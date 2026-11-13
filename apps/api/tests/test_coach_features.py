import asyncio
import json
import ssl
import logging
from pathlib import Path
from io import BytesIO
from urllib.error import URLError
from urllib.error import HTTPError

import certifi
import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from app.engine import PikafishEngine
from app.llm import LLMUnavailable, VisionRecognitionError, _request_vision, coach_chat
from app.models import CoachRequest, EngineResponse, PlanAnalysisRequest, Score
from app.openings import lookup_openings
from app.review import classify_loss, review_game
from app.vision import parse_vision_position
from app.main import coach, health, setup_image
from app.xiangqi import START_FEN


def test_logging_configuration_is_rotating_and_idempotent(tmp_path):
    from app.logging_config import configure_logging, get_logger
    logger = logging.getLogger("app")
    owned = [h for h in logger.handlers if getattr(h, "_xiangqi_owned_handler", False)]
    for handler in owned:
        logger.removeHandler(handler)
        handler.close()
    try:
        configure_logging(tmp_path)
        configure_logging(tmp_path)
        owned = [h for h in logger.handlers if getattr(h, "_xiangqi_owned_handler", False)]
        files = [h for h in owned if hasattr(h, "maxBytes")]
        assert len(owned) == 2
        assert len(files) == 1
        assert files[0].maxBytes == 5 * 1024 * 1024
        assert files[0].backupCount == 3
        get_logger("logging_test").info("configured", extra={"event": "configured"})
        text = (Path(tmp_path) / "logs" / "api.log").read_text(encoding="utf-8")
        assert "configured" in text and "request_id=" in text
    finally:
        for handler in list(logger.handlers):
            if getattr(handler, "_xiangqi_owned_handler", False):
                logger.removeHandler(handler)
                handler.close()


def test_logging_structured_allowlist_writes_safe_api_and_engine_fields(tmp_path):
    from app.logging_config import configure_logging, get_logger
    logger = logging.getLogger("app")
    configure_logging(tmp_path)
    try:
        get_logger("llm").warning(
            "ignored message %s", "prompt-message-sentinel",
            extra={
                "event": "llm.request.failed", "operation": "coach_chat",
                "model": "safe-model", "provider_host": "api.example.test",
                "error_class": "TimeoutError", "error_category": "timeout",
                "prompt": "prompt-extra-sentinel", "fen": "fen-extra-sentinel",
                "authorization": "credential-sentinel",
                "url": "https://user:password@example.test/private",
                "moves": ["a0a1"], "pv": ["b0b1"],
            },
        )
        get_logger("engine").info(
            "ignored engine message",
            extra={
                "event": "engine.search.started", "phase": "search", "pid": 4321,
                "outcome": "started", "depth": 12, "movetime_ms": 2500,
                "multipv": 3, "threads": 2, "hash_mb": 64,
                "fen": "engine-fen-sentinel", "command": "position fen secret",
            },
        )
        get_logger("logging_test").warning("missing-event-message-sentinel")
        get_logger("logging_test").warning(
            "safe message ignored", extra={
                "event": "malicious-event-sentinel prompt=event-payload-sentinel",
            },
        )
        logged = (Path(tmp_path) / "logs" / "api.log").read_text(encoding="utf-8")
        for expected in (
            "operation=coach_chat", "model=safe-model", "provider_host=api.example.test",
            "error_class=TimeoutError", "error_category=timeout", "phase=search",
            "pid=4321", "depth=12", "movetime_ms=2500", "multipv=3",
            "threads=2", "hash_mb=64",
            "event=llm.request.failed", "event=engine.search.started",
            "event=application.event",
        ):
            assert expected in logged
        for forbidden in (
            "prompt-message-sentinel", "prompt-extra-sentinel", "fen-extra-sentinel",
            "credential-sentinel", "password", "engine-fen-sentinel", "position fen",
            "missing-event-message-sentinel", "malicious-event-sentinel",
            "event-payload-sentinel",
        ):
            assert forbidden not in logged
    finally:
        for handler in list(logger.handlers):
            if getattr(handler, "_xiangqi_owned_handler", False):
                logger.removeHandler(handler)
                handler.close()


