from app.engine_strength import PROFILE_DEFINITIONS, profile_for, select_candidate
from app.models import EngineLine, Score, EngineMoveRequest, EngineResponse
from app.xiangqi import START_FEN


def _lines():
    return [
        EngineLine(rank=1, move="a0a1", label="车一进一", score=Score(type="cp", value=100)),
        EngineLine(rank=2, move="b0b1", label="马八进七", score=Score(type="cp", value=90)),
        EngineLine(rank=3, move="c0c1", label="炮二平五", score=Score(type="cp", value=10)),
    ]


def test_profiles_expose_five_user_facing_levels():
    assert [profile.label for profile in PROFILE_DEFINITIONS.values()] == [
        "轻松陪练", "入门练习", "进阶对手", "认真对弈", "全力挑战",
    ]


def test_selection_is_deterministic_for_same_game_seed():
    profile = profile_for("companion")
    first = select_candidate(_lines(), profile, "game-1:4")
    second = select_candidate(_lines(), profile, "game-1:4")
    assert first == second
    assert first.line.rank <= profile.max_rank


def test_selection_excludes_candidates_over_score_loss_limit():
    profile = profile_for("progress")
    selected = select_candidate(_lines(), profile, "game-2:8")
    assert selected.line.rank in {1, 2}


def test_full_profile_always_selects_best_candidate():
    selected = select_candidate(_lines(), profile_for("full"), "any-seed")
    assert selected.line.rank == 1


def test_disabling_suboptimal_moves_always_selects_best_legal_candidate():
    selected = select_candidate(_lines(), profile_for("companion"), "seed", allow_suboptimal=False)
    assert selected.line.rank == 1


def test_custom_profile_uses_bounded_overrides():
    profile = profile_for("custom", depth=1, movetime_ms=100, threads=99, hash_mb=99999)
    assert profile.depth == 1
    assert profile.movetime_ms == 100
    assert profile.threads == 16
    assert profile.hash_mb == 8192


def test_missing_candidate_scores_are_not_used_for_weakened_selection():
    lines = [
        EngineLine(rank=1, move="a0a1", label="最佳", score=Score(type="cp", value=100)),
        EngineLine(rank=2, move="b0b1", label="无分值候选", score=None),
        EngineLine(rank=3, move="c0c1", label="有分值候选", score=Score(type="cp", value=90)),
    ]
    for seed in map(str, range(20)):
        assert select_candidate(lines, profile_for("companion"), seed).line.move != "b0b1"


def test_missing_best_score_falls_back_to_best_candidate():
    lines = [
        EngineLine(rank=1, move="a0a1", label="最佳", score=None),
        EngineLine(rank=2, move="b0b1", label="有分值候选", score=Score(type="cp", value=-500)),
    ]
    assert select_candidate(lines, profile_for("companion"), "seed").line.move == "a0a1"


def test_all_candidates_without_scores_fall_back_to_rank_one():
    lines = [
        EngineLine(rank=1, move="a0a1", label="最佳", score=None),
        EngineLine(rank=2, move="b0b1", label="无分值候选", score=None),
    ]
    assert select_candidate(lines, profile_for("companion"), "seed").line.move == "a0a1"


def test_mate_scores_keep_only_candidates_within_the_mate_loss_budget():
    lines = [
        EngineLine(rank=1, move="a0a1", label="三步杀", score=Score(type="mate", value=3)),
        EngineLine(rank=2, move="b0b1", label="五步杀", score=Score(type="mate", value=5)),
        EngineLine(rank=3, move="c0c1", label="一步杀", score=Score(type="mate", value=1)),
    ]
    profile = profile_for("custom")
    # Full-strength/custom selection only chooses rank 1; exercise the mate loss
    # comparator through a weakened profile with a generous rank allowance.
    from dataclasses import replace
    weakened = replace(profile, full_strength=False, max_rank=3, max_loss_cp=1000)
    for seed in map(str, range(30)):
        assert select_candidate(lines, weakened, seed).line.rank in {1, 3}


def test_losing_mate_scores_measure_loss_by_shorter_survival():
    lines = [
        EngineLine(rank=1, move="a0a1", label="多活三步", score=Score(type="mate", value=-3)),
        EngineLine(rank=2, move="b0b1", label="多活五步", score=Score(type="mate", value=-5)),
        EngineLine(rank=3, move="c0c1", label="一步被杀", score=Score(type="mate", value=-1)),
    ]
    from dataclasses import replace
    weakened = replace(profile_for("custom"), full_strength=False, max_rank=3, max_loss_cp=1000)
    for seed in map(str, range(30)):
        assert select_candidate(lines, weakened, seed).line.rank in {1, 2}


def test_fixed_profiles_adapt_threads_to_available_cpu_count():
    one_cpu = profile_for("serious", available_threads=1)
    two_cpu = profile_for("full", available_threads=2)
    four_cpu = profile_for("full", available_threads=4)
    assert one_cpu.threads == 1
    assert two_cpu.threads == 2
    assert four_cpu.threads == 4


