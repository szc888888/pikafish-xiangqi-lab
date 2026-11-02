import asyncio
import logging

import pytest
from fastapi import HTTPException

from app.engine import EngineUnavailable, PikafishEngine
from app.models import EngineRequest, EngineResponse, PlanAnalysisRequest, ReviewRequest, Score
from app.xiangqi import START_FEN


def test_parse_uci_info_line():
    parsed = {}
    PikafishEngine._parse_info(
        "info depth 18 score cp 42 nodes 123456 nps 789000 pv h2e2 b9c7",
        parsed,
    )
    assert parsed["depth"] == 18
    assert parsed["nodes"] == 123456
    assert parsed["nps"] == 789000
    assert parsed["score"].type == "cp"
    assert parsed["score"].value == 42
    assert parsed["pv"] == ["h2e2", "b9c7"]


def test_engine_metadata_uses_uci_identity_and_nnue_content_hash(tmp_path):
    model = tmp_path / "pikafish.nnue"
    model.write_bytes(b"test model payload")
    assert PikafishEngine._engine_version_from_uci(["id name Pikafish dev-test", "uciok"]) == "Pikafish dev-test"
    assert PikafishEngine._hash_nnue(str(model)) == "sha256:bae77ae8633e61e7906d62148fecbf0f322507fe9b145afb5e3081af6b0e8b88"
    assert PikafishEngine._hash_nnue("") is None


def test_engine_is_safe_when_binary_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("PIKAFISH_PATH", str(tmp_path / "missing.exe"))
    engine = PikafishEngine()
    assert engine.configured is False
    assert engine.ready is False


def test_missing_binary_emits_safe_start_failure(monkeypatch, tmp_path, caplog):
    from app.logging_config import request_id_context

    sentinel_fen = "SENTINEL_FEN_123"
    monkeypatch.setenv("PIKAFISH_PATH", str(tmp_path / "missing.exe"))
    token = request_id_context.set("request-engine-missing")
    try:
        with caplog.at_level(logging.INFO, logger="app.engine"):
            asyncio.run(PikafishEngine().start())
    finally:
        request_id_context.reset(token)

    record = next(record for record in caplog.records if getattr(record, "event", None) == "engine.start_failed")
    assert record.phase == "configuration"
    assert record.exception_type == "FileNotFoundError"
    assert record.path.endswith("missing.exe")
    assert record.request_id == "request-engine-missing"
    assert sentinel_fen not in caplog.text


def test_configured_engine_log_file_contains_bounded_path_fields(monkeypatch, tmp_path):
    from app.logging_config import configure_logging, get_logger

    executable = tmp_path / "pikafish.exe"
    nnue = tmp_path / "weights.nnue"
    monkeypatch.setenv("PIKAFISH_PATH", str(executable))
    monkeypatch.setenv("PIKAFISH_EVAL_FILE", str(nnue))

    app_logger = logging.getLogger("app")
    previous_handlers = list(app_logger.handlers)
    previous_level = app_logger.level
    previous_propagate = app_logger.propagate
    try:
        configure_logging(tmp_path)
        asyncio.run(PikafishEngine().start())
        get_logger("engine").info(
            "bounded path check",
            extra={
                "event": "engine.starting",
                "path": "p" * 600,
                "nnue_path": "n" * 600,
            },
        )
        logged = (tmp_path / "logs" / "api.log").read_text(encoding="utf-8")
        assert f"path={executable}" in logged
        assert f"nnue_path={nnue}" in logged
        assert f"path={'p' * 512}" in logged
        assert f"nnue_path={'n' * 512}" in logged
        assert "p" * 513 not in logged
        assert "n" * 513 not in logged
    finally:
        for handler in list(app_logger.handlers):
            if handler not in previous_handlers and getattr(handler, "_xiangqi_owned_handler", False):
                app_logger.removeHandler(handler)
                handler.close()
        app_logger.setLevel(previous_level)
        app_logger.propagate = previous_propagate