@pytest.mark.parametrize("stack_depth", [0, 80])
def test_logging_request_id_correlation_and_exception_response(tmp_path, stack_depth):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.logging_config import configure_logging
    configure_logging(tmp_path)
    prompt_sentinel = "private-prompt-sentinel"
    fen_sentinel = "private-fen-sentinel"

    def _logging_failure_origin():
        raise RuntimeError(f"{prompt_sentinel} {fen_sentinel}")

    def _logging_wrapper(remaining):
        if remaining:
            return _logging_wrapper(remaining - 1)
        return _logging_failure_origin()

    @app.get("/__logging_failure")
    async def _logging_failure():
        return _logging_wrapper(stack_depth)

    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/api/health", headers={"X-Request-ID": "valid_id-1"})
            assert response.headers["X-Request-ID"] == "valid_id-1"
            generated = client.get("/api/health", headers={"X-Request-ID": "bad id"})
            assert generated.headers["X-Request-ID"] != "bad id"
            assert len(generated.headers["X-Request-ID"]) == 36
            failed = client.get("/__logging_failure", headers={"X-Request-ID": "failure-1"})
            assert failed.status_code == 500
            assert failed.headers["X-Request-ID"] == "failure-1"
        logged = (Path(tmp_path) / "logs" / "api.log").read_text(encoding="utf-8")
        assert "request_failed" in logged
        assert "/__logging_failure" in logged
        assert "RuntimeError" in logged
        assert "stack_locations=" in logged
        assert "test_coach_features.py" in logged
        failed_line = next(line for line in logged.splitlines() if "event=request_failed " in line)
        stack = failed_line.split("stack_locations=", 1)[1].split(" operation=", 1)[0]
        assert stack.split("|", 1)[0].endswith(":_logging_failure_origin")
        assert len(stack) <= 1200
        assert str(Path(__file__).resolve().parents[3]) not in stack
        assert prompt_sentinel not in logged
        assert fen_sentinel not in logged
    finally:
        # This is the shared FastAPI app; do not leave the temporary route in
        # place for the next parametrized case or later tests.
        app.router.routes[:] = [route for route in app.router.routes if getattr(route, "endpoint", None) is not _logging_failure]
        app_logger = logging.getLogger("app")
        for handler in list(app_logger.handlers):
            if getattr(handler, "_xiangqi_owned_handler", False):
                app_logger.removeHandler(handler)
                handler.close()


def test_llm_tls_context_uses_certifi_bundle():
    from app.llm import _tls_context

    context = _tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.get_ca_certs()
    assert certifi.where().endswith("cacert.pem")


