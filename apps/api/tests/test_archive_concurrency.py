"""Archive replay must not stall the single worker's live game requests."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest
from fastapi.testclient import TestClient

from app.database import reset_database
from app.main import app
from app.models import EngineLine, EngineResponse
from app.xiangqi import START_FEN


@pytest.mark.parametrize("archive_operation", ["list", "get", "import"])
def test_archive_replay_keeps_health_and_hall_turn_responsive(monkeypatch, archive_operation):
    monkeypatch.setenv("AUTH_MODE", "dev")
    reset_database()

    async def analyze(*_args, **_kwargs):
        return EngineResponse(bestmove="a6a5", lines=[EngineLine(rank=1, move="a6a5", label="卒一进一", score=None, depth=1, pv=["a6a5"])])

    monkeypatch.setattr("app.main.engine.analyze", analyze)
    headers = {"X-Dev-User": "archive-concurrency"}
    entered, release, lock = Event(), Event(), Lock()
    claimed = False
    from app.main import validate_history

    def slow_archive_replay(*args, **kwargs):
        nonlocal claimed
        with lock:
            block = not claimed
            claimed = True
        if block:
            entered.set()
            assert release.wait(5), "archive test was not released"
        return validate_history(*args, **kwargs)

    try:
        with TestClient(app) as client:
            game = client.post("/api/hall/games", headers=headers, json={"opponent_id": "tea-sparrow", "user_side": "red"}).json()
            monkeypatch.setattr("app.main.validate_history", slow_archive_replay)

            def archive_request():
                if archive_operation == "list":
                    return client.get("/api/games", headers=headers)
                if archive_operation == "get":
                    return client.get(f"/api/games/{game['id']}", headers=headers)
                return client.post("/api/games/import", headers=headers, json={"legacy_id": "slow-archive", "initial_fen": START_FEN, "moves": []})

            with ThreadPoolExecutor(max_workers=3) as pool:
                archive = pool.submit(archive_request)
                try:
                    assert entered.wait(2), "archive request did not reach rule replay"
                    health = pool.submit(client.get, "/api/health")
                    turn = pool.submit(client.post, f"/api/games/{game['id']}/turns", headers=headers, json={"turn_id": "archive-concurrent-turn", "expected_version": 0, "user_uci": "a3a4"})
                    health_response = health.result(timeout=1)
                    turn_response = turn.result(timeout=1)
                    assert health_response.status_code == 200
                    assert turn_response.status_code == 200
                    assert len(turn_response.json()["game"]["moves"]) == 2
                    assert not archive.done(), "live requests must finish while archive replay is still running"
                finally:
                    release.set()
                assert archive.result(timeout=3).status_code in {200, 201}
    finally:
        release.set()
        reset_database()


def test_opening_lookup_keeps_health_responsive(monkeypatch):
    entered, release = Event(), Event()

    def slow_opening_lookup(*_args, **_kwargs):
        entered.set()
        assert release.wait(5), "opening lookup was not released"
        return {"matches": []}

    monkeypatch.setattr("app.main.lookup_openings", slow_opening_lookup)

    try:
        with TestClient(app) as client:
            with ThreadPoolExecutor(max_workers=2) as pool:
                opening = pool.submit(client.post, "/api/openings", json={"fen": START_FEN, "moves": []})
                try:
                    assert entered.wait(2), "opening lookup did not start"
                    health = pool.submit(client.get, "/api/health")
                    assert health.result(timeout=1).status_code == 200
                    assert not opening.done(), "opening lookup should still be blocked"
                finally:
                    release.set()
                assert opening.result(timeout=3).status_code == 200
    finally:
        release.set()


def test_event_sync_keeps_health_responsive(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "dev")
    reset_database()
    entered, release = Event(), Event()

    def slow_event_validation(*_args, **_kwargs):
        entered.set()
        assert release.wait(5), "event validation was not released"

    headers = {"X-Dev-User": "event-concurrency"}

    try:
        with TestClient(app) as client:
            game = client.post("/api/games", headers=headers, json={"initial_fen": START_FEN}).json()
            monkeypatch.setattr("app.main._validate_game_events", slow_event_validation)
            with ThreadPoolExecutor(max_workers=2) as pool:
                events = pool.submit(client.patch, f"/api/games/{game['id']}/events", headers=headers, json={"expected_version": 0, "events": []})
                try:
                    assert entered.wait(2), "event validation did not start"
                    health = pool.submit(client.get, "/api/health")
                    assert health.result(timeout=1).status_code == 200
                    assert not events.done(), "event validation should still be blocked"
                finally:
                    release.set()
                assert events.result(timeout=3).status_code == 200
    finally:
        release.set()
        reset_database()
