import os
import re
import hashlib
import hmac
from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .persistence import LocalCredential, User, UserIdentity
from . import email_flow
from .privacy import has_consent, record_consent
from .logging_config import get_logger


password_hasher = PasswordHasher()
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
logger = get_logger("auth")


def email_fingerprint(value: str) -> str:
    """Return a stable keyed fingerprint without putting an email in logs."""
    normalized = value.strip().lower()
    key = os.getenv("AUTH_LOG_FINGERPRINT_KEY") or os.getenv("SESSION_SECRET") or "development-only-auth-log-key"
    return hmac.new(key.encode("utf-8"), normalized.encode("utf-8"), hashlib.sha256).hexdigest()[:24]


def log_auth_event(action: str, email_value: str, *, outcome: str, status: int,
                   reason_code: str | None = None, user_id: str | None = None,
                   auth_method: str = "email") -> None:
    extra = {
        "event": f"auth.{action}", "auth_method": auth_method, "outcome": outcome,
        "status": status, "email_fingerprint": email_fingerprint(email_value),
    }
    if reason_code:
        extra["reason_code"] = reason_code
    if user_id:
        extra["user_id"] = user_id
    logger.info(f"auth_{action}_{outcome}", extra=extra)


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if len(email) > 320 or not EMAIL_RE.fullmatch(email):
        raise HTTPException(status_code=422, detail={"code": "invalid_email", "message": "请输入有效邮箱地址"})
    return email


def oidc_configured() -> bool:
    return all(os.getenv(key, "").strip() for key in ("OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_REDIRECT_URI"))


def auth_mode() -> str:
    configured = os.getenv("AUTH_MODE", "oidc").strip().lower()
    if configured == "dev":
        return "dev"
    if configured == "email":
        return "email"
    return "oidc" if oidc_configured() else "email"


def _resolve_user(request: Request, db: Session, *, allow_pending: bool = False) -> User:
    if auth_mode() == "dev":
        subject = request.headers.get("X-Dev-User", "local-dev").strip()
        if not subject or len(subject) > 120:
            raise HTTPException(status_code=401, detail={"code": "invalid_identity", "message": "开发身份无效"})
        issuer = "dev"
        identity = db.scalar(select(UserIdentity).where(UserIdentity.issuer == issuer, UserIdentity.subject == subject))
        if identity is None:
            user = User(display_name=subject)
            db.add(user)
            db.flush()
            identity = UserIdentity(user_id=user.id, issuer=issuer, subject=subject)
            db.add(identity)
        user = db.get(User, identity.user_id)
        if user is None or (user.status != "active" and not (allow_pending and user.status == "deletion_pending")):
            raise HTTPException(status_code=410, detail={"code": "account_unavailable", "message": "账号不可用"})
        identity.last_login_at = datetime.now(timezone.utc)
        db.commit()
        return user
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail={"code": "authentication_required", "message": "请先登录"})
    user = db.get(User, user_id)
    if user is None or (user.status != "active" and not (allow_pending and user.status == "deletion_pending")):
        raise HTTPException(status_code=410, detail={"code": "account_unavailable", "message": "账号不可用"})
    if request.session.get("session_version") != user.session_version:
        request.session.clear()
        raise HTTPException(status_code=401, detail={"code": "session_expired", "message": "请重新登录"})
    db.commit()
    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    return _resolve_user(request, db)


def get_deletion_user(request: Request, db: Session = Depends(get_db)) -> User:
    return _resolve_user(request, db, allow_pending=True)


def get_consented_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = _resolve_user(request, db)
    if auth_mode() != "dev" and not has_consent(db, user.id):
        raise HTTPException(status_code=403, detail={"code": "privacy_consent_required", "message": "请先阅读并同意隐私政策"})
    return user


def register_email(request: Request, db: Session, email_value: str, password: str, display_name: str | None, policy_version: str) -> User:
    email = normalize_email(email_value)
    if db.scalar(select(LocalCredential).where(LocalCredential.email == email)) is not None:
        raise HTTPException(status_code=409, detail={"code": "email_already_registered", "message": "该邮箱已注册"})
    user = User(display_name=(display_name or email.split("@", 1)[0]).strip()[:120])
    db.add(user)
    db.flush()
    credential = LocalCredential(user_id=user.id, email=email, password_hash=password_hasher.hash(password), email_verified=not email_flow.email_verification_required())
    db.add(credential)
    record_consent(db, user, policy_version)
    try:
        if email_flow.email_verification_required():
            email_flow.issue_token(db, credential, "verify")
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(user)
    request.session.clear()
    return user


def login_email(request: Request, db: Session, email_value: str, password: str) -> User:
    email = normalize_email(email_value)
    credential = db.scalar(select(LocalCredential).where(LocalCredential.email == email))
    now = datetime.now(timezone.utc)
    invalid = HTTPException(status_code=401, detail={"code": "invalid_credentials", "message": "邮箱或密码错误"})
    locked_until = credential.locked_until if credential else None
    if locked_until is not None and locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=timezone.utc)
    if credential is None or locked_until is not None and locked_until > now:
        raise invalid
    try:
        valid = password_hasher.verify(credential.password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        valid = False
    if not valid:
        credential.failed_attempts += 1
        if credential.failed_attempts >= 5:
            from datetime import timedelta

            credential.locked_until = now + timedelta(minutes=15)
            credential.failed_attempts = 0
        db.commit()
        raise invalid
    if password_hasher.check_needs_rehash(credential.password_hash):
        credential.password_hash = password_hasher.hash(password)
    credential.failed_attempts = 0
    credential.locked_until = None
    credential.last_login_at = now
    user = db.get(User, credential.user_id)
    if user is None or user.status not in {"active", "deletion_pending"}:
        raise HTTPException(status_code=410, detail={"code": "account_unavailable", "message": "账号不可用"})
    if not credential.email_verified:
        raise HTTPException(status_code=403, detail={"code": "email_verification_required", "message": "请先验证邮箱"})
    db.commit()
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["auth_method"] = "email"
    request.session["session_version"] = user.session_version
    return user