def test_vision_timeout_has_a_separate_longer_default(monkeypatch):
    from app.llm import _timeout_seconds

    monkeypatch.delenv("AGENT_OPENAI_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("AGENT_OPENAI_VISION_TIMEOUT_SECONDS", raising=False)

    assert _timeout_seconds("chat") == 60
    assert _timeout_seconds("explain") == 120
    assert _timeout_seconds("vision") == 180


def test_health_reports_model_configuration_without_exposing_credentials(monkeypatch):
    monkeypatch.setenv("AGENT_OPENAI_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("AGENT_OPENAI_API_KEY", "secret-test-key")
    monkeypatch.setenv("AGENT_OPENAI_MODEL", "test-model")

    result = asyncio.run(health())

    assert result["api_ready"] is True
    assert result["llm_configured"] is True
    assert result["llm_model"] == "test-model"
    assert "api_key" not in result
    assert "secret-test-key" not in str(result)


def test_health_reports_model_unconfigured(monkeypatch):
    monkeypatch.delenv("AGENT_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("AGENT_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_OPENAI_MODEL", raising=False)

    result = asyncio.run(health())

    assert result["api_ready"] is True
    assert result["llm_configured"] is False
    assert result["llm_model"] is None


def test_vision_timeout_override_is_bounded(monkeypatch):
    from app.llm import _timeout_seconds

    monkeypatch.setenv("AGENT_OPENAI_VISION_TIMEOUT_SECONDS", "700")
    assert _timeout_seconds("vision") == 600


def test_chat_request_sets_gateway_compatible_user_agent(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "收到"}}]}).encode()

    captured = {}

    def fake_urlopen(request, **kwargs):
        captured["user_agent"] = request.get_header("User-agent")
        return FakeResponse()

    monkeypatch.setenv("AGENT_OPENAI_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("AGENT_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_OPENAI_MODEL", "test-model")
    monkeypatch.setattr("app.llm.urlopen", fake_urlopen)

    from app.llm import _request_chat

    answer = _request_chat({"question": "你好", "fen": START_FEN, "moves": [], "context": "", "messages": []})

    assert answer == "收到"
    assert captured["user_agent"] == "xiangqi-coach/1.0"


def test_chat_prompt_requires_standard_chinese_notation(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "炮二平五"}}]}).encode()

    captured = {}

    def fake_urlopen(request, **kwargs):
        captured["body"] = json.loads(request.data)
        return FakeResponse()

    monkeypatch.setenv("AGENT_OPENAI_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("AGENT_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_OPENAI_MODEL", "test-model")
    monkeypatch.setattr("app.llm.urlopen", fake_urlopen)

    from app.llm import _request_chat

    current_position = {"board": ["........."] * 10, "side_to_move": "red"}
    assert _request_chat({"question": "下一步如何走？", "fen": START_FEN, "moves": [], "context": "",
                          "current_position": current_position, "messages": []}) == "炮二平五"
    system = captured["body"]["messages"][0]["content"]
    assert "中国象棋常用记谱" in system
    assert "禁止使用坐标记法" in system
    assert "炮二平五" in system
    assert "fen 是本局起始局面" in system
    assert "current_position 是后端按同一规则模块重建的权威当前棋盘" in system
    assert "分析当前局面时优先依据 current_position" in system
    assert "不得仅因 fen 显示初始局面就断言与 moves 不一致" in system
    user_payload = json.loads(captured["body"]["messages"][-1]["content"])
    assert user_payload["current_position"] == current_position


def test_chat_response_normalizes_coordinate_notation(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "推荐 H2-E2（h2e2）。"}}]}).encode()

    monkeypatch.setenv("AGENT_OPENAI_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("AGENT_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_OPENAI_MODEL", "test-model")
    monkeypatch.setattr("app.llm.urlopen", lambda *args, **kwargs: FakeResponse())

    from app.llm import _request_chat

    answer = _request_chat({"question": "下一步如何走？", "fen": START_FEN, "moves": [], "context": "", "messages": []})

    assert answer == "推荐 炮二平五。"


def test_multipv_parser_keeps_rank_and_depth_separate():
    parsed = {"lines_by_depth": {}}
    PikafishEngine._parse_info("info depth 9 multipv 1 score cp 32 pv h2e2 b9c7", parsed)
    PikafishEngine._parse_info("info depth 9 multipv 2 score cp 21 pv b2e2 h9g7", parsed)
    PikafishEngine._parse_info("info depth 10 multipv 1 score cp 40 pv h2e2 b9c7", parsed)
    assert set(parsed["lines_by_depth"][9]) == {1, 2}
    assert set(parsed["lines_by_depth"][10]) == {1}
    assert set(PikafishEngine._final_lines(parsed["lines_by_depth"], 2)) == {1, 2}
    assert set(PikafishEngine._final_lines(parsed["lines_by_depth"], 3)) == {1}


def test_review_grade_thresholds_and_mate_loss():
    before = Score(type="cp", value=100)
    assert classify_loss(before, Score(type="cp", value=71)) == ("good", 29)
    assert classify_loss(before, Score(type="cp", value=30)) == ("inaccuracy", 70)
    assert classify_loss(before, Score(type="cp", value=20)) == ("mistake", 80)
    assert classify_loss(before, Score(type="cp", value=-100)) == ("blunder", 200)
    assert classify_loss(before, Score(type="mate", value=3)) == ("good", None)
    assert classify_loss(before, Score(type="mate", value=-3)) == ("blunder", None)


def test_opening_library_matches_prefix_and_reports_deviation():
    first = lookup_openings(START_FEN, ["h2e2"])
    assert any(item.name == "中炮对屏风马" for item in first.matches)
    assert first.matches[0].next_moves
    assert lookup_openings(START_FEN, ["a3a4"]).matches == []
    with pytest.raises(ValueError, match="第 1 步无效"):
        lookup_openings(START_FEN, ["a0a9"])
    assert lookup_openings("4k4/9/9/9/9/9/9/9/9/4K4 w - - 0 1", []).matches == []


def test_review_uses_one_engine_analysis_per_position_and_rejects_bad_move():
    class FakeEngine:
        def __init__(self):
            self.calls = []

        async def analyze(self, fen, moves, depth, movetime, multipv, threads, hash_mb):
            self.calls.append(list(moves))
            score = 50 if len(moves) == 0 else (-40 if len(moves) == 1 else 20)
            return EngineResponse(bestmove="a3a4" if len(moves) == 0 else "a6a5", score=Score(type="cp", value=score), depth=depth, pv=["a3a4"])

    engine = FakeEngine()
    result = asyncio.run(review_game(engine, START_FEN, ["a3a4", "a6a5"], 8, 250, 1, 128))
    assert len(engine.calls) == 3
    assert result.analyzed_plies == 2
    assert [item.ply for item in result.items] == [1, 2]
    with pytest.raises(ValueError, match="第 1 步无效"):
        asyncio.run(review_game(engine, START_FEN, ["a0a9"], 8, 250, 1, 128))


def test_review_stops_before_first_perpetual_chase_and_preserves_prefix():
    fen = "4k4/9/9/9/R1r1P4/9/9/9/9/4K4 w - - 0 1"
    moves = ["a5b5", "c5c6", "b5b6", "c6c5", "b6b5", "c5c6", "b5b6"]

    class FakeEngine:
        def __init__(self):
            self.calls = []

        async def analyze(self, fen, moves, depth, movetime, multipv, threads, hash_mb):
            self.calls.append(list(moves))
            return EngineResponse(bestmove="a5b5", score=Score(type="cp", value=10), depth=depth, pv=[])

    engine = FakeEngine()
    result = asyncio.run(review_game(engine, fen, moves, 8, 250, 1, 128))

    assert result.status == "stopped_rule_violation"
    assert result.stop is not None
    assert result.stop.ply == 7
    assert result.stop.kind == "perpetual_chase"
    assert result.analyzed_plies == 6
    assert len(result.items) == 6
    assert len(engine.calls) == 7


def test_plan_analysis_exposes_score_perspective_and_comparison_status(monkeypatch):
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

    assert response.perspective == "red"
    assert response.comparison_status == "cp"
    assert response.score_difference_cp == 20


def test_coach_chat_bounds_history_and_keeps_board_context(monkeypatch):
    captured = {}

    def fake_request(payload):
        captured.update(payload)
        return "已收到棋局上下文"

    monkeypatch.setattr("app.llm._request_chat", fake_request)
    request = CoachRequest(
        question="为什么这步不好？", fen=START_FEN, moves=["a3a4"],
        messages=[{"role": "user", "content": f"旧消息{i}"} for i in range(15)],
        context="复盘严重失误",
    )
    answer = asyncio.run(coach_chat(request))
    assert answer == "已收到棋局上下文"
    assert captured["fen"] == START_FEN
    assert captured["moves"] == ["a3a4"]
    assert captured["current_position"]["board"][5][0] == "P"
    assert captured["current_position"]["board"][6][0] == "."
    assert captured["current_position"]["side_to_move"] == "black"
    assert captured["context"] == "复盘严重失误"
    assert len(captured["messages"]) <= 20
    assert captured["messages"][-1]["content"] == "旧消息14"


def test_coach_rejects_invalid_fen_with_bad_request():
    request = CoachRequest(question="你好", fen="9/9 w", moves=[])

    with pytest.raises(HTTPException) as error:
        asyncio.run(coach(request))

    assert error.value.status_code == 400
    assert "FEN 无效" in str(error.value.detail)


def test_parse_vision_position_builds_fen_from_a_10_by_9_board():
    result = parse_vision_position({
        "board": [
            "r3k4", "9", "9", "9", "9", "9", "9", "9", "9", "R3K4",
        ],
        "red_to_move": True,
    })
    assert result.fen == "r3k4/9/9/9/9/9/9/9/9/R3K4 w - - 0 1"
    assert result.piece_count == 4
    assert result.red_to_move is True


def test_parse_vision_position_rejects_invalid_shape_and_missing_kings():
    with pytest.raises(ValueError, match="10 行"):
        parse_vision_position({"board": ["9"] * 9, "red_to_move": True})
    with pytest.raises(ValueError, match="红方帅"):
        parse_vision_position({
            "board": ["4k4"] + ["9"] * 9,
            "red_to_move": True,
        })


def test_parse_vision_position_rejects_unknown_piece():
    with pytest.raises(ValueError, match="未知棋子"):
        parse_vision_position({
            "board": ["r3k4"] + ["9"] * 8 + ["R3KX4"],
            "red_to_move": "red",
        })


def test_setup_image_rejects_non_image_content_type():
    upload = UploadFile(filename="board.txt", file=BytesIO(b"not image"), headers={"content-type": "text/plain"})
    with pytest.raises(HTTPException) as error:
        asyncio.run(setup_image(upload))
    assert error.value.status_code == 400


def test_setup_image_rejects_content_that_does_not_match_image_type():
    upload = UploadFile(filename="board.png", file=BytesIO(b"not really a png"), headers={"content-type": "image/png"})
    with pytest.raises(HTTPException) as error:
        asyncio.run(setup_image(upload))
    assert error.value.status_code == 400


def test_setup_image_returns_validated_recognition(monkeypatch):
    from app.vision import VisionPosition

    async def fake_recognize(image, mime_type):
        assert image == b"\x89PNG\r\n\x1a\nimage-bytes"
        assert mime_type == "image/png"
        return VisionPosition("r3k4/9/9/9/9/9/9/9/9/R3K4 w - - 0 1", True, 4, ["棋子位置可能有误"])

    monkeypatch.setattr("app.main.recognize_board_image", fake_recognize)
    upload = UploadFile(filename="board.png", file=BytesIO(b"\x89PNG\r\n\x1a\nimage-bytes"), headers={"content-type": "image/png"})
    result = asyncio.run(setup_image(upload))
    assert result.fen.endswith(" w - - 0 1")
    assert result.piece_count == 4
    assert result.warnings == ["棋子位置可能有误"]


def test_setup_image_maps_unavailable_model_to_503(monkeypatch):
    from app.llm import LLMUnavailable

    async def fail_recognition(image, mime_type):
        raise LLMUnavailable("棋盘图片识别暂时不可用")

    monkeypatch.setattr("app.main.recognize_board_image", fail_recognition)
    upload = UploadFile(filename="board.png", file=BytesIO(b"\x89PNG\r\n\x1a\nimage-bytes"), headers={"content-type": "image/png"})
    with pytest.raises(HTTPException) as error:
        asyncio.run(setup_image(upload))
    assert error.value.status_code == 503


def test_vision_reports_tls_certificate_failure_actionably(monkeypatch):
    monkeypatch.setenv("AGENT_OPENAI_BASE_URL", "https://vision.example/v1")
    monkeypatch.setenv("AGENT_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_OPENAI_MODEL", "vision-model")
    monkeypatch.setattr(
        "app.llm.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(URLError(ssl.SSLCertVerificationError("expired"))),
    )

    with pytest.raises(LLMUnavailable, match="TLS 证书"):
        _request_vision(b"image", "image/png")


def test_coach_reports_upstream_gateway_status_without_exposing_response(monkeypatch):
    from app.llm import _request_chat

    monkeypatch.setenv("AGENT_OPENAI_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("AGENT_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_OPENAI_MODEL", "test-model")
    monkeypatch.setattr(
        "app.llm.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            HTTPError("https://chat.example/v1/chat/completions", 502, "Bad Gateway", {}, BytesIO(b"private upstream details"))
        ),
    )

    with pytest.raises(LLMUnavailable, match="HTTP 502") as error:
        _request_chat({"question": "你好", "fen": START_FEN, "moves": [], "context": "", "messages": []})

    assert "private upstream details" not in str(error.value)


def test_vision_retries_after_invalid_board_and_accepts_corrected_result(monkeypatch):
    responses = [
        {"choices": [{"message": {"content": json.dumps({
            "board": ["r3k4"] + ["9"] * 8,
            "red_to_move": "red",
        })}}]},
        {"choices": [{"message": {"content": json.dumps({
            "board": ["r3k4"] + ["9"] * 8 + ["R3K4"],
            "red_to_move": "red",
        })}}]},
    ]
    requests = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, **kwargs):
        requests.append(json.loads(request.data))
        return FakeResponse(responses.pop(0))

    monkeypatch.setenv("AGENT_OPENAI_BASE_URL", "https://vision.example/v1")
    monkeypatch.setenv("AGENT_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_OPENAI_MODEL", "vision-model")
    monkeypatch.setattr("app.llm.urlopen", fake_urlopen)

    result = _request_vision(b"image", "image/png")

    assert result.fen == "r3k4/9/9/9/9/9/9/9/9/R3K4 w - - 0 1"
    assert len(requests) == 2
    assert "上一次识别结果未通过棋盘校验" in requests[1]["messages"][0]["content"]


