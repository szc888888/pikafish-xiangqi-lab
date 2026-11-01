import os
import json
from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient


os.environ["DATABASE_URL"] = "sqlite+pysqlite:///./test_persistence.db"
os.environ["AUTH_MODE"] = "dev"

from app.main import app  # noqa: E402
from app.database import reset_database  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.main import purge_expired_deletions  # noqa: E402
from app.deletion_ledger import purge_expired_exports, replay_deletions  # noqa: E402
from app.persistence import DataRequest, DeletionTombstone, Game, LocalCredential, PrivacyConsent, Review, ReviewItem, User  # noqa: E402
from datetime import datetime, timedelta, timezone
from sqlalchemy import select


@pytest.fixture(autouse=True)
def clean_database():
    os.environ["AUTH_MODE"] = "dev"
    reset_database()
    yield
    reset_database()


def test_game_and_moves_are_persisted_and_owned_by_dev_user():
    with TestClient(app) as client:
        response = client.post(
            "/api/games",
            headers={"X-Dev-User": "alice"},
            json={"name": "测试棋局", "initial_fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"},
        )
        assert response.status_code == 201
        game = response.json()
        move = client.post(
            f"/api/games/{game['id']}/moves",
            headers={"X-Dev-User": "alice"},
            json={"expected_version": 0, "uci": "a3a4"},
        )
        assert move.status_code == 201
        assert move.json()["version"] == 1
        fetched = client.get(f"/api/games/{game['id']}", headers={"X-Dev-User": "alice"})
        assert fetched.status_code == 200
        assert fetched.json()["moves"][0]["uci"] == "a3a4"


def test_stale_game_version_is_rejected_without_a_second_move():
    with TestClient(app) as client:
        game = client.post(
            "/api/games",
            headers={"X-Dev-User": "alice"},
            json={"name": "版本", "initial_fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"},
        ).json()
        first = client.post(f"/api/games/{game['id']}/moves", headers={"X-Dev-User": "alice"}, json={"expected_version": 0, "uci": "a3a4"})
        assert first.status_code == 201
        stale = client.post(f"/api/games/{game['id']}/moves", headers={"X-Dev-User": "alice"}, json={"expected_version": 0, "uci": "a6a5"})
        assert stale.status_code == 409
        current = client.get(f"/api/games/{game['id']}", headers={"X-Dev-User": "alice"}).json()
        assert len(current["moves"]) == 1


def test_game_engine_settings_round_trip_on_create_and_append_move():
    settings = {"difficulty": "custom", "allow_suboptimal": False, "depth": 3, "movetime_ms": 500, "threads": 2, "hash_mb": 128}
    with TestClient(app) as client:
        headers = {"X-Dev-User": "settings-owner"}
        created = client.post(
            "/api/games", headers=headers,
            json={"name": "档位存档", "initial_fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1", "engine_settings": settings},
        )
        assert created.status_code == 201
        assert created.json()["engine_settings"] == settings
        moved = client.post(
            f"/api/games/{created.json()['id']}/moves", headers=headers,
            json={"expected_version": 0, "uci": "a3a4", "engine_settings": settings},
        )
        assert moved.status_code == 201
        fetched = client.get(f"/api/games/{created.json()['id']}", headers=headers)
        assert fetched.json()["engine_settings"] == settings


def test_fixed_profile_storage_uses_canonical_preset_parameters():
    fixed_settings = {"difficulty": "progress", "allow_suboptimal": False, "depth": 12, "movetime_ms": 9000, "threads": 4, "hash_mb": 2048}
    with TestClient(app) as client:
        headers = {"X-Dev-User": "canonical-settings"}
        created = client.post(
            "/api/games", headers=headers,
            json={"name": "固定档位", "initial_fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1", "engine_settings": fixed_settings},
        )
        assert created.status_code == 201
        expected = {"difficulty": "progress", "allow_suboptimal": False, "depth": 4, "movetime_ms": 700, "threads": 1, "hash_mb": 64}
        assert created.json()["engine_settings"] == expected

        moved = client.post(
            f"/api/games/{created.json()['id']}/moves", headers=headers,
            json={"expected_version": 0, "uci": "a3a4", "engine_settings": fixed_settings},
        )
        assert moved.status_code == 201
        assert moved.json()["engine_settings"] == expected


def test_legacy_game_defaults_to_progress_profile():
    with TestClient(app) as client:
        headers = {"X-Dev-User": "legacy-settings"}
        created = client.post(
            "/api/games", headers=headers,
            json={"name": "旧客户端", "initial_fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"},
        )
        assert created.status_code == 201
        assert created.json()["engine_settings"]["difficulty"] == "progress"
        assert created.json()["engine_settings"]["allow_suboptimal"] is True


def test_existing_game_row_with_null_engine_settings_serializes_progress_defaults():
    with TestClient(app) as client:
        headers = {"X-Dev-User": "legacy-null-settings"}
        created = client.post(
            "/api/games", headers=headers,
            json={"name": "历史空字段", "initial_fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"},
        )
        assert created.status_code == 201
        with SessionLocal() as db:
            game = db.get(Game, created.json()["id"])
            game.engine_settings = None
            db.commit()

        fetched = client.get(f"/api/games/{created.json()['id']}", headers=headers)
        assert fetched.status_code == 200
        assert fetched.json()["engine_settings"] == {
            "difficulty": "progress", "allow_suboptimal": True, "depth": 4, "movetime_ms": 700,
            "threads": 1, "hash_mb": 64,
        }


