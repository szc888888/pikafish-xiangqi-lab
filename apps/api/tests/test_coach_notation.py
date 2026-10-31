import re

from app.coach_notation import normalize_coach_notation
from app.xiangqi import START_FEN


def test_normalize_coach_notation_converts_coordinate_duplicates():
    answer = '推荐走炮二平五（H2-E2 / "h2e2"）。'

    normalized = normalize_coach_notation(answer, START_FEN, [])

    assert normalized == "推荐走炮二平五。"


def test_normalize_coach_notation_removes_unresolvable_coordinate_moves():
    normalized = normalize_coach_notation("请考虑 e6-e5 或 e6e5。", START_FEN, [])

    assert not re.search(r"[a-i][0-9]\s*[-–—]?\s*[a-i][0-9]", normalized, re.IGNORECASE)
    assert "该着法" in normalized


def test_normalize_coach_notation_uses_chinese_digits_for_red_moves():
    normalized = normalize_coach_notation("推荐炮2平5。", START_FEN, [])

    assert normalized == "推荐炮二平五。"


def test_normalize_coach_notation_uses_arabic_digits_for_black_moves():
    black_to_move = START_FEN.replace(" w ", " b ")

    normalized = normalize_coach_notation("黑方可走炮二平五。", black_to_move, [])

    assert normalized == "黑方可走炮2平5。"
