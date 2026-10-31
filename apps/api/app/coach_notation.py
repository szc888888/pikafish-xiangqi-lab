"""Normalize coordinate move notation before coach answers reach the UI."""

import re

from .xiangqi import CN_NUMBERS, Position, describe_uci, resolve_move_position


_COORDINATE_MOVE = re.compile(
    r"(?<![A-Za-z0-9])([a-i])([0-9])\s*[-–—]?\s*([a-i])([0-9])(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_MIXED_CHINESE_MOVE = re.compile(
    r"(?P<piece>[车車马馬象相士仕将帅炮兵卒])"
    r"(?P<source>[1-9一二三四五六七八九])"
    r"(?P<action>[平进退])"
    r"(?P<target>[1-9一二三四五六七八九])"
)


def _normalize_mixed_chinese_move(match: re.Match[str], position: Position) -> str | None:
    """Resolve a Chinese move whose file digits use the wrong digit style."""
    source = match.group("source")
    target = match.group("target")
    if position.red_to_move:
        source = CN_NUMBERS[int(source) - 1] if source.isdigit() else source
        target = CN_NUMBERS[int(target) - 1] if target.isdigit() else target
    else:
        source = str(CN_NUMBERS.index(source) + 1) if source in CN_NUMBERS else source
        target = str(CN_NUMBERS.index(target) + 1) if target in CN_NUMBERS else target
    notation = f"{match.group('piece')}{source}{match.group('action')}{target}"
    try:
        return resolve_move_position(position, notation)
    except (TypeError, ValueError):
        return None


def normalize_coach_notation(content: str, fen: str, moves: list[str]) -> str:
    """Convert legal coordinate moves in an answer to standard Chinese notation."""
    position = Position.from_fen(fen)
    known_labels: dict[str, str] = {}
    for move in moves:
        normalized = move.strip().lower()
        try:
            known_labels.setdefault(normalized, describe_uci(position, normalized))
            position.apply_uci(normalized)
        except ValueError:
            break

    coordinate_parentheses = re.compile(
        r"[（(][^()]{0,160}" + _COORDINATE_MOVE.pattern + r"[^()]{0,160}[）)]",
        re.IGNORECASE,
    )
    normalized_content = coordinate_parentheses.sub("", content)

    def replace_mixed(match: re.Match[str]) -> str:
        # Standard notation already uses the side-appropriate digit style.
        if (position.red_to_move and not match.group("source").isdigit() and not match.group("target").isdigit()) or (
            not position.red_to_move and match.group("source").isdigit() and match.group("target").isdigit()
        ):
            return match.group(0)
        uci = _normalize_mixed_chinese_move(match, position)
        if uci is None:
            return "该着法"
        label = describe_uci(position, uci)
        position.apply_uci(uci)
        return label

    normalized_content = _MIXED_CHINESE_MOVE.sub(replace_mixed, normalized_content)

    def replace_move(match: re.Match[str]) -> str:
        move = "".join(group.lower() for group in match.groups())
        label = known_labels.get(move)
        if label is not None:
            return label
        try:
            label = describe_uci(position, move)
            position.apply_uci(move)
            return label
        except (TypeError, ValueError):
            return "该着法"

    return _COORDINATE_MOVE.sub(replace_move, normalized_content)