def test_vision_reports_validation_reason_after_retry(monkeypatch):
    response = {"choices": [{"message": {"content": json.dumps({
        "board": ["r3k4"] + ["9"] * 8,
        "red_to_move": "red",
    })}}]}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(response).encode("utf-8")

    monkeypatch.setenv("AGENT_OPENAI_BASE_URL", "https://vision.example/v1")
    monkeypatch.setenv("AGENT_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_OPENAI_MODEL", "vision-model")
    monkeypatch.setattr("app.llm.urlopen", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(VisionRecognitionError, match="10 行"):
        _request_vision(b"image", "image/png")


def test_llm_provider_lifecycle_logs_safe_success_metadata(monkeypatch):
    from app.llm import _request_chat

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "private-output-sentinel"}}]}).encode()

    class Capture(logging.Handler):
        def __init__(self):
            super().__init__()
            self.messages = []

        def emit(self, record):
            self.messages.append(" ".join(
                [record.getMessage()] + [f"{key}={getattr(record, key, '-')}"
                 for key in ("operation", "model", "provider_host", "duration_ms", "status", "error_class", "error_category")]
            ))

    logger = logging.getLogger("app.llm")
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    capture = Capture()
    logger.addHandler(capture)
    try:
        monkeypatch.setenv("AGENT_OPENAI_BASE_URL", "https://chat.example/private/path?secret=query")
        monkeypatch.setenv("AGENT_OPENAI_API_KEY", "private-key-sentinel")
        monkeypatch.setenv("AGENT_OPENAI_MODEL", "safe-model")
        monkeypatch.setattr("app.llm.urlopen", lambda *args, **kwargs: FakeResponse())
        assert _request_chat({
            "question": "private-prompt-sentinel", "fen": START_FEN,
            "moves": ["private-move-sentinel"], "context": "private-context-sentinel",
            "messages": [{"role": "user", "content": "private-history-sentinel"}],
        }) == "private-output-sentinel"
    finally:
        logger.removeHandler(capture)
        logger.setLevel(previous_level)

    output = "\n".join(capture.messages)
    assert "llm.request.started" in output
    assert "llm.request.succeeded" in output
    assert "operation=chat" in output
    assert "model=safe-model" in output
    assert "provider_host=chat.example" in output
    assert "duration_ms=" in output
    for secret in (
        "private-key-sentinel", "private-prompt-sentinel", "private-output-sentinel",
        "private-context-sentinel", "private-history-sentinel", START_FEN,
        "private-move-sentinel", "/private/path", "secret=query",
    ):
        assert secret not in output


