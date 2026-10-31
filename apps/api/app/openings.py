import json
from pathlib import Path

from .models import OpeningsResponse, OpeningLine
from .xiangqi import Position, START_FEN, describe_uci, validate_moves


DATA_FILE = Path(__file__).with_name("openings.json")


def lookup_openings(fen: str, moves: list[str]) -> OpeningsResponse:
    # The bundled lines are rooted at the standard initial position. Avoid
    # reporting false matches for arbitrary user-loaded FENs.
    if " ".join(fen.strip().split()[:2]) != " ".join(START_FEN.split()[:2]):
        return OpeningsResponse(matches=[])
    valid, error, index = validate_moves(fen, moves)
    if not valid:
        raise ValueError(f"第 {index + 1} 步无效: {error}")
    entries = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    candidates = [entry for entry in entries if len(entry["moves"]) >= len(moves) and entry["moves"][:len(moves)] == moves]
    position = Position.from_fen(fen)
    for move in moves:
        position.apply_uci(move)
    next_by_move: dict[str, str] = {}
    for entry in candidates:
        if len(entry["moves"]) > len(moves):
            move = entry["moves"][len(moves)]
            next_by_move.setdefault(move, describe_uci(position, move))
    matches = [OpeningLine(
        name=entry["name"], aliases=entry["aliases"], source=entry["source"],
        matched_plies=len(moves),
        next_moves=[{"move": move, "label": label} for move, label in next_by_move.items()],
    ) for entry in candidates]
    return OpeningsResponse(matches=matches)
