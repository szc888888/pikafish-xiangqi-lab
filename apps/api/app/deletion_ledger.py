"""Purge expired accounts and replay an external deletion ledger after restore."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .database import SessionLocal
from .persistence import DataRequest, DeletionTombstone, EmailActionToken, Game, GameMove, LocalCredential, PrivacyConsent, Review, ReviewItem, User, UserIdentity
from .settings import PROJECT_ROOT


def ledger_path() -> Path:
    return Path(os.getenv("DELETION_LEDGER_PATH", str(PROJECT_ROOT / "backups" / "deletion-ledger.jsonl"))).resolve()


def export_artifact_path(key: str | None) -> Path | None:
    if not key:
        return None
    export_root = Path(os.getenv("EXPORT_ROOT", str(PROJECT_ROOT / "exports"))).resolve()
    path = Path(key).resolve()
    return path if path.is_relative_to(export_root) and path != export_root else None


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _append_purge(user_id: str, requested_at: datetime, purged_at: datetime) -> None:
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({"event": "purged", "user_id": user_id, "requested_at": _utc(requested_at).isoformat(), "purge_completed_at": purged_at.isoformat()}, separators=(",", ":")) + "\n"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(line)
        stream.flush()
        os.fsync(stream.fileno())


def _delete_user_data(db: Session, user_id: str) -> list[Path]:
    game_ids = list(db.scalars(select(Game.id).where(Game.user_id == user_id)))
    review_ids = list(db.scalars(select(Review.id).where(Review.user_id == user_id)))
    artifacts = []
    for key in db.scalars(select(DataRequest.artifact_key).where(DataRequest.user_id == user_id, DataRequest.artifact_key.is_not(None))):
        path = export_artifact_path(key)
        if path is not None:
            artifacts.append(path)
    if review_ids:
        db.execute(delete(ReviewItem).where(ReviewItem.review_id.in_(review_ids)))
    db.execute(delete(Review).where(Review.user_id == user_id))
    if game_ids:
        db.execute(delete(GameMove).where(GameMove.game_id.in_(game_ids)))
    db.execute(delete(Game).where(Game.user_id == user_id))
    for model in (DataRequest, EmailActionToken, LocalCredential, PrivacyConsent, UserIdentity):
        db.execute(delete(model).where(model.user_id == user_id))
    db.execute(delete(User).where(User.id == user_id))
    return artifacts


def purge_expired_deletions() -> int:
    now = datetime.now(timezone.utc)
    purged = 0
    with SessionLocal() as db:
        users = db.scalars(select(User).where(User.status == "deletion_pending")).all()
        for user in users:
            request = db.scalar(select(DataRequest).where(DataRequest.user_id == user.id, DataRequest.type == "delete", DataRequest.status == "pending").order_by(DataRequest.requested_at.desc()))
            if request is None or request.expires_at is None or _utc(request.expires_at) > now:
                continue
            tombstone = db.get(DeletionTombstone, user.id)
            requested_at = tombstone.requested_at if tombstone else request.requested_at
            _append_purge(user.id, requested_at, now)
            artifacts = _delete_user_data(db, user.id)
            if tombstone is None:
                db.add(DeletionTombstone(user_id=user.id, requested_at=requested_at, purge_completed_at=now))
            else:
                tombstone.purge_completed_at = now
            db.commit()
            for path in artifacts:
                path.unlink(missing_ok=True)
            purged += 1
    return purged


def purge_expired_exports() -> int:
    now = datetime.now(timezone.utc)
    paths = []
    expired = 0
    with SessionLocal() as db:
        requests = db.scalars(select(DataRequest).where(DataRequest.type == "export", DataRequest.status.in_(("ready", "expired")), DataRequest.expires_at.is_not(None))).all()
        for request in requests:
            if _utc(request.expires_at) > now:
                continue
            if request.status == "ready":
                request.status = "expired"
                expired += 1
            path = export_artifact_path(request.artifact_key)
            if path is not None:
                paths.append(path)
        db.commit()
    for path in paths:
        path.unlink(missing_ok=True)
    return expired


def replay_deletions(db: Session, path: Path) -> int:
    if not path.is_file():
        raise FileNotFoundError(path)
    events = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("event") != "purged":
            raise ValueError("Invalid deletion ledger event")
        user_id = str(UUID(record["user_id"]))
        requested_at = datetime.fromisoformat(record["requested_at"])
        purged_at = datetime.fromisoformat(record["purge_completed_at"])
        events[user_id] = (requested_at, purged_at)
    removed = 0
    for user_id, (requested_at, purged_at) in events.items():
        if db.get(User, user_id) is not None:
            _delete_user_data(db, user_id)
            removed += 1
        tombstone = db.get(DeletionTombstone, user_id)
        if tombstone is None:
            db.add(DeletionTombstone(user_id=user_id, requested_at=requested_at, purge_completed_at=purged_at))
        else:
            tombstone.purge_completed_at = purged_at
        db.commit()
    return removed


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["purge", "replay"])
    parser.add_argument("--ledger", type=Path)
    arguments = parser.parse_args()
    if arguments.command == "purge":
        print(f"purged_accounts={purge_expired_deletions()} expired_exports={purge_expired_exports()}")
    else:
        if arguments.ledger is None:
            parser.error("--ledger is required for replay")
        with SessionLocal() as session:
            print(f"removed_restored_users={replay_deletions(session, arguments.ledger)}")
