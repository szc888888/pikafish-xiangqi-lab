import os

from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///./test_privacy_consent.db"
os.environ["AUTH_MODE"] = "oidc"

from app.main import app  # noqa: E402
from app.database import reset_database, SessionLocal  # noqa: E402
from app.persistence import PrivacyConsent  # noqa: E402
from app.privacy import publication_missing, validate_publication_configuration  # noqa: E402
import pytest

FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"


def setup_function():
    os.environ["AUTH_MODE"] = "oidc"
    reset_database()


def teardown_function():
    reset_database()


def test_oidc_account_must_accept_current_policy_before_saving(monkeypatch):
    async def profile(_):
        return {"issuer": "https://issuer.example", "subject": "subject-1", "email": "a@example.com", "email_verified": True, "display_name": "A"}

    monkeypatch.setattr("app.oidc.callback", profile)
    with TestClient(app) as client:
        assert client.get("/auth/oidc/callback", follow_redirects=False).status_code == 307
        assert client.get("/api/me").json()["privacy_accepted"] is False
        assert client.post("/api/games", json={"initial_fen": FEN}).status_code == 403
        assert client.post("/api/me/privacy-consent", json={"accepted": True, "policy_version": "outdated"}).status_code == 409
        accepted = client.post("/api/me/privacy-consent", json={"accepted": True, "policy_version": "v1.0"})
        assert accepted.status_code == 200
        assert client.post("/api/me/privacy-consent", json={"accepted": True, "policy_version": "v1.0"}).status_code == 200
        assert client.post("/api/games", json={"initial_fen": FEN}).status_code == 201
        with SessionLocal() as db:
            assert db.query(PrivacyConsent).count() == 1


def test_production_startup_rejects_missing_privacy_and_backup_configuration(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("PRIVACY_OPERATOR_NAME", raising=False)
    monkeypatch.delenv("BACKUP_ENCRYPTION_KEY", raising=False)
    with pytest.raises(RuntimeError, match="PRIVACY_OPERATOR_NAME"):
        validate_publication_configuration()


def test_production_requires_applied_database_migrations():
    from app.database import assert_database_migrated

    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        assert_database_migrated()


def test_publication_requires_reviewed_processor_and_backup_disclosures(monkeypatch):
    for name in ("PRIVACY_THIRD_PARTY_DISCLOSURE", "PRIVACY_BACKUP_STORAGE_DESCRIPTION", "PRIVACY_POLICY_APPROVED"):
        monkeypatch.delenv(name, raising=False)
    missing = publication_missing()
    assert "PRIVACY_THIRD_PARTY_DISCLOSURE" in missing
    assert "PRIVACY_BACKUP_STORAGE_DESCRIPTION" in missing
    assert "PRIVACY_POLICY_APPROVED=1" in missing


def test_first_version_does_not_require_mail_configuration(monkeypatch):
    monkeypatch.setenv("EMAIL_VERIFICATION_REQUIRED", "false")
    for name in ("MAIL_HOST", "MAIL_PORT", "MAIL_FROM", "MAIL_USERNAME", "MAIL_PASSWORD", "PUBLIC_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    missing = publication_missing()
    assert not any(name in missing for name in ("MAIL_HOST", "MAIL_PORT", "MAIL_FROM", "MAIL_USERNAME", "MAIL_PASSWORD"))