@pytest.mark.parametrize(
    ("failure", "category", "status"),
    [
        (lambda: HTTPError("https://chat.example/private/path", 429, "private-body-sentinel", {}, BytesIO(b"private-body-sentinel")), "http_error", "429"),
        (lambda: TimeoutError("private-timeout-sentinel"), "timeout", "-"),
        (lambda: URLError(ssl.SSLCertVerificationError("private-tls-sentinel")), "tls_error", "-"),
        (lambda: URLError("private-network-sentinel"), "network_error", "-"),
        (lambda: None, "invalid_json", "-"),
        (lambda: None, "invalid_response", "-"),
    ],
    ids=["http-429", "timeout", "tls", "network", "malformed-json", "response-shape"],
)
def test_llm_provider_lifecycle_classifies_failures_without_sensitive_data(monkeypatch, failure, category, status):
    from app.llm import _request_chat

    class FakeResponse:
        def __init__(self, content):
            self.content = content

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return self.content

    class Capture(logging.Handler):
        def __init__(self):
            super().__init__()
            self.messages = []

        def emit(self, record):
            self.messages.append(" ".join(
                [record.getMessage()] + [f"{key}={getattr(record, key, '-')}"
                 for key in ("operation", "model", "provider_host", "duration_ms", "status", "error_class", "error_category")]
            ))

    logger = logging.getLogger("app.llm")
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    capture = Capture()
    logger.addHandler(capture)
    try:
        monkeypatch.setenv("AGENT_OPENAI_BASE_URL", "https://chat.example/private/path?secret=query")
        monkeypatch.setenv("AGENT_OPENAI_API_KEY", "private-key-sentinel")
        monkeypatch.setenv("AGENT_OPENAI_MODEL", "safe-model")
        if category == "invalid_json":
            monkeypatch.setattr("app.llm.urlopen", lambda *args, **kwargs: FakeResponse(b"private-body-sentinel"))
        elif category == "invalid_response":
            body = json.dumps({"choices": []}).encode()
            monkeypatch.setattr("app.llm.urlopen", lambda *args, **kwargs: FakeResponse(body))
        else:
            def fail(*args, **kwargs):
                raise failure()
            monkeypatch.setattr("app.llm.urlopen", fail)
        with pytest.raises(LLMUnavailable):
            _request_chat({"question": "private-prompt-sentinel", "fen": START_FEN, "moves": [], "context": "", "messages": []})
    finally:
        logger.removeHandler(capture)
        logger.setLevel(previous_level)

    output = "\n".join(capture.messages)
    assert "llm.request.started" in output
    assert "llm.request.failed" in output
    expected_error_class = {
        "http_error": "HTTPError",
        "timeout": "TimeoutError",
        "tls_error": "URLError",
        "network_error": "URLError",
        "invalid_json": "JSONDecodeError",
        "invalid_response": "IndexError",
    }[category]
    assert f"error_class={expected_error_class}" in output
    assert f"error_category={category}" in output
    assert f"status={status}" in output
    assert "provider_host=chat.example" in output
    for secret in (
        "private-key-sentinel", "private-prompt-sentinel", "private-body-sentinel",
        "private-timeout-sentinel", "private-tls-sentinel", "private-network-sentinel",
        "/private/path", "secret=query",
    ):
        assert secret not in output