def test_move_endpoint_uses_profile_and_deterministic_selection(monkeypatch):
    from app import main

    called = {}

    async def fake_analyze(fen, moves, depth, movetime_ms, multipv, threads, hash_mb):
        called.update(depth=depth, movetime_ms=movetime_ms, multipv=multipv)
        return EngineResponse(bestmove="a0a1", lines=_lines())

    monkeypatch.setattr(main.engine, "analyze", fake_analyze)
    request = EngineMoveRequest(fen=START_FEN, moves=[], difficulty="companion", game_id="g1", ply=0)
    result = __import__("asyncio").run(main.engine_move(request))
    assert called == {"depth": 1, "movetime_ms": 100, "multipv": 5}
    assert result.difficulty_label == "轻松陪练"
    assert result.selection_seed == "g1:0"
    assert result.bestmove == select_candidate(_lines(), profile_for("companion"), "g1:0").line.move


def test_engine_move_request_exposes_suboptimal_move_setting():
    request = EngineMoveRequest(fen=START_FEN, moves=[], difficulty="companion", game_id="g1", ply=0,
                                allow_suboptimal=False)
    assert request.allow_suboptimal is False


def test_move_endpoint_honors_disabled_suboptimal_moves(monkeypatch):
    from app import main

    async def fake_analyze(fen, moves, depth, movetime_ms, multipv, threads, hash_mb):
        return EngineResponse(bestmove="a0a1", lines=_lines())

    monkeypatch.setattr(main.engine, "analyze", fake_analyze)
    request = EngineMoveRequest(fen=START_FEN, moves=[], difficulty="companion", game_id="g1", ply=0,
                                allow_suboptimal=False)
    result = __import__("asyncio").run(main.engine_move(request))
    assert result.selected_rank == 1
    assert result.bestmove == "a0a1"


def test_move_endpoint_rejects_invalid_history_before_engine(monkeypatch):
    from app import main
    from fastapi import HTTPException

    async def forbidden(*args, **kwargs):
        raise AssertionError("engine must not receive invalid move history")

    monkeypatch.setattr(main.engine, "analyze", forbidden)
    request = EngineMoveRequest(fen=START_FEN, moves=["z9z9"], difficulty="full", game_id="g2", ply=1)
    with __import__("pytest").raises(HTTPException) as error:
        __import__("asyncio").run(main.engine_move(request))
    assert error.value.status_code == 400


def test_move_endpoint_passes_custom_search_parameters(monkeypatch):
    from app import main
    from app.xiangqi import START_FEN

    called = {}

    async def fake_analyze(fen, moves, depth, movetime_ms, multipv, threads, hash_mb):
        called.update(depth=depth, movetime_ms=movetime_ms, multipv=multipv, threads=threads, hash_mb=hash_mb)
        return EngineResponse(bestmove="a0a1", lines=[_lines()[0]])

    monkeypatch.setattr(main.engine, "analyze", fake_analyze)
    monkeypatch.setattr(main.os, "cpu_count", lambda: 8)
    request = EngineMoveRequest(
        fen=START_FEN, moves=[], difficulty="custom", game_id="custom", ply=0,
        depth=3, movetime_ms=500, multipv=1, threads=3, hash_mb=128,
    )
    __import__("asyncio").run(main.engine_move(request))
    assert called == {"depth": 3, "movetime_ms": 500, "multipv": 1, "threads": 3, "hash_mb": 128}


def test_fixed_profile_degrades_threads_on_low_core_host(monkeypatch):
    from app import main
    from app.xiangqi import START_FEN

    called = {}

    async def fake_analyze(fen, moves, depth, movetime_ms, multipv, threads, hash_mb):
        called["threads"] = threads
        return EngineResponse(bestmove="a0a1", lines=[_lines()[0]])

    monkeypatch.setattr(main.engine, "analyze", fake_analyze)
    monkeypatch.setattr(main.os, "cpu_count", lambda: 1)
    request = EngineMoveRequest(fen=START_FEN, moves=[], difficulty="serious", game_id="low-cpu", ply=0)
    __import__("asyncio").run(main.engine_move(request))
    assert called["threads"] == 1


def test_move_endpoint_rejects_custom_threads_above_host_cpu_count(monkeypatch):
    from app import main
    from app.xiangqi import START_FEN
    from fastapi import HTTPException
    import pytest

    async def forbidden(*args, **kwargs):
        raise AssertionError("engine must not receive an over-limit thread count")

    monkeypatch.setattr(main.engine, "analyze", forbidden)
    monkeypatch.setattr(main.os, "cpu_count", lambda: 2)
    request = EngineMoveRequest(
        fen=START_FEN, moves=[], difficulty="custom", game_id="over-cpu", ply=0,
        depth=3, movetime_ms=500, multipv=1, threads=3, hash_mb=128,
    )
    with pytest.raises(HTTPException) as error:
        __import__("asyncio").run(main.engine_move(request))
    assert error.value.status_code == 400
    assert "逻辑处理器数量 2" in error.value.detail["message"]
