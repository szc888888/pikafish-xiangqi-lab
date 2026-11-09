import asyncio

import pytest

from app.engine import EngineQueueFull, EngineQueueTimeout, PikafishEngine
from app.models import EngineResponse
from app.xiangqi import START_FEN


def test_engine_admits_at_most_three_requests_and_serializes_searches(monkeypatch):
    async def run():
        engine = PikafishEngine()
        entered = asyncio.Event()
        release = asyncio.Event()
        active = 0
        maximum_active = 0

        async def fake_search(*args, **kwargs):
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            entered.set()
            await release.wait()
            active -= 1
            return EngineResponse(bestmove="a6a5")

        async def fake_start():
            engine.process = type("Process", (), {"returncode": None, "pid": 1})()

        monkeypatch.setattr(engine, "_search", fake_search)
        monkeypatch.setattr(engine, "start", fake_start)
        requests = [asyncio.create_task(engine.analyze(START_FEN, [], 1, 0, 1)) for _ in range(3)]
        await entered.wait()
        await asyncio.sleep(0)
        with pytest.raises(EngineQueueFull):
            await engine.analyze(START_FEN, [], 1, 0, 1)
        release.set()
        await asyncio.gather(*requests)
        assert maximum_active == 1

    asyncio.run(run())


def test_reset_waits_for_in_flight_search(monkeypatch):
    async def run():
        engine = PikafishEngine()
        entered = asyncio.Event()
        release = asyncio.Event()
        reset_finished = asyncio.Event()

        async def fake_search(*args, **kwargs):
            entered.set()
            await release.wait()
            return EngineResponse(bestmove="a6a5")

        async def fake_start():
            engine.process = type("Process", (), {"returncode": None, "pid": 1})()

        async def fake_stop():
            engine.process = None

        monkeypatch.setattr(engine, "_search", fake_search)
        monkeypatch.setattr(engine, "start", fake_start)
        monkeypatch.setattr(engine, "stop", fake_stop)
        search = asyncio.create_task(engine.analyze(START_FEN, [], 1, 0, 1))
        await entered.wait()

        async def reset():
            await engine.reset()
            reset_finished.set()

        reset_task = asyncio.create_task(reset())
        await asyncio.sleep(0)
        assert not reset_finished.is_set()
        release.set()
        await asyncio.gather(search, reset_task)
        assert reset_finished.is_set()

    asyncio.run(run())


def test_cancelled_search_drains_uci_before_releasing_lock(monkeypatch):
    async def run():
        engine = PikafishEngine()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def fake_search(*args, **kwargs):
            entered.set()
            await release.wait()
            return EngineResponse(bestmove="a6a5")

        async def fake_start():
            engine.process = type("Process", (), {"returncode": None, "pid": 1})()

        sent: list[str] = []

        async def fake_send(command):
            sent.append(command)

        async def fake_wait_for(token):
            assert token == "bestmove"
            return ["bestmove 0000"]

        monkeypatch.setattr(engine, "_search", fake_search)
        monkeypatch.setattr(engine, "start", fake_start)
        monkeypatch.setattr(engine, "_send", fake_send)
        monkeypatch.setattr(engine, "_wait_for", fake_wait_for)
        task = asyncio.create_task(engine.analyze(START_FEN, [], 1, 0, 1))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert sent == ["stop"]
        assert engine._inflight == 0

    asyncio.run(run())


def test_waiting_request_expires_after_queue_timeout(monkeypatch):
    async def run():
        engine = PikafishEngine()
        engine.queue_wait_timeout_seconds = 0.01
        entered = asyncio.Event()
        release = asyncio.Event()

        async def fake_search(*args, **kwargs):
            entered.set()
            await release.wait()
            return EngineResponse(bestmove="a6a5")

        async def fake_start():
            engine.process = type("Process", (), {"returncode": None, "pid": 1})()

        monkeypatch.setattr(engine, "_search", fake_search)
        monkeypatch.setattr(engine, "start", fake_start)
        first = asyncio.create_task(engine.analyze(START_FEN, [], 1, 0, 1))
        await entered.wait()
        waiting = asyncio.create_task(engine.analyze(START_FEN, [], 1, 0, 1))
        with pytest.raises(EngineQueueTimeout):
            await asyncio.wait_for(waiting, 0.5)
        release.set()
        await first

    asyncio.run(run())
