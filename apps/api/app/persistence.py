from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    session_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    identities: Mapped[list["UserIdentity"]] = relationship(cascade="all, delete-orphan")


class UserIdentity(Base):
    __tablename__ = "user_identities"
    __table_args__ = (UniqueConstraint("issuer", "subject", name="uq_identity_issuer_subject"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    issuer: Mapped[str] = mapped_column(String(500))
    subject: Mapped[str] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LocalCredential(Base):
    __tablename__ = "local_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(500))
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EmailActionToken(Base):
    __tablename__ = "email_action_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(24), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PrivacyConsent(Base):
    __tablename__ = "privacy_consents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    policy_type: Mapped[str] = mapped_column(String(32))
    policy_version: Mapped[str] = mapped_column(String(64))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Game(Base):
    __tablename__ = "games"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    initial_fen: Mapped[str] = mapped_column(String(220))
    current_fen: Mapped[str] = mapped_column(String(220))
    engine_settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    red_to_move: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    moves: Mapped[list["GameMove"]] = relationship(order_by="GameMove.ply", cascade="all, delete-orphan")


class GameMove(Base):
    __tablename__ = "game_moves"
    __table_args__ = (UniqueConstraint("game_id", "ply", name="uq_game_move_ply"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    ply: Mapped[int] = mapped_column(Integer)
    side: Mapped[str] = mapped_column(String(8))
    uci: Mapped[str] = mapped_column(String(8))
    notation_zh: Mapped[str] = mapped_column(String(32))
    before_fen: Mapped[str] = mapped_column(String(220))
    after_fen: Mapped[str] = mapped_column(String(220))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    game_id: Mapped[str] = mapped_column(ForeignKey("games.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    game_version: Mapped[int] = mapped_column(Integer)
    initial_fen_snapshot: Mapped[str] = mapped_column(String(220))
    moves_snapshot: Mapped[list] = mapped_column(JSON)
    history_hash: Mapped[str] = mapped_column(String(128))
    engine_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    engine_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    nnue_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list["ReviewItem"]] = relationship(order_by="ReviewItem.ply", cascade="all, delete-orphan")


class ReviewItem(Base):
    __tablename__ = "review_items"
    __table_args__ = (UniqueConstraint("review_id", "ply", name="uq_review_item_ply"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    review_id: Mapped[str] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), index=True)
    ply: Mapped[int] = mapped_column(Integer)
    side: Mapped[str] = mapped_column(String(8))
    move: Mapped[str] = mapped_column(String(8))
    best_move: Mapped[str | None] = mapped_column(String(8), nullable=True)
    before_score: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_score: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    loss_cp: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mate_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    grade: Mapped[str] = mapped_column(String(24), default="unknown")
    pv: Mapped[list] = mapped_column(JSON, default=list)
    rule_stop_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rule_stop_message: Mapped[str | None] = mapped_column(Text, nullable=True)


class DataRequest(Base):
    __tablename__ = "data_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    artifact_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)


class DeletionTombstone(Base):
    __tablename__ = "deletion_tombstones"

    user_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    purge_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
