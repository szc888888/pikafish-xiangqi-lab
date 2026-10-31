"""Validation and normalization for vision-based Xiangqi board recognition."""

from dataclasses import dataclass
from typing import Any

from .xiangqi import Position

PIECES = set("rnbakcpRNBKACP.")
PIECE_LIMITS = {
    "K": 1, "k": 1, "A": 2, "a": 2, "B": 2, "b": 2,
    "R": 2, "r": 2, "C": 2, "c": 2, "N": 2, "n": 2,
    "P": 5, "p": 5,
}


@dataclass(frozen=True)
class VisionPosition:
    fen: str
    red_to_move: bool
    piece_count: int
    warnings: list[str]


def _normalize_row(row: Any) -> list[str]:
    values = list(row) if isinstance(row, list) else list(row) if isinstance(row, str) else None
    if values is None:
        raise ValueError("视觉识别结果的每一行必须是字符串或数组")
    cells: list[str] = []
    for value in values:
        if not isinstance(value, str) or len(value) != 1:
            raise ValueError("视觉识别结果包含无效棋子")
        if value.isdigit():
            count = int(value)
            if count < 1 or count > 9:
                raise ValueError("视觉识别结果包含无效空格数量")
            cells.extend(["."] * count)
        elif value in PIECES:
            cells.append(value)
        else:
            raise ValueError(f"未知棋子: {value}")
    if len(cells) != 9:
        raise ValueError("视觉识别结果每行必须有 9 个格子")
    return cells


def _row_to_fen(row: list[str]) -> str:
    result = ""
    empty = 0
    for piece in row:
        if piece == ".":
            empty += 1
        else:
            if empty:
                result += str(empty)
                empty = 0
            result += piece
    if empty:
        result += str(empty)
    return result


def parse_vision_position(payload: Any) -> VisionPosition:
    if not isinstance(payload, dict):
        raise ValueError("视觉识别结果必须是 JSON 对象")
    rows = payload.get("board")
    if not isinstance(rows, list) or len(rows) != 10:
        raise ValueError("视觉识别结果必须包含 10 行棋盘")
    board = [_normalize_row(row) for row in rows]
    red_to_move = payload.get("red_to_move")
    if red_to_move in ("red", "w", True):
        red_to_move = True
    elif red_to_move in ("black", "b", False):
        red_to_move = False
    else:
        raise ValueError("视觉识别结果的行棋方必须是 red 或 black")

    counts: dict[str, int] = {}
    for row in board:
        for piece in row:
            if piece != ".":
                counts[piece] = counts.get(piece, 0) + 1
    if counts.get("K", 0) != 1:
        raise ValueError("红方帅必须恰好一个")
    if counts.get("k", 0) != 1:
        raise ValueError("黑方将必须恰好一个")
    for piece, limit in PIECE_LIMITS.items():
        if counts.get(piece, 0) > limit:
            raise ValueError(f"棋子 {piece} 数量不能超过 {limit} 个")

    board_fen = "/".join(_row_to_fen(row) for row in board)
    fen = f"{board_fen} {'w' if red_to_move else 'b'} - - 0 1"
    Position.from_fen(fen)
    return VisionPosition(
        fen=fen,
        red_to_move=red_to_move,
        piece_count=sum(counts.values()),
        warnings=[],
    )
