"""Transactional AI hall turn orchestration."""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .ai_friends import get_friend
from .engine import EngineQueueFull, EngineQueueTimeout, EngineRuleViolation, EngineUnavailable, PikafishEngine
from .engine_strength import profile_for, select_candidate
from .models import HallTurnResponse, TurnRequest
from .persistence import Game, GameMove, GameTurn, User
from .xiangqi import Position, describe_uci, history_result, validate_candidate, validate_history


class HallTurnError(RuntimeError):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass
class HallTurnOutcome:
    game: Game
    turn: GameTurn
    user_move: GameMove | None
    ai_move: GameMove | None


@dataclass
class _TurnLockEntry:
    lock: asyncio.Lock
    users: int = 0


_turn_locks: dict[tuple[str, str], _TurnLockEntry] = {}
_turn_locks_guard = asyncio.Lock()


def _fen(position: Position) -> str:
    rows: list[str] = []
    for row in position.board:
        output = ""
        empty = 0
        for piece in row:
            if piece == ".":
                empty += 1
            else:
                if empty:
                    output += str(empty)
                    empty = 0
                output += piece
        if empty:
            output += str(empty)
        rows.append(output)
    return "/".join(rows) + (" w" if position.red_to_move else " b") + " - - 0 1"


def _fingerprint(game_id: str, payload: TurnRequest) -> str:
    raw = json.dumps({"game_id": game_id, "expected_version": payload.expected_version, "user_uci": payload.user_uci}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _side(position: Position) -> str:
    return "red" if position.red_to_move else "black"


def _terminal_values(positions: list[Position], moves: list[str]) -> tuple[str, str] | None:
    return history_result(positions, moves)


def _set_terminal(game: Game, terminal: tuple[str, str], *, count_stats: bool) -> None:
    reason, result = terminal
    game.status = "finished"
    game.termination_reason = reason
    game.result = result
    game.finished_at = datetime.now(timezone.utc)
    game.counts_for_stats = count_stats


def _move_by_ply(game: Game, ply: int | None) -> GameMove | None:
    if ply is None:
        return None
    return next((move for move in game.moves if move.ply == ply), None)


def _existing_outcome(game: Game, turn: GameTurn) -> HallTurnOutcome:
    return HallTurnOutcome(game=game, turn=turn, user_move=_move_by_ply(game, turn.user_ply), ai_move=_move_by_ply(game, turn.ai_ply))


async def submit_turn(db: Session, user: User, game: Game, payload: TurnRequest, engine: PikafishEngine) -> HallTurnOutcome:
    key = (game.id, payload.turn_id)
    async with _turn_locks_guard:
        entry = _turn_locks.get(key)
        if entry is None:
            entry = _TurnLockEntry(asyncio.Lock())
            _turn_locks[key] = entry
        entry.users += 1
    try:
        async with entry.lock:
            db.expire_all()
            refreshed = db.scalar(select(Game).options(selectinload(Game.moves), selectinload(Game.turns)).where(Game.id == game.id, Game.user_id == user.id, Game.deleted_at.is_(None)))
            if refreshed is None:
                raise HallTurnError(404, "game_not_found", "棋局不存在")
            return await _submit_turn(db, user, refreshed, payload, engine)
    finally:
        async with _turn_locks_guard:
            entry.users -= 1
            if entry.users == 0:
                _turn_locks.pop(key, None)


async def _submit_turn(db: Session, user: User, game: Game, payload: TurnRequest, engine: PikafishEngine) -> HallTurnOutcome:
    if game.mode != "ai_hall":
        raise HallTurnError(409, "not_hall_game", "该棋局不是 AI 棋友对局")
    fingerprint = _fingerprint(game.id, payload)
    turn = db.scalar(select(GameTurn).where(GameTurn.game_id == game.id, GameTurn.turn_id == payload.turn_id))
    if turn is not None:
        if turn.request_fingerprint != fingerprint:
            raise HallTurnError(409, "turn_conflict", "该回合编号已对应其他着法")
        if turn.status == "completed":
            return _existing_outcome(game, turn)
        if game.status != "awaiting_ai":
            raise HallTurnError(409, "turn_state_invalid", "待处理回合状态与棋局不一致")
        initial_version = game.version
        moves = [item.uci for item in game.moves]
        history = validate_history(game.initial_fen, moves)
        if history.issue:
            raise HallTurnError(409, "game_history_invalid", history.issue.message)
        user_move = _move_by_ply(game, turn.user_ply)
    else:
        if game.status == "finished":
            raise HallTurnError(409, "game_finished", "棋局已经结束")
        if game.status == "awaiting_ai":
            raise HallTurnError(409, "ai_pending", "上一回合的 AI 应手尚未完成，请重试原回合")
        if game.version != payload.expected_version:
            raise HallTurnError(409, "stale_game", "棋局已被其他页面更新，请刷新后重试")
        moves = [item.uci for item in game.moves]
        history = validate_history(game.initial_fen, moves)
        if history.issue:
            raise HallTurnError(409, "game_history_invalid", history.issue.message)
        position = history.positions[-1]
        is_user_turn = _side(position) == game.user_side
        if is_user_turn and not payload.user_uci:
            raise HallTurnError(422, "user_move_required", "当前轮到用户走棋")
        if not is_user_turn and payload.user_uci:
            raise HallTurnError(422, "ai_turn_in_progress", "当前轮到 AI 走棋")
        user_move = None
        if payload.user_uci:
            next_history = validate_history(game.initial_fen, [*moves, payload.user_uci])
            if next_history.issue:
                code = "rule_violation" if next_history.issue.code in {"perpetual_check", "perpetual_chase"} else "invalid_move"
                raise HallTurnError(422, code, next_history.issue.message)
            before, after = next_history.positions[-2], next_history.positions[-1]
            user_move = GameMove(game_id=game.id, ply=len(moves) + 1, side=_side(before), uci=payload.user_uci, notation_zh=describe_uci(before, payload.user_uci), before_fen=_fen(before), after_fen=_fen(after))
            db.add(user_move)
            game.moves.append(user_move)
            moves.append(payload.user_uci)
            history = next_history
            game.current_fen = _fen(after)
            game.red_to_move = after.red_to_move
            game.version += 1
            terminal = _terminal_values(history.positions, moves)
            if terminal:
                _set_terminal(game, terminal, count_stats=game.origin == "cloud_formal")
                turn = GameTurn(turn_id=payload.turn_id, game_id=game.id, request_fingerprint=fingerprint, expected_version=payload.expected_version, user_uci=payload.user_uci, user_ply=user_move.ply, status="completed")
                db.add(turn)
                db.commit()
                db.expire(game, ["moves"])
                db.refresh(game)
                return HallTurnOutcome(game, turn, user_move, None)
        initial_version = game.version
        game.status = "awaiting_ai"
        turn = GameTurn(turn_id=payload.turn_id, game_id=game.id, request_fingerprint=fingerprint, expected_version=payload.expected_version, user_uci=payload.user_uci, user_ply=user_move.ply if user_move else None, status="ai_pending")
        db.add(turn)
        try:
            db.commit()
        except IntegrityError as exc:
            db.rollback()
            raise HallTurnError(409, "turn_in_progress", "该回合正在由其他请求处理，请重试同一回合编号") from exc
        db.expire(game, ["moves"])
        game = db.scalar(select(Game).options(selectinload(Game.moves)).where(Game.id == game.id))
        if game is None:
            raise HallTurnError(404, "game_not_found", "棋局不存在")
        turn = db.scalar(select(GameTurn).where(GameTurn.game_id == game.id, GameTurn.turn_id == payload.turn_id)) or turn
        moves = [item.uci for item in game.moves]
        history = validate_history(game.initial_fen, moves)

    if game.opponent_snapshot and game.opponent_snapshot.get("strength_profile"):
        try:
            profile = profile_for(str(game.opponent_snapshot["strength_profile"]))
        except ValueError as exc:
            raise HallTurnError(409, "opponent_snapshot_invalid", "棋友棋力快照无效，无法恢复对局") from exc
    else:
        try:
            profile = profile_for(get_friend(game.opponent_id or "").strength_profile)
        except (KeyError, ValueError) as exc:
            raise HallTurnError(409, "opponent_unavailable", "棋友配置不可用，无法恢复对局") from exc
    turn.attempt_count += 1
    db.commit()
    try:
        result = await engine.analyze(game.initial_fen, moves, profile.depth, profile.movetime_ms, profile.max_rank, profile.threads, profile.hash_mb)
        selected = select_candidate(result.lines, profile, f"{game.id}:{len(moves)}", allow_suboptimal=True)
        candidate = selected.line.move
        checked = validate_candidate(history.positions[-1], candidate, history.positions, moves)
        if checked.issue:
            raise EngineRuleViolation(checked.issue.message, result.filter_summary)
    except (EngineRuleViolation, EngineUnavailable, ValueError) as exc:
        error_code = getattr(exc, "code", "engine_unavailable")
        turn.error_code = error_code
        db.commit()
        if isinstance(exc, EngineQueueFull):
            raise HallTurnError(429, error_code, "引擎请求较多，请稍后重试同一回合") from exc
        if isinstance(exc, EngineQueueTimeout):
            raise HallTurnError(503, error_code, "引擎排队超时，请重试同一回合") from exc
        raise HallTurnError(503, "ai_pending", "AI 应手暂时不可用，请重试同一回合") from exc

    current_game = db.scalar(select(Game).options(selectinload(Game.moves)).where(Game.id == game.id))
    current_turn = db.scalar(select(GameTurn).where(GameTurn.game_id == game.id, GameTurn.turn_id == payload.turn_id))
    if current_game is None or current_turn is None:
        raise HallTurnError(404, "game_not_found", "棋局或回合不存在")
    if current_turn.status == "completed":
        return _existing_outcome(current_game, current_turn)
    if current_game.status != "awaiting_ai":
        raise HallTurnError(409, "turn_state_invalid", "待处理回合状态已改变")
    ai_history = validate_history(current_game.initial_fen, [item.uci for item in current_game.moves])
    if ai_history.issue:
        raise HallTurnError(409, "game_history_invalid", ai_history.issue.message)
    before, after = ai_history.positions[-1], checked.position
    if after is None:
        raise HallTurnError(503, "ai_pending", "AI 着法无法生成有效局面")
    ai_move = GameMove(game_id=current_game.id, ply=len(current_game.moves) + 1, side=_side(before), uci=candidate, notation_zh=describe_uci(before, candidate), before_fen=_fen(before), after_fen=_fen(after))
    current_game.moves.append(ai_move)
    db.add(ai_move)
    current_game.current_fen = _fen(after)
    current_game.red_to_move = after.red_to_move
    current_game.version += 1
    terminal = _terminal_values([*ai_history.positions, after], [item.uci for item in current_game.moves])
    if terminal:
        _set_terminal(current_game, terminal, count_stats=current_game.origin == "cloud_formal")
    else:
        current_game.status = "active"
    current_turn.ai_uci = candidate
    current_turn.ai_ply = ai_move.ply
    current_turn.status = "completed"
    current_turn.error_code = None
    db.commit()
    db.expire(current_game, ["moves"])
    db.refresh(current_game)
    return HallTurnOutcome(current_game, current_turn, _move_by_ply(current_game, current_turn.user_ply), ai_move)
