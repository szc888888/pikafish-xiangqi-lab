"""Small, dependency-free Xiangqi position validator used at the API boundary."""

from dataclasses import dataclass

FILES = "abcdefghi"
START_FEN = "rnbakabnr/9/1c5c1/p1p1p1p1p/9/9/P1P1P1P1P/1C5C1/9/RNBAKABNR w - - 0 1"
PIECE_LIMITS = {"K": 1, "k": 1, "A": 2, "a": 2, "B": 2, "b": 2, "R": 2, "r": 2, "C": 2, "c": 2, "N": 2, "n": 2, "P": 5, "p": 5}


@dataclass
class Position:
    board: list[list[str]]
    red_to_move: bool

    @classmethod
    def from_fen(cls, fen: str) -> "Position":
        fields = fen.strip().split()
        if len(fields) < 2:
            raise ValueError("FEN 至少需要棋盘和行棋方字段")
        rows = fields[0].split("/")
        if len(rows) != 10:
            raise ValueError("中国象棋 FEN 必须包含 10 行")
        board: list[list[str]] = []
        for row in rows:
            parsed: list[str] = []
            for char in row:
                if char.isdigit():
                    parsed.extend(["."] * int(char))
                elif char in "rnbakcpRNBKACP":
                    parsed.append(char)
                else:
                    raise ValueError(f"FEN 包含未知棋子: {char}")
            if len(parsed) != 9:
                raise ValueError("FEN 每行必须展开为 9 个格子")
            board.append(parsed)
        if fields[1] not in {"w", "b"}:
            raise ValueError("FEN 行棋方必须是 w 或 b")
        counts: dict[str, int] = {}
        for row in board:
            for piece in row:
                if piece != ".":
                    counts[piece] = counts.get(piece, 0) + 1
        if counts.get("K", 0) != 1:
            raise ValueError("FEN 红方帅必须恰好一个")
        if counts.get("k", 0) != 1:
            raise ValueError("FEN 黑方将必须恰好一个")
        for piece, limit in PIECE_LIMITS.items():
            if counts.get(piece, 0) > limit:
                raise ValueError(f"FEN {piece} 数量不能超过 {limit} 个")
        return cls(board, fields[1] == "w")

    def apply_uci(self, move: str) -> None:
        if len(move) != 4 or move[0] not in FILES or move[2] not in FILES or not move[1].isdigit() or not move[3].isdigit():
            raise ValueError(f"非法 UCI 走法: {move}")
        source = (9 - int(move[1]), FILES.index(move[0]))
        target = (9 - int(move[3]), FILES.index(move[2]))
        if not all(0 <= value < 10 for value in (*source, *target)):
            raise ValueError(f"UCI 坐标超出棋盘: {move}")
        piece = self.board[source[0]][source[1]]
        if piece == ".":
            raise ValueError(f"起点没有棋子: {move}")
        if piece.isupper() != self.red_to_move:
            raise ValueError(f"不是该方走棋: {move}")
        legal = legal_moves(self, source)
        if target not in legal:
            raise ValueError(f"不合法的走法: {move}")
        self.board[target[0]][target[1]] = piece
        self.board[source[0]][source[1]] = "."
        self.red_to_move = not self.red_to_move


@dataclass(frozen=True)
class RuleIssue:
    code: str
    message: str
    ply: int
    side: str


@dataclass
class HistoryValidation:
    positions: list[Position]
    issue: RuleIssue | None = None


def validate_fen(fen: str) -> Position:
    """Parse a position and enforce formal game-position constraints."""
    position = Position.from_fen(fen)
    red_king = find_king(position, True)
    black_king = find_king(position, False)
    if red_king and black_king and red_king[1] == black_king[1]:
        start, end = sorted((red_king[0], black_king[0]))
        if all(position.board[row][red_king[1]] == "." for row in range(start + 1, end)):
            raise ValueError("FEN 将帅照面，局面无效")
    return position


def inside(row: int, col: int) -> bool:
    return 0 <= row < 10 and 0 <= col < 9


def same_side(piece: str, red: bool) -> bool:
    return piece != "." and piece.isupper() == red


def in_palace(row: int, col: int, red: bool) -> bool:
    return 7 <= row <= 9 and 3 <= col <= 5 if red else 0 <= row <= 2 and 3 <= col <= 5


