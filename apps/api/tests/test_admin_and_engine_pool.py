import asyncio

import pytest
from fastapi.testclient import TestClient

from app.database import reset_database
from app.engine import EngineQueueFull, PikafishEnginePool
from app.main import app
from app.models import EngineResponse
from app.xiangqi import START_FEN


def test_dev_admin_can_view_dashboard_but_regular_user_cannot(monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "dev")
    reset_database()
    try:
        with TestClient(app) as client:
            admin = {"X-Dev-User": "admin"}
            user = {"X-Dev-User": "ordinary-user"}
            assert client.get("/api/me", headers=admin).json()["role"] == "admin"
            overview = client.get("/api/admin/overview", headers=admin)
            assert overview.status_code == 200
            assert overview.json()["engine"]["max_inflight"] == 6
            assert client.get("/api/admin/users", headers=admin).status_code == 200
            assert client.get("/api/admin/overview", headers=user).status_code == 403
    finally:
        reset_database()


def test_engine_pool_runs_one_search_per_child_and_bounds_total(monkeypatch):
    async def run():
        monkeypatch.setenv("ENGINE_POOL_SIZE", "2")
        pool = PikafishEnginePool()
        entered = asyncio.Event()
        release = asyncio.Event()
        active = 0
        maximum = 0
        child_maximum: list[int] = []

        def fake_for(child_index: int):
            child_active = 0
            child_max = 0
            child_lock = asyncio.Lock()

            async def fake_analyze(*_args, **_kwargs):
                nonlocal active, maximum, child_active, child_max
                async with child_lock:
                    child_active += 1
                    child_max = max(child_max, child_active)
                    child_maximum[child_index] = child_max
                    active += 1
                    maximum = max(maximum, active)
                    entered.set()
                    await release.wait()
                    active -= 1
                    child_active -= 1
                    return EngineResponse(bestmove="a6a5")

            return fake_analyze

        child_maximum.extend([0] * len(pool.engines))
        for index, child in enumerate(pool.engines):
            child.analyze = fake_for(index)
        tasks = [asyncio.create_task(pool.analyze(START_FEN, [], 1, 0, 1)) for _ in range(6)]
        await entered.wait()
        with pytest.raises(EngineQueueFull):
            await pool.analyze(START_FEN, [], 1, 0, 1)
        release.set()
        await asyncio.gather(*tasks)
        assert maximum == 2
        assert child_maximum == [1, 1]
        assert pool.inflight == 0

    asyncio.run(run())