def test_engine_uses_bounded_effective_values_for_uci_and_timeout(monkeypatch):
    engine = PikafishEngine()
    engine.process = type("Process", (), {"returncode": None, "pid": 99})()
    sent = []
    timeouts = []
    lines = iter(["bestmove a6a5"])

    async def no_start():
        pass

    async def record(command):
        sent.append(command)

    async def ready(_token):
        return ["readyok"]

    async def readline(timeout=None):
        timeouts.append(timeout)
        return next(lines)

    monkeypatch.setattr(engine, "start", no_start)
    monkeypatch.setattr(engine, "_send", record)
    monkeypatch.setattr(engine, "_wait_for", ready)
    monkeypatch.setattr(engine, "_readline", readline)

    result = asyncio.run(engine.analyze(
        START_FEN, ["a3a4"], 100, 200_000, 0, 999, 99_999,
    ))

    assert result.bestmove == "a6a5"
    assert "setoption name Threads value 128" in sent
    assert "setoption name Hash value 8192" in sent
    assert "setoption name MultiPV value 1" in sent
    assert "go movetime 120000" in sent
    assert timeouts == [130.0]


class _FakeStdin:
    def write(self, _data):
        pass

    async def drain(self):
        pass


class _FakeStdout:
    def __init__(self, lines):
        self.lines = iter(lines)

    async def readline(self):
        return next(self.lines).encode() + b"\n"


class _FakeProcess:
    def __init__(self, lines):
        self.stdin = _FakeStdin()
        self.stdout = _FakeStdout(lines)
        self.pid = 4312
        self.returncode = None

    def kill(self):
        self.returncode = -9

    async def wait(self):
        return self.returncode


