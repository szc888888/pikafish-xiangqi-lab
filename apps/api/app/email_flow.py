"""Single-use email verification and password reset links."""
import hashlib
import os
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from urllib.parse import urlencode

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .persistence import EmailActionToken, LocalCredential, User


def mail_configured() -> bool:
    return all(os.getenv(key, "").strip() for key in ("MAIL_HOST", "MAIL_PORT", "MAIL_FROM", "MAIL_USERNAME", "MAIL_PASSWORD", "PUBLIC_BASE_URL"))


def email_verification_required() -> bool:
    return os.getenv("EMAIL_VERIFICATION_REQUIRED", "false").strip().lower() in {"1", "true", "yes", "on"}


def deliver_email(address: str, purpose: str, token: str) -> None:
    if not mail_configured():
        raise HTTPException(status_code=503, detail={"code": "mail_not_configured", "message": "邮件服务尚未配置，暂时不能完成此操作"})
    base = os.environ["PUBLIC_BASE_URL"].strip().rstrip("/")
    if os.getenv("APP_ENV") == "production" and not base.startswith("https://"):
        raise HTTPException(status_code=503, detail={"code": "mail_url_insecure", "message": "邮件链接必须使用 HTTPS"})
    action = "verify" if purpose == "verify" else "reset"
    link = f"{base}/#{urlencode({'email_action': action, 'token': token})}"
    message = EmailMessage()
    message["From"] = os.environ["MAIL_FROM"]
    message["To"] = address
    message["Subject"] = "AI 象棋教练邮箱验证" if purpose == "verify" else "AI 象棋教练重置密码"
    message.set_content(f"请在链接有效期内完成操作：\n{link}\n若非本人发起，请忽略此邮件。")
    try:
        port = int(os.environ["MAIL_PORT"])
        if not 1 <= port <= 65535:
            raise ValueError("port out of range")
        mode = os.getenv("MAIL_TLS_MODE", "starttls").strip().lower()
        if mode == "ssl":
            with smtplib.SMTP_SSL(os.environ["MAIL_HOST"], port, timeout=10) as smtp:
                smtp.login(os.environ["MAIL_USERNAME"], os.environ["MAIL_PASSWORD"])
                smtp.send_message(message)
        elif mode == "starttls":
            with smtplib.SMTP(os.environ["MAIL_HOST"], port, timeout=10) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(os.environ["MAIL_USERNAME"], os.environ["MAIL_PASSWORD"])
                smtp.send_message(message)
        else:
            raise ValueError("unsupported mail TLS mode")
    except (OSError, smtplib.SMTPException, ValueError) as exc:
        raise HTTPException(status_code=503, detail={"code": "mail_delivery_failed", "message": "邮件暂时无法发送，请稍后重试"}) from exc


def issue_token(db: Session, credential: LocalCredential, purpose: str) -> None:
    now = datetime.now(timezone.utc)
    recent = db.scalar(select(EmailActionToken).where(EmailActionToken.user_id == credential.user_id, EmailActionToken.purpose == purpose, EmailActionToken.created_at >= now - timedelta(seconds=60)).order_by(EmailActionToken.created_at.desc()))
    if recent:
        return
    raw = secrets.token_urlsafe(32)
    token = EmailActionToken(user_id=credential.user_id, purpose=purpose, token_hash=hashlib.sha256(raw.encode()).hexdigest(), expires_at=now + (timedelta(hours=24) if purpose == "verify" else timedelta(minutes=30)))
    deliver_email(credential.email, purpose, raw)
    db.add(token)


def consume_token(db: Session, raw: str, purpose: str) -> LocalCredential:
    digest = hashlib.sha256(raw.encode()).hexdigest()
    token = db.scalar(select(EmailActionToken).where(EmailActionToken.token_hash == digest, EmailActionToken.purpose == purpose).with_for_update())
    now = datetime.now(timezone.utc)
    expires = token.expires_at if token else None
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if token is None or token.used_at or expires is None or expires <= now:
        raise HTTPException(status_code=400, detail={"code": "email_token_invalid", "message": "链接无效或已过期"})
    credential = db.scalar(select(LocalCredential).where(LocalCredential.user_id == token.user_id))
    if credential is None:
        raise HTTPException(status_code=400, detail={"code": "email_token_invalid", "message": "链接无效或已过期"})
    token.used_at = now
    return credential


def revoke_tokens(db: Session, user_id: str, purpose: str) -> None:
    db.execute(
        update(EmailActionToken)
        .where(EmailActionToken.user_id == user_id, EmailActionToken.purpose == purpose, EmailActionToken.used_at.is_(None))
        .values(used_at=datetime.now(timezone.utc))
    )


def request_action(db: Session, email: str, purpose: str) -> None:
    if not mail_configured():
        raise HTTPException(status_code=503, detail={"code": "mail_not_configured", "message": "邮件服务尚未配置，暂时不能完成此操作"})
    credential = db.scalar(select(LocalCredential).where(LocalCredential.email == email))
    if credential is not None and (purpose != "verify" or not credential.email_verified):
        issue_token(db, credential, purpose)
        db.commit()
