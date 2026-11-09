import os

import pytest
from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///./test_game_hall.db"
os.environ["AUTH_MODE"] = "dev"

from app.engine import EngineQueueFull, EngineUnavailable  # noqa: E402
from app.main import app  # noqa: E402
from app.database import reset_database  # noqa: E402
from app.models import EngineLine, EngineResponse  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    os.environ["AUTH_MODE"] = "dev"
    reset_database()
    yield
    reset_database()


def _engine_response():
    return EngineResponse(bestmove="a6a5", lines=[EngineLine(rank=1, move="a6a5", label="卒一进一", score=None, depth=1, pv=["a6a5"])])


def test_hall_turn_saves_user_and_legal_ai_move_and_is_idempotent(monkeypatch):
    async def analyze(*_args, **_kwargs):
        return _engine_response()

    monkeypatch.setattr("app.main.engine.analyze", analyze)
    with TestClient(app) as client:
        headers = {"X-Dev-User": "hall-user"}
        created = client.post("/api/hall/games", headers=headers, json={"opponent_id": "north-star", "user_side": "red"})
        assert created.status_code == 201
        game = created.json()
        assert game["counts_for_stats"] is False
        payload = {"turn_id": "turn-123456", "expected_version": 0, "user_uci": "a3a4"}
        response = client.post(f"/api/games/{game['id']}/turns", headers=headers, json=payload)
        assert response.status_code == 200
        assert response.json()["turn_status"] == "completed"
        assert len(response.json()["game"]["moves"]) == 2
        duplicate = client.post(f"/api/games/{game['id']}/turns", headers=headers, json=payload)
        assert duplicate.status_code == 200
        assert duplicate.json()["game"]["version"] == 2
        assert len(duplicate.json()["game"]["moves"]) == 2


def test_engine_failure_keeps_awaiting_ai_and_same_turn_can_retry(monkeypatch):
    calls = 0

    async def analyze(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise EngineUnavailable("offline")
        return _engine_response()

    monkeypatch.setattr("app.main.engine.analyze", analyze)
    with TestClient(app) as client:
        headers = {"X-Dev-User": "hall-retry"}
        game = client.post("/api/hall/games", headers=headers, json={"opponent_id": "north-star", "user_side": "red"}).json()
        payload = {"turn_id": "turn-retry-1", "expected_version": 0, "user_uci": "a3a4"}
        failed = client.post(f"/api/games/{game['id']}/turns", headers=headers, json=payload)
        assert failed.status_code == 503
        current = client.get(f"/api/games/{game['id']}", headers=headers).json()
        assert current["status"] == "awaiting_ai"
        assert len(current["moves"]) == 1
        retried = client.post(f"/api/games/{game['id']}/turns", headers=headers, json=payload)
        assert retried.status_code == 200
        assert len(retried.json()["game"]["moves"]) == 2


def test_full_engine_queue_returns_429_and_keeps_turn_recoverable(monkeypatch):
    async def analyze(*_args, **_kwargs):
        raise EngineQueueFull("full")

    monkeypatch.setattr("app.main.engine.analyze", analyze)
    with TestClient(app) as client:
        headers = {"X-Dev-User": "hall-queue-full"}
        game = client.post("/api/hall/games", headers=headers, json={"opponent_id": "north-star", "user_side": "red"}).json()
        failed = client.post(f"/api/games/{game['id']}/turns", headers=headers, json={"turn_id": "queue-full-turn", "expected_version": 0, "user_uci": "a3a4"})
        assert failed.status_code == 429
        assert failed.json()["detail"]["code"] == "engine_queue_full"
        current = client.get(f"/api/games/{game['id']}", headers=headers).json()
        assert current["status"] == "awaiting_ai"
        assert len(current["moves"]) == 1


def test_resign_is_a_formal_result_and_counts_for_stats():
    with TestClient(app) as client:
        headers = {"X-Dev-User": "hall-resign"}
        game = client.post("/api/hall/games", headers=headers, json={"opponent_id": "north-star", "user_side": "red"}).json()
        resigned = client.post(f"/api/games/{game['id']}/resign", headers=headers, json={"request_id": "resign-1234", "expected_version": 0})
        assert resigned.status_code == 200
        assert resigned.json()["termination_reason"] == "resignation"
        stats = client.get("/api/me/game-stats", headers=headers)
        assert stats.status_code == 200
        assert stats.json()["losses"] == 1


def test_imported_guest_game_never_counts_for_stats():
    with TestClient(app) as client:
        headers = {"X-Dev-User": "guest-import"}
        imported = client.post("/api/games/import", headers=headers, json={"legacy_id": "guest-1", "initial_fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1", "moves": []})
        assert imported.status_code == 201
        body = imported.json()
        assert body["origin"] == "guest_import"
        assert body["counts_for_stats"] is False


def test_imported_ai_friend_snapshot_is_preserved_but_never_scored():
    with TestClient(app) as client:
        headers = {"X-Dev-User": "guest-hall-import"}
        friend = client.get("/api/ai-friends").json()["friends"][0]
        imported = client.post("/api/games/import", headers=headers, json={
            "legacy_id": "guest-hall-1",
            "initial_fen": "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1",
            "moves": [],
            "mode": "ai_hall",
            "user_side": "red",
            "opponent_id": friend["bot_id"],
            "opponent_snapshot": friend,
        })
        assert imported.status_code == 201
        body = imported.json()
        assert body["mode"] == "ai_hall"
        assert body["opponent_snapshot"]["bot_id"] == friend["bot_id"]
        assert body["origin"] == "guest_import"
        assert body["counts_for_stats"] is False


def test_catalog_experience_filter_and_match_status_contract():
    with TestClient(app) as client:
        filtered = client.get("/api/ai-friends?experience=casual")
        assert filtered.status_code == 200
        assert filtered.json()["friends"]
        assert all("casual" in friend["experiences"] for friend in filtered.json()["friends"])
        assert client.get("/api/ai-friends?experience=invalid").status_code == 400
        assert client.post("/api/matches/recommend", json={"experience": "practice"}).status_code == 201
        assert client.post("/api/matches/random", json={}).status_code == 201
