import json
import os
import asyncio
from datetime import datetime, timezone
from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

os.environ["AUTH_MODE"] = "dev"

from app import main
from app.database import SessionLocal, reset_database
from app.engine import EngineUnavailable
from app.models import EngineResponse, Score
from app.persistence import Review, ReviewItem, Game, User
from app.xiangqi import START_FEN

# A legal 132-ply game without a repetition draw before the final position.
MOVES = """i3i4 b9a7 h0g2 h7h6 i0h0 i9i7 h2h1 h6h5 f0e1 f9e8 c3c4 e8d7 c4c5 h5g5 h1h2 a7b9 h0h1 b7c7 h2h7 b9a7 h1i1 a7c8 b2f2 c7b7 h7f7 c9a7 i1h1 b7b9 c0e2 g5e5 e2c0 i7g7 f7f5 g7i7 a0a2 b9b2 a3a4 c6c5 f2d2 c8e7 e3e4 a6a5 a2a1 a9c9 b0c2 b2a2 h1h6 c9c8 h6h4 i7h7 f5f8 e5h5 f8f4 c8h8 d2d6 h5e5 d6d3 h7i7 g2e3 e9f9 f4f7 f9e9 a1a0 h8e8 f7f5 i6i5 i4i5 i7i8 d3d2 e7g8 f5g5 g8e7 h4h0 e8c8 h0h2 e5f5 e3g2 f5f1 d2d9 f1f2 g5g4 i8e8 i5h5 g6g5 a4a5 a2a4 c0a2 c8a8 c2b0 a4g4 d9c9 g9i7 g0e2 f2f9 a2c0 e8d8 e2g0 g4f4 a0a1 f4i4 c9c8 a8a9 g3g4 e7g6 e1f2 e9d9 a1a2 d8g8 c8e8 g8f8 b0c2 f8e8 c2d4 e8i8 h2h4 i8f8 h4h3 i4i2 d4e2 f8f4 a5b5 e6e5 g2h0 i2h2 h5i5 a7c9 f2e1 f4f1 i5i6 f1e1 d0e1 f9f1""".split()
OWNER = {"X-Dev-User": "long-review-owner"}
OTHER = {"X-Dev-User": "long-review-other"}


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "dev")
    reset_database()
    yield
    reset_database()


def imported_game(client):
    response = client.post("/api/games/import", headers=OWNER, json={
        "legacy_id": "long-review", "initial_fen": START_FEN, "moves": MOVES,
    })
    assert response.status_code == 201, response.text
    return response.json()


def begin(client, game, **extra):
    return client.post(f"/api/games/{game['id']}/reviews/segmented", headers=OWNER,
                       json={"fen": START_FEN, "moves": MOVES, "depth": 1, "movetime_ms": 1, **extra})


def fake_search(monkeypatch, fail_prefix=None):
    calls = []

    async def analyze(_fen, moves, *_args):
        calls.append(len(moves))
        if len(moves) == fail_prefix:
            raise EngineUnavailable("测试引擎中断")
        return EngineResponse(bestmove=MOVES[len(moves) % 4], score=Score(type="cp", value=len(moves)), pv=[])

    monkeypatch.setattr(main.engine, "analyze", analyze)
    return calls


def test_long_review_persists_every_segment_and_restores_without_reanalysis(monkeypatch, tmp_path):
    monkeypatch.setenv("EXPORT_ROOT", str(tmp_path))
    calls = fake_search(monkeypatch)
    with TestClient(main.app) as client:
        game = imported_game(client)
        initial = begin(client, game)
        assert initial.status_code == 200, initial.text
        state = initial.json()
        review_id = state["review_id"]
        assert state["completed_plies"] == 0
        assert state["status"] == "in_progress"
        for start in range(0, len(MOVES), 30):
            response = client.post(f"/api/reviews/{review_id}/advance", headers=OWNER, json={"start_ply": start})
            assert response.status_code == 200, response.text
            state = response.json()
            assert state["completed_plies"] == min(start + 30, len(MOVES))
        assert state["status"] == "complete"
        assert state["result"]["analyzed_plies"] == 132
        assert [i["ply"] for i in state["result"]["items"]] == list(range(1, 133))
        assert state["result"]["final_score"] == {"type": "cp", "value": 132}
        assert state["result"]["items"][120]["label"]
        count = len(calls)
        # A fresh client has no browser cache; the server returns the same result.
        restored = begin(client, game).json()
        assert restored == state
        assert len(calls) == count
        assert client.get(f"/api/reviews/{review_id}", headers=OTHER).status_code == 404
        assert client.post(f"/api/reviews/{review_id}/advance", headers=OTHER, json={"start_ply": 0}).status_code == 404
        exported = client.post("/api/me/exports", headers=OWNER).json()
        archive = client.get(exported["download_url"], headers=OWNER)
        with ZipFile(BytesIO(archive.content)) as z:
            reviews = json.loads(z.read("reviews.json"))
        saved = next(r for r in reviews if r["id"] == review_id)
        assert len(saved["items"]) == 132
        assert saved["moves_snapshot"] == MOVES
        assert saved["parameters"]["_segmented"]["final_score"] == {"type": "cp", "value": 132}
        fresh = begin(client, game, reuse=False).json()
        assert fresh["review_id"] != review_id
        assert fresh["status"] == "in_progress"
        assert client.delete(f"/api/games/{game['id']}", headers=OWNER).status_code == 204
        assert client.get(f"/api/reviews/{review_id}", headers=OWNER).status_code in {404, 410}
        assert client.post(f"/api/reviews/{fresh['review_id']}/advance", headers=OWNER, json={"start_ply": 0}).status_code in {404, 410}