def test_invalid_engine_settings_are_rejected():
    with TestClient(app) as client:
        response = client.post(
            "/api/games", headers={"X-Dev-User": "invalid-settings"},
            json={"name": "错误档位", "initial_fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1", "engine_settings": {"difficulty": "super", "depth": 2, "movetime_ms": 100, "threads": 1, "hash_mb": 16}},
        )
        assert response.status_code == 422


def test_export_and_delete_requests_require_the_authenticated_user():
    with TestClient(app) as client:
        export_response = client.post("/api/me/exports", headers={"X-Dev-User": "alice"})
        assert export_response.status_code == 202
        deletion = client.post("/api/me/deletion", headers={"X-Dev-User": "alice"})
        assert deletion.status_code == 202
        assert deletion.json()["status"] == "pending"
        blocked = client.post("/api/games", headers={"X-Dev-User": "alice"}, json={"name": "禁止", "initial_fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"})
        assert blocked.status_code == 410


def test_export_contains_account_consent_and_full_review_without_credentials():
    with TestClient(app) as client:
        headers = {"X-Dev-User": "export-owner"}
        user_id = client.get("/api/me", headers=headers).json()["id"]
        game = client.post("/api/games", headers=headers, json={"initial_fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"}).json()
        with SessionLocal() as db:
            db.add(LocalCredential(user_id=user_id, email="owner@example.com", password_hash="secret-hash", email_verified=True))
            db.add(PrivacyConsent(user_id=user_id, policy_type="privacy", policy_version="v1.0"))
            review = Review(user_id=user_id, game_id=game["id"], game_version=0, initial_fen_snapshot=game["initial_fen"], moves_snapshot=[], history_hash="test", parameters={}, status="completed", summary="复盘摘要")
            db.add(review)
            db.flush()
            db.add(ReviewItem(review_id=review.id, ply=1, side="red", move="a3a4", best_move="a3a4", loss_cp=12, grade="good", pv=["a3a4"]))
            db.commit()
        export = client.post("/api/me/exports", headers=headers)
        assert export.status_code == 202
        download = client.get(export.json()["download_url"], headers=headers)
        assert download.status_code == 200
        with ZipFile(BytesIO(download.content)) as archive:
            account = json.loads(archive.read("account.json"))
            consents = json.loads(archive.read("privacy_consents.json"))
            reviews = json.loads(archive.read("reviews.json"))
            assert account["id"] == user_id
            assert account["local_email"] == "owner@example.com"
            assert "password_hash" not in str(account)
            assert consents[0]["policy_version"] == "v1.0"
            assert reviews[0]["summary"] == "复盘摘要"
            assert reviews[0]["items"][0]["loss_cp"] == 12


def test_expired_export_file_is_removed_by_cleanup(tmp_path, monkeypatch):
    monkeypatch.setenv("EXPORT_ROOT", str(tmp_path))
    with TestClient(app) as client:
        response = client.post("/api/me/exports", headers={"X-Dev-User": "export-owner"})
        request_id = response.json()["id"]
        artifact = tmp_path / f"{request_id}.zip"
        assert artifact.is_file()
        with SessionLocal() as db:
            request = db.get(DataRequest, request_id)
            request.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        assert purge_expired_exports() == 1
        assert not artifact.exists()
        with SessionLocal() as db:
            assert db.get(DataRequest, request_id).status == "expired"


def test_restore_replay_does_not_delete_external_export_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv("EXPORT_ROOT", str(tmp_path))
    with TestClient(app) as client:
        headers = {"X-Dev-User": "restored-owner"}
        user_id = client.get("/api/me", headers=headers).json()["id"]
        export = client.post("/api/me/exports", headers=headers).json()
        artifact = tmp_path / f"{export['id']}.zip"
        assert artifact.is_file()
    now = datetime.now(timezone.utc).isoformat()
    ledger = tmp_path / "deletion-ledger.jsonl"
    ledger.write_text(json.dumps({"event": "purged", "user_id": user_id, "requested_at": now, "purge_completed_at": now}) + "\n", encoding="utf-8")
    with SessionLocal() as db:
        assert replay_deletions(db, ledger) == 1
        assert db.get(User, user_id) is None
    assert artifact.is_file()


def test_pending_deletion_can_be_cancelled_without_reactivating_deleted_data():
    with TestClient(app) as client:
        headers = {"X-Dev-User": "restore-me"}
        game = client.post("/api/games", headers=headers, json={"name": "保留", "initial_fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"}).json()
        assert client.post("/api/me/deletion", headers=headers).status_code == 202
        cancelled = client.post("/api/me/deletion/cancel", headers=headers)
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert client.get(f"/api/games/{game['id']}", headers=headers).status_code == 200
        assert client.post("/api/me/deletion/cancel", headers=headers).status_code == 410


def test_expired_deletion_ledger_removes_user_restored_from_old_backup(tmp_path, monkeypatch):
    ledger = tmp_path / "deletions.jsonl"
    monkeypatch.setenv("DELETION_LEDGER_PATH", str(ledger))
    with TestClient(app) as client:
        headers = {"X-Dev-User": "purge-me"}
        user_id = client.get("/api/me", headers=headers).json()["id"]
        assert client.post("/api/me/deletion", headers=headers).status_code == 202
    with SessionLocal() as db:
        request = db.scalar(select(DataRequest).where(DataRequest.user_id == user_id, DataRequest.type == "delete"))
        request.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    purge_expired_deletions()
    assert ledger.is_file()
    with SessionLocal() as db:
        assert db.get(User, user_id) is None
        assert db.get(DeletionTombstone, user_id).purge_completed_at is not None
        db.add(User(id=user_id, display_name="restored"))
        db.commit()
        assert replay_deletions(db, ledger) == 1
        assert db.get(User, user_id) is None