def clear_line(board: list[list[str]], source: tuple[int, int], target: tuple[int, int]) -> int:
    dr = (target[0] > source[0]) - (target[0] < source[0])
    dc = (target[1] > source[1]) - (target[1] < source[1])
    row, col = source[0] + dr, source[1] + dc
    count = 0
    while (row, col) != target:
        if board[row][col] != ".":
            count += 1
        row, col = row + dr, col + dc
    return count


def pseudo_moves(position: Position, source: tuple[int, int]) -> list[tuple[int, int]]:
    board = position.board
    row, col = source
    piece = board[row][col]
    red = piece.isupper()
    kind = piece.lower()
    result: list[tuple[int, int]] = []

    def add(target_row: int, target_col: int) -> None:
        if not inside(target_row, target_col) or same_side(board[target_row][target_col], red):
            return
        result.append((target_row, target_col))

    if kind in {"r", "c"}:
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            target_row, target_col = row + dr, col + dc
            jumped = False
            while inside(target_row, target_col):
                target = board[target_row][target_col]
                if kind == "c" and not jumped:
                    if target == ".":
                        result.append((target_row, target_col))
                    else:
                        jumped = True
                elif kind == "c":
                    if target != ".":
                        if not same_side(target, red):
                            result.append((target_row, target_col))
                        break
                elif target == ".":
                    result.append((target_row, target_col))
                else:
                    if not same_side(target, red):
                        result.append((target_row, target_col))
                    break
                target_row, target_col = target_row + dr, target_col + dc
    elif kind == "n":
        for dr, dc, lr, lc in ((-2, -1, -1, 0), (-2, 1, -1, 0), (2, -1, 1, 0), (2, 1, 1, 0), (-1, -2, 0, -1), (1, -2, 0, -1), (-1, 2, 0, 1), (1, 2, 0, 1)):
            if inside(row + lr, col + lc) and board[row + lr][col + lc] == ".":
                add(row + dr, col + dc)
    elif kind == "b":
        for dr, dc in ((-2, -2), (-2, 2), (2, -2), (2, 2)):
            eye = (row + dr // 2, col + dc // 2)
            target = (row + dr, col + dc)
            if inside(*target) and board[eye[0]][eye[1]] == "." and ((target[0] >= 5) if red else (target[0] <= 4)):
                add(*target)
    elif kind == "a":
        for dr, dc in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
            target = (row + dr, col + dc)
            if in_palace(*target, red):
                add(*target)
    elif kind == "k":
        for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            target = (row + dr, col + dc)
            if in_palace(*target, red):
                add(*target)
        # Flying general capture is represented as a normal king move.
        dr = -1 if red else 1
        target_row = row + dr
        while inside(target_row, col):
            target = board[target_row][col]
            if target != ".":
                if target.lower() == "k" and not same_side(target, red) and clear_line(board, source, (target_row, col)) == 0:
                    result.append((target_row, col))
                break
            target_row += dr
    elif kind == "p":
        forward = -1 if red else 1
        add(row + forward, col)
        crossed = row <= 4 if red else row >= 5
        if crossed:
            add(row, col - 1)
            add(row, col + 1)
    return result


def find_king(position: Position, red: bool) -> tuple[int, int] | None:
    for row in range(10):
        for col in range(9):
            if position.board[row][col] == ("K" if red else "k"):
                return row, col
    return None


def is_attacked(position: Position, target: tuple[int, int], by_red: bool) -> bool:
    king = find_king(position, not by_red)
    for row in range(10):
        for col in range(9):
            piece = position.board[row][col]
            if same_side(piece, by_red) and target in pseudo_moves(position, (row, col)):
                return True
    return False


def is_in_check(position: Position, red: bool) -> bool:
    king = find_king(position, red)
    return king is None or is_attacked(position, king, not red)


def _repetition_key(position: Position) -> str:
    return "/".join("".join(row) for row in position.board) + (" w" if position.red_to_move else " b")


def _material_key(position: Position) -> str:
    return "".join(sorted(piece for row in position.board for piece in row if piece != "."))


def perpetual_check_side(positions: list[Position], moves: list[str] | None = None) -> str | None:
    """Return the side giving continuous checks through a threefold cycle."""
    if len(positions) < 3:
        return None
    occurrences: dict[str, list[int]] = {}
    for index, position in enumerate(positions):
        occurrences.setdefault(_repetition_key(position), []).append(index)
    for indexes in occurrences.values():
        if len(indexes) < 3:
            continue
        cycle_indexes = indexes[-3:]
        for side in ("red", "black"):
            valid = True
            for cycle in range(1, len(cycle_indexes)):
                checked = False
                for index in range(cycle_indexes[cycle - 1], cycle_indexes[cycle]):
                    mover = "red" if positions[index].red_to_move else "black"
                    if mover == side:
                        checked = True
                        if not is_in_check(positions[index + 1], side != "red"):
                            valid = False
                if not checked:
                    valid = False
                if not valid:
                    break
            if valid:
                return side
    if moves is not None and len(moves) == len(positions) - 1:
        for side in ("red", "black"):
            checks: list[tuple[int, str]] = []
            for index in range(len(positions) - 1):
                mover = "red" if positions[index].red_to_move else "black"
                if mover != side:
                    continue
                if not is_in_check(positions[index + 1], side != "red"):
                    checks.clear()
                    continue
                checks.append((index, moves[index]))
                if len(checks) >= 3:
                    window = checks[-3:]
                    repeated_move = len({move for _, move in window}) < len(window)
                    unchanged_material = _material_key(positions[window[0][0]]) == _material_key(positions[index + 1])
                    if repeated_move and unchanged_material:
                        return side
    return None


def _move_squares(move: str) -> tuple[tuple[int, int], tuple[int, int]] | None:
    if len(move) != 4 or move[0] not in FILES or move[2] not in FILES or not move[1].isdigit() or not move[3].isdigit():
        return None
    return (9 - int(move[1]), FILES.index(move[0])), (9 - int(move[3]), FILES.index(move[2]))


def _attacks_piece(position: Position, source: tuple[int, int], target: tuple[int, int]) -> bool:
    piece = position.board[source[0]][source[1]]
    target_piece = position.board[target[0]][target[1]]
    return piece != "." and target_piece != "." and piece.isupper() != target_piece.isupper() and target in legal_moves(position, source)


def perpetual_chase_side(positions: list[Position], moves: list[str] | None = None) -> str | None:
    """Return the side making three consecutive attacks on one moving enemy piece."""
    moves = moves or []
    if len(moves) != len(positions) - 1 or len(moves) < 5:
        return None
    for side in ("red", "black"):
        attacks: list[tuple[int, tuple[int, int], tuple[int, int]]] = []
        for index in range(len(moves) - 2):
            mover = "red" if positions[index].red_to_move else "black"
            first, reply, follow = (_move_squares(moves[index]), _move_squares(moves[index + 1]), _move_squares(moves[index + 2]))
            if mover != side or not first or not reply or not follow or follow[0] != first[1]:
                continue
            if not _attacks_piece(positions[index + 1], first[1], reply[0]) or not _attacks_piece(positions[index + 3], follow[1], reply[1]):
                continue
            attacks.append((index, reply[0], reply[1]))
        for start in range(len(attacks)):
            count = 1
            for next_index in range(start + 1, len(attacks)):
                previous, current = attacks[next_index - 1], attacks[next_index]
                if current[0] != previous[0] + 2 or current[1] != previous[2]:
                    break
                count += 1
                if count >= 3 and current[0] + 2 == len(moves) - 1:
                    return side
    return None


def perpetual_rule_violation(positions: list[Position], moves: list[str] | None = None) -> tuple[str, str] | None:
    if (side := perpetual_check_side(positions, moves)):
        return side, "长将"
    if (side := perpetual_chase_side(positions, moves)):
        return side, "长捉"
    return None


def _copy_position(position: Position) -> Position:
    return Position([row[:] for row in position.board], position.red_to_move)


def _rule_issue(offender: tuple[str, str], ply: int) -> RuleIssue:
    side, kind = offender
    code = "perpetual_check" if kind == "长将" else "perpetual_chase"
    side_label = "红方" if side == "red" else "黑方"
    return RuleIssue(code=code, message=f"{side_label}连续{kind}，违反棋规，不能继续", ply=ply, side=side)


def validate_history(fen: str, moves: list[str]) -> HistoryValidation:
    """Validate a complete history and retain snapshots through the first issue."""
    position = validate_fen(fen)
    positions = [_copy_position(position)]
    for index, move in enumerate(moves):
        side = "red" if position.red_to_move else "black"
        try:
            position.apply_uci(move)
        except ValueError as exc:
            return HistoryValidation(
                positions=positions,
                issue=RuleIssue(code="invalid_move", message=str(exc), ply=index + 1, side=side),
            )
        positions.append(_copy_position(position))
        offender = perpetual_rule_violation(positions, moves[: index + 1])
        if offender:
            return HistoryValidation(positions=positions, issue=_rule_issue(offender, index + 1))
    return HistoryValidation(positions=positions)


@dataclass
class CandidateValidation:
    position: Position | None
    issue: RuleIssue | None = None


def validate_candidate(
    position: Position,
    move: str,
    positions: list[Position] | None = None,
    moves: list[str] | None = None,
) -> CandidateValidation:
    """Validate an engine or user candidate against the current history."""
    side = "red" if position.red_to_move else "black"
    next_position = _copy_position(position)
    try:
        next_position.apply_uci(move)
    except ValueError as exc:
        return CandidateValidation(None, RuleIssue("illegal_move", str(exc), len(moves or []) + 1, side))
    history_positions = [_copy_position(item) for item in (positions or [position])]
    offender = perpetual_rule_violation(history_positions + [next_position], [*(moves or []), move])
    if offender:
        return CandidateValidation(None, _rule_issue(offender, len(moves or []) + 1))
    return CandidateValidation(next_position)


def legal_moves(position: Position, source: tuple[int, int]) -> list[tuple[int, int]]:
    piece = position.board[source[0]][source[1]]
    if piece == ".":
        return []
    red = piece.isupper()
    result: list[tuple[int, int]] = []
    for target in pseudo_moves(position, source):
        clone = Position([row[:] for row in position.board], position.red_to_move)
        clone.board[target[0]][target[1]] = piece
        clone.board[source[0]][source[1]] = "."
        if not is_in_check(clone, red):
            result.append(target)
    return result


def terminal_status(position: Position) -> str | None:
    """Return checkmate or stalemate for the side to move, if the game is over."""
    for row in range(10):
        for col in range(9):
            piece = position.board[row][col]
            if piece != "." and piece.isupper() == position.red_to_move and legal_moves(position, (row, col)):
                return None
    return "checkmate" if is_in_check(position, position.red_to_move) else "stalemate"


def validate_moves(fen: str, moves: list[str]) -> tuple[bool, str | None, int | None]:
    result = validate_history(fen, moves)
    if result.issue is None:
        return True, None, None
    return False, result.issue.message, result.issue.ply - 1


CN_NUMBERS = "一二三四五六七八九"
PIECE_NAMES = {"r": "車", "n": "马", "b": "象", "a": "士", "k": "将", "c": "炮", "p": "卒", "R": "車", "N": "马", "B": "相", "A": "仕", "K": "帅", "C": "炮", "P": "兵"}


def describe_uci(position: Position, move: str) -> str:
    """Render a legal-coordinate move in common Chinese notation."""
    source = (9 - int(move[1]), FILES.index(move[0]))
    target = (9 - int(move[3]), FILES.index(move[2]))
    piece = position.board[source[0]][source[1]]
    if piece == ".":
        return move
    red = piece.isupper()
    file_name = lambda col: CN_NUMBERS[8 - col] if red else str(col + 1)
    forward = target[0] < source[0] if red else target[0] > source[0]
    action = "平" if target[0] == source[0] else "进" if forward else "退"
    if target[0] == source[0]:
        destination = file_name(target[1])
    elif piece.lower() in {"r", "c", "p"}:
        distance = abs(target[0] - source[0])
        destination = CN_NUMBERS[distance - 1] if red else str(distance)
    else:
        destination = file_name(target[1])
    return f"{PIECE_NAMES[piece]}{file_name(source[1])}{action}{destination}"


def resolve_move_position(position: Position, move: str) -> str:
    """Resolve UCI or Chinese notation against legal moves in this position."""
    normalized = "".join(move.split()).replace("車", "车")
    if len(normalized) == 4 and normalized[0] in FILES and normalized[2] in FILES and normalized[1].isdigit() and normalized[3].isdigit():
        position.apply_uci(normalized)
        return normalized

    candidates: list[str] = []
    for row in range(10):
        for col in range(9):
            piece = position.board[row][col]
            if piece == "." or piece.isupper() != position.red_to_move:
                continue
            for target_row, target_col in legal_moves(position, (row, col)):
                uci = f"{FILES[col]}{9-row}{FILES[target_col]}{9-target_row}"
                if "".join(describe_uci(position, uci).split()).replace("車", "车") == normalized:
                    candidates.append(uci)
    if not candidates:
        raise ValueError(f"无法识别或不合法的着法：{move}。请检查当前行棋方，或改用 UCI 坐标（如 h2e2）")
    if len(candidates) > 1:
        raise ValueError(f"中文着法“{move}”有歧义（{', '.join(candidates)}），请改用 UCI 坐标")
    return candidates[0]


def resolve_move(fen: str, move: str) -> str:
    return resolve_move_position(Position.from_fen(fen), move)