def test_successful_uci_search_logs_lifecycle_without_position_data(monkeypatch, tmp_path, caplog):
    from app.logging_config import request_id_context

    executable = tmp_path / "pikafish.exe"
    executable.write_bytes(b"fake")
    nnue = tmp_path / "weights.nnue"
    nnue.write_bytes(b"fake")
    monkeypatch.setenv("PIKAFISH_PATH", str(executable))
    monkeypatch.setenv("PIKAFISH_EVAL_FILE", str(nnue))
    process = _FakeProcess([
        "id name Pikafish",
        "uciok",
        "readyok",
        "readyok",
        "info depth 5 score cp 12 nodes 100 nps 200 pv a6a5 SENTINEL_PV",
        "bestmove a6a5",
    ])

    async def create_process(*_args, **_kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    token = request_id_context.set("request-engine-search")
    try:
        with caplog.at_level(logging.INFO, logger="app.engine"):
            engine = PikafishEngine()
            result = asyncio.run(engine.analyze(
                START_FEN, ["a3a4"], 5, 123, 1, 2, 256
            ))
    finally:
        request_id_context.reset(token)

    assert result.bestmove == "a6a5"
    events = [getattr(record, "event", None) for record in caplog.records]
    assert "engine.starting" in events
    assert "engine.ready" in events
    assert "engine.search.started" in events
    assert "engine.search.completed" in events
    ready = next(record for record in caplog.records if getattr(record, "event", None) == "engine.ready")
    assert ready.phase == "isready"
    assert ready.pid == 4312
    search = next(record for record in caplog.records if getattr(record, "event", None) == "engine.search.completed")
    assert search.depth == 5
    assert search.movetime_ms == 123
    assert search.multipv == 1
    assert search.threads == 2
    assert search.hash_mb == 256
    assert search.outcome == "success"
    assert search.request_id == "request-engine-search"
    for secret in (START_FEN, "a3a4", "a6a5", "SENTINEL_PV"):
        assert secret not in caplog.text


def test_engine_filters_invalid_multipv_candidates_and_reports_summary(monkeypatch, tmp_path):
    executable = tmp_path / "pikafish.exe"
    executable.write_bytes(b"fake")
    monkeypatch.setenv("PIKAFISH_PATH", str(executable))
    process = _FakeProcess([
        "id name Pikafish",
        "uciok",
        "readyok",
        "readyok",
        "info depth 5 multipv 1 score cp 12 pv h2e2",
        "info depth 5 multipv 2 score cp 4 pv a0a9",
        "bestmove h2e2",
    ])

    async def create_process(*_args, **_kwargs):
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    result = asyncio.run(PikafishEngine().analyze(START_FEN, [], 5, 0, 2, 1, 16))

    assert [line.move for line in result.lines] == ["h2e2"]
    assert result.filter_summary.requested == 2
    assert result.filter_summary.returned == 1
    assert result.filter_summary.rejected[0].move == "a0a9"
    assert result.filter_summary.rejected[0].code == "illegal_move"


def test_engine_chooses_next_candidate_when_bestmove_is_perpetual_check(monkeypatch, tmp_path):
    from app import engine as engine_module
    from app.xiangqi import CandidateValidation, RuleIssue

    executable = tmp_path / "pikafish.exe"
    executable.write_bytes(b"fake")
    monkeypatch.setenv("PIKAFISH_PATH", str(executable))
    process = _FakeProcess([
        "id name Pikafish",
        "uciok",
        "readyok",
        "readyok",
        "info depth 5 multipv 1 score cp 12 pv h2e2",
        "info depth 5 multipv 2 score cp 4 pv a3a4",
        "bestmove h2e2",
    ])

    async def create_process(*_args, **_kwargs):
        return process

    def validate_candidate(position, move, positions=None, moves=None):
        if move == "h2e2":
            return CandidateValidation(
                None,
                RuleIssue("perpetual_check", "黑方连续长将，违反棋规，不能继续", 1, "black"),
            )
        return CandidateValidation(position)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
    monkeypatch.setattr(engine_module, "validate_candidate", validate_candidate)

    result = asyncio.run(PikafishEngine().analyze(START_FEN, [], 5, 0, 2, 1, 16))

    assert result.bestmove == "a3a4"
    assert [line.move for line in result.lines] == ["a3a4"]
    assert result.filter_summary.rejected[0].move == "h2e2"
    assert result.filter_summary.rejected[0].code == "perpetual_check"


def test_search_timeout_emits_safe_failure(monkeypatch, caplog):
    engine = PikafishEngine()
    engine.process = type("Process", (), {"returncode": None, "pid": 99})()

    async def no_start():
        pass

    async def record(_command):
        pass

    async def ready(_token):
        return ["readyok"]

    async def timeout(_timeout=None):
        raise asyncio.TimeoutError("SENTINEL_TIMEOUT_LINE")

    async def fail_stop():
        engine.process = None

    monkeypatch.setattr(engine, "start", no_start)
    monkeypatch.setattr(engine, "_send", record)
    monkeypatch.setattr(engine, "_wait_for", ready)
    monkeypatch.setattr(engine, "_readline", timeout)
    monkeypatch.setattr(engine, "stop", fail_stop)
    with caplog.at_level(logging.INFO, logger="app.engine"):
        with pytest.raises(EngineUnavailable, match="搜索超时"):
            asyncio.run(engine.analyze(START_FEN, ["a3a4"], 5, 1, 1))

    failure = next(record for record in caplog.records if getattr(record, "event", None) == "engine.search.failed")
    assert failure.outcome == "timeout"
    assert failure.exception_type == "TimeoutError"
    assert failure.pid == 99
    assert START_FEN not in caplog.text
    assert "a3a4" not in caplog.text
    assert "SENTINEL_TIMEOUT_LINE" not in caplog.text


def test_engine_sends_threads_and_hash_options(monkeypatch):
    engine = PikafishEngine()
    engine.process = type("Process", (), {"returncode": None})()
    sent = []
    lines = iter(["info depth 5 score cp 12 nodes 100 nps 200 pv a6a5", "bestmove a6a5"])

    async def no_start():
        pass

    async def record(command):
        sent.append(command)

    async def ready(_token):
        return ["readyok"]

    async def readline(_timeout=None):
        return next(lines)

    monkeypatch.setattr(engine, "start", no_start)
    monkeypatch.setattr(engine, "_send", record)
    monkeypatch.setattr(engine, "_wait_for", ready)
    monkeypatch.setattr(engine, "_readline", readline)
    result = asyncio.run(engine.analyze(START_FEN, ["a3a4"], 5, 0, 1, 3, 512))

    assert result.bestmove == "a6a5"
    assert "setoption name Threads value 3" in sent
    assert "setoption name Hash value 512" in sent
    assert "position fen " + START_FEN + " moves a3a4" in sent


def test_engine_rejects_an_illegal_bestmove_without_logging_move(monkeypatch, caplog):
    engine = PikafishEngine()
    engine.process = type("Process", (), {"returncode": None})()
    lines = iter(["bestmove a0a9"])

    async def no_start():
        pass

    async def record(_command):
        pass

    async def ready(_token):
        return ["readyok"]

    async def readline(_timeout=None):
        return next(lines)

    monkeypatch.setattr(engine, "start", no_start)
    monkeypatch.setattr(engine, "_send", record)
    monkeypatch.setattr(engine, "_wait_for", ready)
    monkeypatch.setattr(engine, "_readline", readline)
    with caplog.at_level(logging.INFO, logger="app.engine"):
        with pytest.raises(EngineUnavailable, match="不合法着法"):
            asyncio.run(engine.analyze(START_FEN, [], 5, 0, 1, 1, 16))

    failure = next(record for record in caplog.records if getattr(record, "event", None) == "engine.search.failed")
    assert failure.outcome == "failed"
    assert failure.exception_type == "EngineUnavailable"
    assert "a0a9" not in caplog.text
    assert START_FEN not in caplog.text


def test_engine_returns_terminal_result_when_side_to_move_is_checkmated(monkeypatch):
    engine = PikafishEngine()
    engine.process = type("Process", (), {"returncode": None})()
    lines = iter(["bestmove 0000"])
    fen = "3k1ab2/4a2r1/3Nb4/p1p3n1p/9/2P2p2P/P3P3c/B2C1R3/4A4/3A1K3 b - - 0 1"

    async def no_start():
        pass

    async def record(_command):
        pass

    async def ready(_token):
        return ["readyok"]

    async def readline(_timeout=None):
        return next(lines)

    monkeypatch.setattr(engine, "start", no_start)
    monkeypatch.setattr(engine, "_send", record)
    monkeypatch.setattr(engine, "_wait_for", ready)
    monkeypatch.setattr(engine, "_readline", readline)

    result = asyncio.run(engine.analyze(fen, [], 5, 0, 1, 1, 16))

    assert result.bestmove == "0000"
    assert result.lines == []
    assert result.terminal_status == "checkmate"


def test_engine_request_rejects_out_of_range_settings():
    with pytest.raises(ValueError):
        EngineRequest(fen=START_FEN, depth=65)
    with pytest.raises(ValueError):
        EngineRequest(fen=START_FEN, hash_mb=8193)
    with pytest.raises(ValueError):
        EngineRequest(fen=START_FEN, movetime_ms=120001)


def test_plan_analysis_returns_engine_comparison_when_llm_is_unavailable(monkeypatch):
    import asyncio
    from app import main
    from app.llm import LLMUnavailable

    class FakeEngine:
        async def analyze(self, fen, moves, depth, movetime_ms, multipv, threads, hash_mb):
            score = 30 if not moves else -10
            return EngineResponse(bestmove="h2e2", score=Score(type="cp", value=score), depth=depth, pv=["h2e2"])

    async def unavailable(_payload):
        raise LLMUnavailable("not configured")

    monkeypatch.setattr(main, "engine", FakeEngine())
    monkeypatch.setattr(main, "explain", unavailable)
    response = asyncio.run(main.plan_analysis(PlanAnalysisRequest(fen=START_FEN, idea="控制中路", move="炮二平五")))
    assert response.ai_available is False
    assert response.best.move == "h2e2"
    assert response.proposed.move == "h2e2"
    assert response.score_difference_cp == 20


def test_analyze_rejects_facing_kings_with_stable_error_code(monkeypatch):
    from app import main

    class NeverCalledEngine:
        async def analyze(self, *args, **kwargs):
            raise AssertionError("engine must not run for invalid FEN")

    monkeypatch.setattr(main, "engine", NeverCalledEngine())
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.analyze(EngineRequest(fen="4k4/9/9/9/9/9/9/9/9/4K4 w - - 0 1")))

    assert error.value.status_code == 400
    assert error.value.detail["code"] == "invalid_fen"