def test_llm_plan_explanation_and_vision_emit_operation_lifecycle(monkeypatch):
    from app.llm import _request_explanation, _request_vision_payload

    class FakeResponse:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return self.body

    class Capture(logging.Handler):
        def __init__(self):
            super().__init__()
            self.messages = []

        def emit(self, record):
            self.messages.append(" ".join(
                [record.getMessage()] + [f"{key}={getattr(record, key, '-')}"
                 for key in ("operation", "model", "provider_host", "duration_ms", "status", "error_category")]
            ))

    logger = logging.getLogger("app.llm")
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    capture = Capture()
    logger.addHandler(capture)
    try:
        monkeypatch.setenv("AGENT_OPENAI_BASE_URL", "https://vision.example/v1")
        monkeypatch.setenv("AGENT_OPENAI_API_KEY", "secret-key")
        monkeypatch.setenv("AGENT_OPENAI_MODEL", "safe-model")
        responses = [
            {"choices": [{"message": {"content": json.dumps({"advantages": [], "risks": [], "engine_assessment": "", "suggestion": ""})}}]},
            {"choices": [{"message": {"content": json.dumps({"board": ["r3k4"] + ["9"] * 8 + ["R3K4"], "red_to_move": "red"})}}]},
        ]
        monkeypatch.setattr("app.llm.urlopen", lambda *args, **kwargs: FakeResponse(json.dumps(responses.pop(0)).encode()))
        _request_explanation({"plan": "private-plan-sentinel"})
        _request_vision_payload(b"private-image-sentinel", "image/png", "private-vision-prompt-sentinel")
    finally:
        logger.removeHandler(capture)
        logger.setLevel(previous_level)

    output = "\n".join(capture.messages)
    for operation in ("explain", "vision"):
        assert f"operation={operation}" in output
    assert output.count("llm.request.started") == 2
    assert output.count("llm.request.succeeded") == 2
    assert "provider_host=vision.example" in output
    for secret in ("secret-key", "private-plan-sentinel", "private-image-sentinel", "private-vision-prompt-sentinel", "r3k4", "R3K4"):
        assert secret not in output


