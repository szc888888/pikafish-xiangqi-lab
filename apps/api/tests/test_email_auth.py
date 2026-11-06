import os
import logging
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///./test_email_auth.db"
os.environ["AUTH_MODE"] = "email"

from app.main import app  # noqa: E402
from app.database import reset_database, SessionLocal  # noqa: E402
from app.persistence import LocalCredential, PrivacyConsent, EmailActionToken  # noqa: E402


class _AuthRecordHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def setup_function():
    os.environ["AUTH_MODE"] = "email"
    os.environ["EMAIL_VERIFICATION_REQUIRED"] = "true"
    reset_database()


def teardown_function():
    os.environ.pop("EMAIL_VERIFICATION_REQUIRED", None)
    reset_database()


def test_register_requires_policy_consent_and_sends_verification(monkeypatch):
    sent = []
    monkeypatch.setattr("app.email_flow.deliver_email", lambda email, purpose, token: sent.append((email, purpose, token)))
    with TestClient(app) as client:
        without_consent = client.post("/auth/email/register", json={"email": " Alice@Example.COM ", "password": "correct horse battery", "display_name": "Alice"})
        assert without_consent.status_code == 422
        response = client.post("/auth/email/register", json={"email": " Alice@Example.COM ", "password": "correct horse battery", "display_name": "Alice", "accept_privacy": True, "policy_version": "v1.0"})
        assert response.status_code == 201
        assert response.json()["user"]["display_name"] == "Alice"
        with SessionLocal() as db:
            row = db.query(LocalCredential).one()
            assert row.email == "alice@example.com"
            assert row.password_hash != "correct horse battery"
            assert row.password_hash.startswith("$argon2")
            assert db.query(PrivacyConsent).one().policy_version == "v1.0"
            assert db.query(EmailActionToken).one().token_hash != sent[0][2]
        assert client.get("/api/me").status_code == 401
        assert client.post("/auth/email/login", json={"email": "alice@example.com", "password": "correct horse battery"}).status_code == 403
        verified = client.post("/auth/email/verify", json={"token": sent[0][2]})
        assert verified.status_code == 200
        assert client.post("/auth/email/verify", json={"token": sent[0][2]}).status_code == 400
        assert client.post("/auth/email/login", json={"email": "alice@example.com", "password": "correct horse battery"}).status_code == 200
        assert client.get("/api/me").status_code == 200


def test_duplicate_email_and_wrong_password_are_generic_errors(monkeypatch):
    monkeypatch.setattr("app.email_flow.deliver_email", lambda *args: None)
    with TestClient(app) as client:
        client.post("/auth/email/register", json={"email": "alice@example.com", "password": "correct horse battery", "accept_privacy": True, "policy_version": "v1.0"})
        duplicate = client.post("/auth/email/register", json={"email": " ALICE@example.com ", "password": "another password", "accept_privacy": True, "policy_version": "v1.0"})
        assert duplicate.status_code == 409
        wrong = client.post("/auth/email/login", json={"email": "alice@example.com", "password": "wrong password"})
        assert wrong.status_code == 401
        assert wrong.json()["detail"]["code"] == "invalid_credentials"


def test_password_reset_token_expires_and_cannot_be_reused(monkeypatch):
    sent = []
    monkeypatch.setattr("app.email_flow.deliver_email", lambda email, purpose, token: sent.append((email, purpose, token)))
    monkeypatch.setattr("app.email_flow.mail_configured", lambda: True)
    with TestClient(app) as client:
        client.post("/auth/email/register", json={"email": "alice@example.com", "password": "old password 123", "accept_privacy": True, "policy_version": "v1.0"})
        client.post("/auth/email/verify", json={"token": sent[-1][2]})
        client.post("/auth/email/login", json={"email": "alice@example.com", "password": "old password 123"})
        assert client.post("/auth/email/password/forgot", json={"email": "missing@example.com"}).status_code == 200
        assert client.post("/auth/email/password/forgot", json={"email": "alice@example.com"}).status_code == 200
        token = sent[-1][2]
        assert client.post("/auth/email/password/reset", json={"token": token, "password": "new password 123"}).status_code == 200
        assert client.get("/api/me").status_code == 401
        assert client.post("/auth/email/password/reset", json={"token": token, "password": "third password 123"}).status_code == 400
        assert client.post("/auth/email/login", json={"email": "alice@example.com", "password": "old password 123"}).status_code == 401
        assert client.post("/auth/email/login", json={"email": "alice@example.com", "password": "new password 123"}).status_code == 200


def test_password_reset_revokes_other_outstanding_links(monkeypatch):
    sent = []
    monkeypatch.setattr("app.email_flow.deliver_email", lambda email, purpose, token: sent.append((purpose, token)))
    monkeypatch.setattr("app.email_flow.mail_configured", lambda: True)
    with TestClient(app) as client:
        assert client.post("/auth/email/register", json={"email": "alice@example.com", "password": "old password 123", "accept_privacy": True, "policy_version": "v1.0"}).status_code == 201
        assert client.post("/auth/email/verify", json={"token": sent[-1][1]}).status_code == 200
        assert client.post("/auth/email/password/forgot", json={"email": "alice@example.com"}).status_code == 200
        first = sent[-1][1]
        with SessionLocal() as db:
            token = db.query(EmailActionToken).filter_by(purpose="reset").one()
            token.created_at = datetime.now(timezone.utc) - timedelta(minutes=2)
            db.commit()
        assert client.post("/auth/email/password/forgot", json={"email": "alice@example.com"}).status_code == 200
        second = sent[-1][1]
        assert second != first
        assert client.post("/auth/email/password/reset", json={"token": first, "password": "new password 123"}).status_code == 200
        assert client.post("/auth/email/password/reset", json={"token": second, "password": "other password 123"}).status_code == 400


