import asyncio

import pytest
from pydantic import ValidationError

from app.models import EngineResponse, Score
from app.review import review_game
from app.xiangqi import START_FEN


def test_long_review_segment_preserves_absolute_plies_and_full_prefix():
    moves = ["b0c2", "b9c7", "c2b0", "c7b9"] * 33

    class Engine:
        def __init__(self):
            self.prefixes = []

        async def analyze(self, fen, prefix, *args):
            assert fen == START_FEN
            self.prefixes.append(list(prefix))
            return EngineResponse(bestmove=moves[len(prefix) % 4], score=Score(type="cp", value=0), pv=[])

    engine = Engine()
    result = asyncio.run(review_game(engine, START_FEN, moves, 8, 250, 1, 128, start_ply=120))
    assert [item.ply for item in result.items] == list(range(121, 133))
    assert [item.side for item in result.items[:2]] == ["red", "black"]
    assert engine.prefixes == [moves[:i] for i in range(120, 133)]
    assert result.analyzed_plies == 132


def test_segment_keeps_rule_history_before_boundary():
    fen = "4k4/9/9/9/R1r1P4/9/9/9/9/4K4 w - - 0 1"
    moves = ["a5b5", "c5c6", "b5b6", "c6c5", "b6b5", "c5c6", "b5b6"]

    class Engine:
        async def analyze(self, *_args):
            return EngineResponse(bestmove="b5b6", score=None, pv=[])

    result = asyncio.run(review_game(Engine(), fen, moves, 8, 250, 1, 128, start_ply=6))
    assert result.analyzed_plies == 6
    assert result.items == []
    assert result.stop.ply == 7
    assert result.stop.kind == "perpetual_chase"


def test_segment_contract_bounds_work_and_rejects_invalid_history():
    from app.models import ReviewSegmentRequest

    moves = ["b0c2", "b9c7", "c2b0", "c7b9"] * 33
    assert ReviewSegmentRequest(fen=START_FEN, moves=moves, start_ply=120).start_ply == 120
    for values in [dict(start_ply=-1), dict(start_ply=133), dict(start_ply=0), dict(start_ply=120, moves=moves * 4)]:
        with pytest.raises(ValidationError):
            ReviewSegmentRequest.model_validate(dict(fen=START_FEN, moves=moves) | values)

    with pytest.raises(ValueError, match="无效"):
        asyncio.run(review_game(None, START_FEN, moves[:120] + ["a0a9"], 8, 250, 1, 128, start_ply=120))


@pytest.mark.parametrize("error_type,code", [("EngineQueueTimeout", "engine_queue_timeout"), ("EngineQueueFull", "engine_queue_full")])
def test_segment_endpoint_preserves_validation_and_structured_load_errors(monkeypatch, error_type, code):
    from fastapi import HTTPException
    from app import main
    from app import engine as engine_module
    from app.models import ReviewSegmentRequest

    moves = ["b0c2", "b9c7", "c2b0", "c7b9"] * 30 + ["a0a9"]
    with pytest.raises(HTTPException) as invalid:
        asyncio.run(main.review_segment(ReviewSegmentRequest(fen=START_FEN, moves=moves, start_ply=120)))
    assert invalid.value.status_code == 400
    assert invalid.value.detail["code"] == "invalid_move_history"

    async def loaded(*_args, **_kwargs):
        raise getattr(engine_module, error_type)("引擎繁忙")

    monkeypatch.setattr(main, "review_game", loaded)
    with pytest.raises(HTTPException) as busy:
        asyncio.run(main.review_segment(ReviewSegmentRequest(fen=START_FEN, moves=["a3a4"])))
    assert busy.value.status_code == 503
    assert busy.value.detail["code"] == code


def test_long_review_coach_accepts_full_history_but_retains_play_limit():
    from app.models import CoachRequest

    moves = ["b0c2", "b9c7", "c2b0", "c7b9"] * 100
    assert len(CoachRequest(fen=START_FEN, question="解释这步", moves=moves).moves) == 400
    with pytest.raises(ValidationError):
        CoachRequest(fen=START_FEN, question="解释这步", moves=moves + ["a3a4"])