def test_plan_explanation_accepts_json_wrapped_in_markdown(monkeypatch):
    from app.llm import _request_explanation

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            content = "```json\n" + json.dumps({
                "advantages": ["占据中路"],
                "risks": [],
                "engine_assessment": "两步接近",
                "suggestion": "继续观察主变化",
            }, ensure_ascii=False) + "\n```"
            return json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    monkeypatch.setenv("AGENT_OPENAI_BASE_URL", "https://chat.example/v1")
    monkeypatch.setenv("AGENT_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_OPENAI_MODEL", "test-model")
    monkeypatch.setattr("app.llm.urlopen", lambda *args, **kwargs: FakeResponse())

    result = _request_explanation({"plan": "控制中路"})

    assert result.engine_assessment == "两步接近"
    assert result.advantages == ["占据中路"]


def test_vision_retry_logs_attempt_and_safe_validation_category(monkeypatch):
    from app.llm import _request_vision

    class FakeResponse:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return self.body

    class Capture(logging.Handler):
        def __init__(self):
            super().__init__()
            self.messages = []

        def emit(self, record):
            self.messages.append(record.getMessage())

    logger = logging.getLogger("app.llm")
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    capture = Capture()
    logger.addHandler(capture)
    responses = [
        {"choices": [{"message": {"content": json.dumps({"board": ["r3k4"] + ["9"] * 8, "red_to_move": "red"})}}]},
        {"choices": [{"message": {"content": json.dumps({"board": ["r3k4"] + ["9"] * 8, "red_to_move": "red"})}}]},
    ]
    try:
        monkeypatch.setenv("AGENT_OPENAI_BASE_URL", "https://vision.example/private/path")
        monkeypatch.setenv("AGENT_OPENAI_API_KEY", "private-key-sentinel")
        monkeypatch.setenv("AGENT_OPENAI_MODEL", "vision-model")
        monkeypatch.setattr("app.llm.urlopen", lambda *args, **kwargs: FakeResponse(json.dumps(responses.pop(0)).encode()))
        with pytest.raises(VisionRecognitionError):
            _request_vision(b"private-image-sentinel", "image/png")
    finally:
        logger.removeHandler(capture)
        logger.setLevel(previous_level)

    output = "\n".join(capture.messages)
    assert "attempt=1 validation_category=invalid_board" in output
    assert "attempt=2 validation_category=invalid_board" in output
    assert output.count("llm.request.started") == 2
    assert output.count("llm.request.succeeded") == 2
    for secret in ("private-key-sentinel", "private-image-sentinel", "r3k4", "/private/path"):
        assert secret not in output