def test_password_reset_clears_login_lockout(monkeypatch):
    sent = []
    monkeypatch.setattr("app.email_flow.deliver_email", lambda email, purpose, token: sent.append(token))
    monkeypatch.setattr("app.email_flow.mail_configured", lambda: True)
    with TestClient(app) as client:
        assert client.post("/auth/email/register", json={"email": "alice@example.com", "password": "old password 123", "accept_privacy": True, "policy_version": "v1.0"}).status_code == 201
        assert client.post("/auth/email/verify", json={"token": sent[-1]}).status_code == 200
        with SessionLocal() as db:
            credential = db.query(LocalCredential).one()
            credential.locked_until = datetime.now(timezone.utc) + timedelta(minutes=15)
            db.commit()
        assert client.post("/auth/email/password/forgot", json={"email": "alice@example.com"}).status_code == 200
        assert client.post("/auth/email/password/reset", json={"token": sent[-1], "password": "new password 123"}).status_code == 200
        assert client.post("/auth/email/login", json={"email": "alice@example.com", "password": "new password 123"}).status_code == 200


def test_login_lockout_returns_auth_error_instead_of_server_error(monkeypatch):
    sent = []
    monkeypatch.setattr("app.email_flow.deliver_email", lambda email, purpose, token: sent.append(token))
    with TestClient(app) as client:
        assert client.post("/auth/email/register", json={"email": "alice@example.com", "password": "password 123", "accept_privacy": True, "policy_version": "v1.0"}).status_code == 201
        assert client.post("/auth/email/verify", json={"token": sent[-1]}).status_code == 200
        for _ in range(5):
            assert client.post("/auth/email/login", json={"email": "alice@example.com", "password": "incorrect"}).status_code == 401
        assert client.post("/auth/email/login", json={"email": "alice@example.com", "password": "password 123"}).status_code == 401


def test_registration_without_mail_is_verified_and_can_login(monkeypatch):
    for key in ("MAIL_HOST", "MAIL_FROM", "MAIL_USERNAME", "MAIL_PASSWORD", "PUBLIC_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("EMAIL_VERIFICATION_REQUIRED", "false")
    with TestClient(app) as client:
        result = client.post("/auth/email/register", json={"email": "alice@example.com", "password": "password 123", "accept_privacy": True, "policy_version": "v1.0"})
        assert result.status_code == 201
        assert result.json()["email_verified"] is True
        assert result.json()["verification_required"] is False
        assert client.post("/auth/email/login", json={"email": "alice@example.com", "password": "password 123"}).status_code == 200


def test_register_and_login_emit_structured_auth_events(monkeypatch):
    monkeypatch.setenv("EMAIL_VERIFICATION_REQUIRED", "false")
    handler = _AuthRecordHandler()
    logger = logging.getLogger("app.auth")
    logger.addHandler(handler)
    try:
        with TestClient(app) as client:
            registered = client.post("/auth/email/register", json={"email": "alice@example.com", "password": "password 123", "accept_privacy": True, "policy_version": "v1.0"})
            assert registered.status_code == 201
            logged_in = client.post("/auth/email/login", json={"email": "alice@example.com", "password": "password 123"})
            assert logged_in.status_code == 200
            wrong_password = client.post("/auth/email/login", json={"email": "alice@example.com", "password": "wrong secret"})
            assert wrong_password.status_code == 401
        events = [record for record in handler.records if record.name == "app.auth"]
        register = next(record for record in events if record.event == "auth.register")
        login = next(record for record in events if record.event == "auth.login")
        assert register.outcome == "success"
        assert int(register.status) == 201
        assert register.email_fingerprint
        assert register.user_id
        assert login.outcome == "success"
        assert int(login.status) == 200
        assert login.email_fingerprint == register.email_fingerprint
        assert login.user_id == register.user_id
        failure = next(record for record in events if record.event == "auth.login" and record.outcome == "failure")
        assert int(failure.status) == 401
        assert failure.reason_code == "invalid_credentials"
        assert not any("password" in record.__dict__ or "wrong secret" in record.getMessage() or "alice@example.com" in record.getMessage() for record in events)
    finally:
        logger.removeHandler(handler)


def test_verification_token_expires(monkeypatch):
    sent = []
    monkeypatch.setattr("app.email_flow.deliver_email", lambda email, purpose, token: sent.append(token))
    with TestClient(app) as client:
        client.post("/auth/email/register", json={"email": "alice@example.com", "password": "password 123", "accept_privacy": True, "policy_version": "v1.0"})
        with SessionLocal() as db:
            token = db.query(EmailActionToken).one()
            token.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        assert client.post("/auth/email/verify", json={"token": sent[0]}).status_code == 400


def test_unconfigured_oidc_advertises_email_login():
    os.environ["AUTH_MODE"] = "oidc"
    for key in ("OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET"):
        os.environ.pop(key, None)
    with TestClient(app) as client:
        response = client.get("/api/auth/methods")
        assert response.status_code == 200
        assert response.json() == {"email": True, "oidc": False, "email_verification_required": True}
