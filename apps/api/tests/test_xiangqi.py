import pytest

from app.xiangqi import (
    Position,
    START_FEN,
    describe_uci,
    perpetual_check_side,
    perpetual_chase_side,
    resolve_move,
    terminal_status,
    validate_fen,
    validate_history,
    validate_moves,
)


def test_start_fen_has_ten_rows():
    position = Position.from_fen(START_FEN)
    assert len(position.board) == 10
    assert position.red_to_move is True
    assert position.board[9][4] == "K"


def test_terminal_status_distinguishes_checkmate_from_playable_position():
    checkmate = Position.from_fen("3k1ab2/4a2r1/3Nb4/p1p3n1p/9/2P2p2P/P3P3c/B2C1R3/4A4/3A1K3 b - - 0 1")
    normal = Position.from_fen(START_FEN)

    assert terminal_status(checkmate) == "checkmate"
    assert terminal_status(normal) is None


def test_terminal_status_reports_stalemate_separately(monkeypatch):
    import app.xiangqi as rules

    monkeypatch.setattr(rules, "legal_moves", lambda _position, _source: [])
    monkeypatch.setattr(rules, "is_in_check", lambda _position, _red: False)

    assert terminal_status(Position.from_fen(START_FEN)) == "stalemate"


def test_pawn_move_is_valid():
    valid, error, index = validate_moves(START_FEN, ["a3a4"])
    assert valid is True
    assert error is None
    assert index is None


def test_wrong_side_is_rejected():
    valid, error, index = validate_moves(START_FEN, ["a6a5"])
    assert valid is False
    assert index == 0
    assert "不是该方" in error


def test_invalid_fen_is_rejected():
    with pytest.raises(ValueError):
        Position.from_fen("9/9 w")


def test_fen_requires_one_king_each_and_rejects_facing_kings():
    with pytest.raises(ValueError, match="红方帅"):
        Position.from_fen("4k4/9/9/9/9/9/9/9/9/9 w - - 0 1")
    with pytest.raises(ValueError, match="将帅照面"):
        validate_fen("4k4/9/9/9/9/9/9/9/9/4K4 w - - 0 1")


def test_history_validation_returns_structured_long_chase_stop():
    result = validate_history(
        "4k4/9/9/9/R1r1P4/9/9/9/9/4K4 w - - 0 1",
        ["a5b5", "c5c6", "b5b6", "c6c5", "b6b5", "c5c6", "b5b6"],
    )
    assert result.issue is not None
    assert result.issue.code == "perpetual_chase"
    assert result.issue.ply == 7
    assert result.issue.side == "red"
    assert len(result.positions) == 8


def test_resolve_chinese_and_uci_move():
    assert resolve_move(START_FEN, "炮二平五") == "h2e2"
    assert resolve_move(START_FEN, "h2e2") == "h2e2"
    assert describe_uci(Position.from_fen(START_FEN), "h2e2")


def test_resolve_illegal_move_has_readable_error():
    with pytest.raises(ValueError, match="无法识别|不合法"):
        resolve_move(START_FEN, "将五平六")


def test_repeated_cycle_with_same_side_check_is_perpetual_check():
    quiet = Position.from_fen("4k4/9/9/9/R3p4/9/9/9/9/4K4 w - - 0 1")
    check = Position.from_fen("4k4/9/9/9/4R4/9/9/9/9/4K4 b - - 0 1")
    assert perpetual_check_side([quiet, check, quiet, check, quiet]) == "red"


def test_repeated_cycle_without_check_is_allowed_by_perpetual_check_detector():
    quiet = Position.from_fen("4k4/9/9/9/R3p4/9/9/9/9/4K4 w - - 0 1")
    assert perpetual_check_side([quiet, quiet, quiet]) is None


def test_repeated_attacks_on_same_unguarded_piece_are_perpetual_chase():
    fen = "4k4/9/9/9/R1r1P4/9/9/9/9/4K4 w - - 0 1"
    moves = ["a5b5", "c5c6", "b5b6", "c6c5", "b6b5", "c5c6", "b5b6", "c6c5", "e0d0"]
    position = Position.from_fen(fen)
    positions = [Position([row[:] for row in position.board], position.red_to_move)]
    for move in moves:
        position.apply_uci(move)
        positions.append(Position([row[:] for row in position.board], position.red_to_move))

    assert perpetual_chase_side(positions[:-2], moves[:-2]) == "red"
    assert perpetual_chase_side(positions[:-1], moves[:-1]) is None
    assert perpetual_chase_side(positions, moves) is None


def test_move_validation_rejects_perpetual_chase():
    valid, error, index = validate_moves(
        "4k4/9/9/9/R1r1P4/9/9/9/9/4K4 w - - 0 1",
        ["a5b5", "c5c6", "b5b6", "c6c5", "b6b5", "c5c6", "b5b6", "c6c5"],
    )
    assert valid is False
    assert index == 6
    assert "长捉" in error


def test_repeated_checking_moves_are_detected_without_exact_board_cycle():
    positions = [
        Position.from_fen("4k4/9/9/9/R8/9/9/9/9/3K5 w - - 0 1"),
        Position.from_fen("4k4/9/9/9/4R4/9/9/9/9/3K5 b - - 0 1"),
        Position.from_fen("4k4/9/9/9/1R7/9/9/9/9/3K5 w - - 0 1"),
        Position.from_fen("4k4/9/9/9/9/4R4/9/9/9/3K5 b - - 0 1"),
        Position.from_fen("4k4/9/9/9/2R6/9/9/9/9/3K5 w - - 0 1"),
        Position.from_fen("4k4/9/9/9/9/9/4R4/9/9/3K5 b - - 0 1"),
    ]
    assert perpetual_check_side(positions, ["a5e5", "a0a1", "b5e4", "a1a0", "a5e5"]) == "red"