def test_plan_analysis_rejects_perpetual_chase_before_engine(monkeypatch):
    from app import main

    class NeverCalledEngine:
        async def analyze(self, *args, **kwargs):
            raise AssertionError("engine must not run for a blocked proposed move")

    monkeypatch.setattr(main, "engine", NeverCalledEngine())
    request = PlanAnalysisRequest(
        fen="4k4/9/9/9/R1r1P4/9/9/9/9/4K4 w - - 0 1",
        moves=["a5b5", "c5c6", "b5b6", "c6c5", "b6b5", "c5c6"],
        idea="反复攻击",
        move="b5b6",
    )

    with pytest.raises(HTTPException) as error:
        asyncio.run(main.plan_analysis(request))

    assert error.value.status_code == 422
    assert error.value.detail["code"] == "rule_violation"


def test_review_reports_invalid_fen_with_stable_error_code():
    from app import main

    with pytest.raises(HTTPException) as error:
        asyncio.run(main.review(ReviewRequest(fen="9/9 w")))

    assert error.value.status_code == 400
    assert error.value.detail["code"] == "invalid_fen"


def test_analyze_reports_thread_limit_as_parameter_error(monkeypatch):
    from app import main

    monkeypatch.setattr(main.os, "cpu_count", lambda: 2)
    with pytest.raises(HTTPException) as error:
        asyncio.run(main.analyze(EngineRequest(fen=START_FEN, threads=3)))

    assert error.value.status_code == 400
    assert error.value.detail["code"] == "invalid_parameter"

