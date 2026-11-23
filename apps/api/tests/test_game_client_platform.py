import json
from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.client_platform import client_platform
from app.database import reset_database
from app.main import app
from app.xiangqi import START_FEN


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("AUTH_MODE", "dev")
    monkeypatch.setenv("EXPORT_ROOT", str(tmp_path))
    reset_database()
    with TestClient(app) as instance:
        yield instance
    reset_database()


@pytest.mark.parametrize("headers,expected", [
    ({"X-Client-Platform": "pc"}, "pc"),
    ({"X-Client-Platform": "mini_program"}, "mini_program"),
    ({"X-Client-Platform": " mobile_web "}, "mobile_web"),
    ({"X-Client-Platform": "invalid", "User-Agent": "Windows NT"}, "unknown"),
    ({"X-Client-Platform": "unknown", "User-Agent": "Windows NT"}, "unknown"),
    ({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, "pc"),
    ({"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}, "pc"),
    ({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"}, "pc"),
    ({"User-Agent": "iPhone MicroMessenger miniProgram"}, "mini_program"),
    ({"User-Agent": "iPhone MicroMessenger"}, "mobile_web"),
    ({"User-Agent": "Android"}, "mobile_web"),
    ({"User-Agent": "testclient"}, "unknown"),
    ({}, "unknown"),
])
def test_source_detection(headers, expected):
    request = Request({"type": "http", "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()]})
    assert client_platform(request) == expected


@pytest.mark.parametrize("endpoint,payload", [
    ("/api/games", {"initial_fen": START_FEN}),
    ("/api/hall/games", {"opponent_id": "north-star", "user_side": "red"}),
])
def test_creation_records_source_and_cross_device_access_does_not_replace_it(client, endpoint, payload):
    headers = {"X-Dev-User": "player", "X-Client-Platform": "mini_program"}
    response = client.post(endpoint, headers=headers, json=payload)
    assert response.status_code == 201
    game = response.json()
    assert game["client_platform"] == "mini_program"
    pc = {**headers, "X-Client-Platform": "pc"}
    fetched = client.get(f"/api/games/{game['id']}", headers=pc)
    assert fetched.json()["client_platform"] == "mini_program"
    assert client.get("/api/games", headers=pc).json()[0]["client_platform"] == "mini_program"
    changed = client.patch(f"/api/games/{game['id']}", headers=pc, json={"expected_version": 0, "name": "跨端续下"})
    assert changed.status_code == 200
    assert changed.json()["client_platform"] == "mini_program"
    assert client.get(f"/api/games/{game['id']}", headers={"X-Dev-User": "other"}).status_code == 404


@pytest.mark.parametrize("source,expected", [(None, "unknown"), ("mini_program", "mini_program"), ("pc", "pc")])
def test_import_preserves_original_source_not_upload_device_and_is_idempotent(client, source, expected):
    headers = {"X-Dev-User": "importer", "X-Client-Platform": "pc"}
    payload = {"legacy_id": "old-game", "initial_fen": START_FEN, "moves": ["a3a4"]}
    if source is not None:
        payload["client_platform"] = source
    result = client.post("/api/games/import", headers=headers, json=payload)
    assert result.status_code == 201
    game = result.json()
    assert game["client_platform"] == expected
    assert game["origin"] == "guest_import"
    assert game["counts_for_stats"] is False
    assert game["moves"][0]["uci"] == "a3a4"
    retry = client.post("/api/games/import", headers=headers, json={**payload, "client_platform": "mobile_web"})
    assert retry.status_code == 200
    assert retry.json()["client_platform"] == expected
    assert retry.json()["id"] == game["id"]


def test_invalid_import_source_is_rejected_without_creating_game(client):
    headers = {"X-Dev-User": "importer"}
    result = client.post("/api/games/import", headers=headers, json={
        "legacy_id": "invalid", "initial_fen": START_FEN, "client_platform": "arbitrary",
    })
    assert result.status_code == 422
    assert client.get("/api/games", headers=headers).json() == []


def test_admin_aggregates_per_game_sources_and_export_retains_them(client):
    for source in ("pc", "mini_program", "mini_program", "unknown"):
        assert client.post("/api/games", headers={"X-Dev-User": "player", "X-Client-Platform": source}, json={"initial_fen": START_FEN}).status_code == 201
    assert client.get("/api/admin/users", headers={"X-Dev-User": "player"}).status_code == 403
    rows = client.get("/api/admin/users", headers={"X-Dev-User": "admin"}).json()["users"]
    player = next(row for row in rows if row["display_name"] == "player")
    assert player["game_platforms"] == [
        {"platform": "pc", "games": 1}, {"platform": "mini_program", "games": 2}, {"platform": "unknown", "games": 1},
    ]
    assert player["games_total"] == 4
    exported = client.post("/api/me/exports", headers={"X-Dev-User": "player"})
    assert exported.status_code == 202
    archive = client.get(exported.json()["download_url"], headers={"X-Dev-User": "player"})
    with ZipFile(BytesIO(archive.content)) as zipped:
        games = json.loads(zipped.read("games.json"))
    assert sorted(game["client_platform"] for game in games) == ["mini_program", "mini_program", "pc", "unknown"]