def test_failed_segment_is_retryable_and_duplicates_do_not_insert_twice(monkeypatch):
    calls = fake_search(monkeypatch, fail_prefix=30)
    with TestClient(main.app) as client:
        game = imported_game(client)
        state = begin(client, game).json()
        path = f"/api/reviews/{state['review_id']}/advance"
        # First segment includes boundary 30; a failed batch writes no partial items.
        assert client.post(path, headers=OWNER, json={"start_ply": 0}).status_code == 503
        with SessionLocal() as db:
            saved = db.get(Review, state["review_id"])
            assert saved.status == "in_progress"
            assert saved.completed_at is None
            assert db.query(ReviewItem).count() == 0
        fake_search(monkeypatch)
        first = client.post(path, headers=OWNER, json={"start_ply": 0}).json()
        assert first["completed_plies"] == 30
        assert first["result"] is None
        assert client.post(path, headers=OWNER, json={"start_ply": 0}).json() == first
        assert client.post(path, headers=OWNER, json={"start_ply": 60}).status_code == 409
        resumed = begin(client, game).json()
        assert resumed["review_id"] == state["review_id"]
        assert resumed["completed_plies"] == 30
        with SessionLocal() as db:
            assert db.query(ReviewItem).count() == 30
        assert calls


def test_cloud_review_rejects_wrong_snapshot_guest_and_missing_consent(monkeypatch):
    with TestClient(main.app) as client:
        game = imported_game(client)
        assert begin(client, game, moves=MOVES[:-1]).status_code == 409
        assert begin(client, game, moves=MOVES * 4).status_code == 422
        monkeypatch.setenv("AUTH_MODE", "email")
        response = begin(client, game)
        assert response.status_code == 401
        monkeypatch.setenv("EMAIL_VERIFICATION_REQUIRED", "false")
        registration = client.post("/auth/email/register", json={"email": "cloud-review@example.test", "password": "LongReviewPass123!", "accept_privacy": True, "policy_version": main.policy_version()})
        assert registration.status_code == 201, registration.text
        assert client.post("/auth/email/login", json={"email": "cloud-review@example.test", "password": "LongReviewPass123!"}).status_code == 200
        monkeypatch.setenv("PRIVACY_POLICY_VERSION", "new-long-review-policy")
        assert begin(client, game).status_code == 403


@pytest.mark.parametrize("change", ["game_deleted", "account_deleted", "consent_withdrawn"])
def test_changes_during_engine_search_prevent_result_writeback(monkeypatch, change):
    fake_search(monkeypatch)
    with TestClient(main.app) as client:
        game = imported_game(client)
        state = begin(client, game).json()
        original = main.engine.analyze
        changed = False

        async def analyze(*args):
            nonlocal changed
            if not changed:
                changed = True
                with SessionLocal() as db:
                    stored = db.get(Game, game["id"])
                    if change == "game_deleted":
                        stored.deleted_at = datetime.now(timezone.utc)
                        stored.status = "deleted"
                    elif change == "account_deleted":
                        db.get(User, stored.user_id).status = "deletion_pending"
                    else:
                        monkeypatch.setenv("AUTH_MODE", "email")
                        monkeypatch.setattr(main, "has_consent", lambda *_args: False)
                    db.commit()
            return await original(*args)

        monkeypatch.setattr(main.engine, "analyze", analyze)
        response = client.post(f"/api/reviews/{state['review_id']}/advance", headers=OWNER, json={"start_ply": 0})
        assert response.status_code == (403 if change == "consent_withdrawn" else 410), response.text
        with SessionLocal() as db:
            assert db.query(ReviewItem).count() == 0
            assert db.get(Review, state["review_id"]).status == "in_progress"


def test_concurrent_advance_is_rejected_without_duplicate_results(monkeypatch):
    from fastapi import HTTPException
    from app.models import ReviewAdvanceRequest

    fake_search(monkeypatch)
    with TestClient(main.app) as client:
        game = imported_game(client)
        state = begin(client, game).json()
    original = main.engine.analyze

    async def concurrent():
        entered, release = asyncio.Event(), asyncio.Event()

        async def analyze(*args):
            entered.set()
            await release.wait()
            return await original(*args)

        monkeypatch.setattr(main.engine, "analyze", analyze)
        with SessionLocal() as first_db, SessionLocal() as second_db:
            user_id = first_db.get(Review, state["review_id"]).user_id
            task = asyncio.create_task(main.advance_cloud_review(state["review_id"], ReviewAdvanceRequest(start_ply=0), first_db.get(User, user_id), first_db))
            await entered.wait()
            try:
                with pytest.raises(HTTPException) as busy:
                    await main.advance_cloud_review(state["review_id"], ReviewAdvanceRequest(start_ply=0), second_db.get(User, user_id), second_db)
                assert busy.value.detail["code"] == "review_busy"
            finally:
                second_db.rollback()
                release.set()
            assert (await task).completed_plies == 30
    asyncio.run(concurrent())
    with SessionLocal() as db:
        assert db.query(ReviewItem).count() == 30
