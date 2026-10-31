"""Versioned privacy acceptance shared by registration and OIDC."""
import os
import base64
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .email_flow import email_verification_required
from .persistence import PrivacyConsent, User


def policy_version() -> str:
    return os.getenv("PRIVACY_POLICY_VERSION", "v1.0").strip() or "v1.0"


def ensure_current_version(version: str) -> None:
    if version != policy_version():
        raise HTTPException(status_code=409, detail={"code": "privacy_policy_changed", "message": "隐私政策已更新，请重新阅读并同意"})


def has_consent(db: Session, user_id: str) -> bool:
    return db.scalar(select(PrivacyConsent.id).where(PrivacyConsent.user_id == user_id, PrivacyConsent.policy_type == "privacy", PrivacyConsent.policy_version == policy_version(), PrivacyConsent.withdrawn_at.is_(None))) is not None


def record_consent(db: Session, user: User, version: str) -> None:
    ensure_current_version(version)
    if not has_consent(db, user.id):
        db.add(PrivacyConsent(user_id=user.id, policy_type="privacy", policy_version=version, accepted_at=datetime.now(timezone.utc)))


def publication_missing() -> list[str]:
    required = ["PRIVACY_OPERATOR_NAME", "PRIVACY_CONTACT_EMAIL", "PRIVACY_EFFECTIVE_DATE", "PRIVACY_THIRD_PARTY_DISCLOSURE", "PRIVACY_BACKUP_STORAGE_DESCRIPTION", "BACKUP_OUTPUT_DIR", "BACKUP_ENCRYPTION_KEY", "DELETION_LEDGER_PATH"]
    if email_verification_required():
        required.extend(["MAIL_HOST", "MAIL_PORT", "MAIL_FROM", "MAIL_USERNAME", "MAIL_PASSWORD", "PUBLIC_BASE_URL"])
    missing = [key for key in required if not os.getenv(key, "").strip()]
    if os.getenv("PRIVACY_POLICY_APPROVED") != "1":
        missing.append("PRIVACY_POLICY_APPROVED=1")
    if os.getenv("COOKIE_SECURE") != "1":
        missing.append("COOKIE_SECURE=1")
    if len(os.getenv("SESSION_SECRET", "")) < 32:
        missing.append("SESSION_SECRET>=32")
    if not os.getenv("PUBLIC_BASE_URL", "").startswith("https://"):
        missing.append("PUBLIC_BASE_URL=https")
    if os.getenv("AUTH_MODE") == "dev":
        missing.append("AUTH_MODE!=dev")
    if not os.getenv("DATABASE_URL", "").startswith("postgresql+psycopg://"):
        missing.append("DATABASE_URL=postgresql")
    encoded = os.getenv("BACKUP_ENCRYPTION_KEY", "")
    if encoded:
        try:
            if len(base64.b64decode(encoded, validate=True)) != 32:
                missing.append("BACKUP_ENCRYPTION_KEY=32-byte-base64")
        except ValueError:
            missing.append("BACKUP_ENCRYPTION_KEY=32-byte-base64")
    return missing


def validate_publication_configuration() -> None:
    if os.getenv("APP_ENV", "development").lower() == "production":
        missing = publication_missing()
        if missing:
            raise RuntimeError("Production configuration incomplete: " + ", ".join(missing))
