from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import os
from pathlib import Path
import time
import uuid
from urllib.parse import urlencode
import zipfile

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse, Response
from starlette.requests import Request
from starlette.middleware.sessions import SessionMiddleware

from .logging_config import REQUEST_ID_HEADER, configure_logging, get_logger, request_id_context

from .engine import EngineQueueFull, EngineQueueTimeout, EngineRuleViolation, EngineUnavailable, PikafishEngine
from .engine_strength import profile_for, select_candidate
from .ai_friends import AiFriend, get_friend, load_catalog, random_friend, recommend_friend, snapshot as friend_snapshot
from .llm import LLMUnavailable, VisionRecognitionError, coach_chat, explain, recognize_board_image
from .models import AiFriendSummary, AiFriendsResponse, MatchRequest, MatchResponse, RandomMatchRequest, HallGameCreateRequest, TurnRequest, ResignRequest, HallTurnResponse, GameResultResponse, GameStatsResponse, CoachRequest, CoachResponse, DataRequestResponse, EmailAddressRequest, EmailLoginRequest, EmailRegisterRequest, EmailTokenRequest, PasswordResetRequest, PrivacyConsentRequest, EngineRequest, EngineMoveRequest, EngineMoveResponse, EngineResponse, GameCreateRequest, LegacyGameImportRequest, GameMoveResponse, GameResponse, GameUpdateRequest, GameEventsUpdateRequest, MoveCreateRequest, OpeningsResponse, PersistedReviewResponse, PlanAnalysisRequest, PlanAnalysisResponse, PlanExplanation, PlanMoveEvaluation, ReviewRequest, ReviewResponse, SavedEngineSettings, SetupImageResponse, ValidationResponse
from .auth import get_current_user, get_consented_user, get_deletion_user, login_email, oidc_configured, register_email, normalize_email, password_hasher, log_auth_event
from .email_flow import consume_token, email_verification_required, request_action, revoke_tokens
from .privacy import has_consent, policy_version, publication_missing, record_consent, validate_publication_configuration
from .database import assert_database_migrated, get_db, init_database
from .persistence import DataRequest, DeletionTombstone, Game, GameMove, GameTurn, LocalCredential, PrivacyConsent, Review, ReviewItem, User, UserIdentity
from .deletion_ledger import export_artifact_path, purge_expired_deletions, purge_expired_exports
from .openings import lookup_openings
from .review import review_game
from .game_hall import HallTurnError, submit_turn
from .xiangqi import Position, START_FEN, describe_uci, history_result, resolve_move_position, terminal_result, terminal_status, validate_candidate, validate_fen, validate_history, validate_moves
from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload
from . import oidc

configure_logging()
logger = get_logger(__name__)
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

engine = PikafishEngine()


def _api_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _value_error_code(message: str, fallback: str) -> str:
    if "FEN" in message:
        return "invalid_fen"
    if "线程数" in message:
        return "invalid_parameter"
    return fallback


def _normalized_engine_settings(settings: SavedEngineSettings | None) -> SavedEngineSettings:
    settings = settings or SavedEngineSettings()
    if settings.difficulty == "custom":
        return settings
    profile = profile_for(settings.difficulty)
    return SavedEngineSettings(
        difficulty=settings.difficulty,
        allow_suboptimal=settings.allow_suboptimal,
        depth=profile.depth,
        movetime_ms=profile.movetime_ms,
        threads=profile.threads,
        hash_mb=profile.hash_mb,
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_publication_configuration()
    if os.getenv("APP_ENV", "development").lower() == "production":
        assert_database_migrated()
    else:
        init_database()
    purge_expired_deletions()
    purge_expired_exports()
    logger.info("application_startup", extra={"event": "application_startup"})
    await engine.start()
    logger.info(
        "engine_ready",
        extra={"event": "engine_ready", "ready": engine.ready},
    )
    yield
    logger.info("application_shutdown", extra={"event": "application_shutdown"})
    await engine.stop()


app = FastAPI(title="Pikafish Xiangqi Lab", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "development-only-change-me"), https_only=os.getenv("COOKIE_SECURE", "0") == "1", same_site="lax", max_age=60 * 60 * 24 * 7)


@app.exception_handler(Exception)
async def unhandled_exception_response(request: Request, _: Exception) -> Response:
    """Keep unhandled errors generic while retaining request correlation."""
    return Response(
        content="Internal Server Error",
        status_code=500,
        media_type="text/plain",
        headers={REQUEST_ID_HEADER: getattr(request.state, "request_id", "-")},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_response(request: Request, exc: RequestValidationError) -> Response:
    auth_action = {"/auth/email/register": "register", "/auth/email/login": "login"}.get(request.url.path)
    if auth_action:
        # FastAPI already consumed the request stream during validation. With
        # BaseHTTPMiddleware, rereading it here can wait forever on disconnect.
        body = exc.body
        email = body.get("email", "") if isinstance(body, dict) else ""
        log_auth_event(auth_action, str(email), outcome="failure", status=422, reason_code="invalid_request")
    return await request_validation_exception_handler(request, exc)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    supplied = request.headers.get(REQUEST_ID_HEADER, "")
    request_id = supplied if _REQUEST_ID_RE.fullmatch(supplied) else str(uuid.uuid4())
    request.state.request_id = request_id
    token = request_id_context.set(request_id)
    started = time.perf_counter()
    route = request.scope.get("route")
    route_template = getattr(route, "path", None) or "<unmatched-route>"
    logger.info("request_started", extra={"event": "request_started", "method": request.method, "route": route_template})
    try:
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        route = request.scope.get("route")
        route_template = getattr(route, "path", None) or "<unmatched-route>"
        response.headers[REQUEST_ID_HEADER] = request_id
        if request.url.path.startswith("/auth/") or request.url.path in {"/api/me", "/api/auth/methods"}:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
            response.headers["Pragma"] = "no-cache"
        logger.info(
            "request_completed",
            extra={
                "event": "request_completed",
                "method": request.method,
                "route": route_template,
                "status": response.status_code,
                "duration_ms": round(elapsed_ms, 2),
            },
        )
        return response
    except Exception as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        route = request.scope.get("route")
        route_template = getattr(route, "path", None) or "<unmatched-route>"
        traceback = exc.__traceback__
        stack_locations = []
        while traceback is not None:
            frame = traceback.tb_frame
            stack_locations.append(
                f"{frame.f_code.co_filename}:{traceback.tb_lineno}:{frame.f_code.co_name}"
            )
            traceback = traceback.tb_next
        logger.error(
            "request_failed",
            extra={
                "event": "request_failed",
                "method": request.method,
                "route": route_template,
                "status": 500,
                "duration_ms": round(elapsed_ms, 2),
                "exception_type": type(exc).__name__,
                "stack_locations": "|".join(stack_locations),
            },
        )
        raise
    finally:
        request_id_context.reset(token)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:1239", "http://localhost:1239"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def _position_to_fen(position: Position) -> str:
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


def _same_position_as_fen(position: Position, fen: str) -> bool:
    try:
        cached = validate_fen(fen)
    except ValueError:
        return False
    return cached.board == position.board and cached.red_to_move == position.red_to_move


def _validate_game_projection(game: Game, history) -> None:
    if history.issue:
        raise _api_error(409, "game_history_invalid", f"已保存棋谱第 {history.issue.ply} 步无效: {history.issue.message}")
    if len(history.positions) != len(game.moves) + 1:
        raise _api_error(409, "game_projection_mismatch", "棋谱与当前棋局缓存不一致，请修复或重新导入棋局")
    for index, move in enumerate(game.moves):
        before, after = history.positions[index], history.positions[index + 1]
        expected_side = "red" if before.red_to_move else "black"
        if (
            move.ply != index + 1
            or move.side != expected_side
            or not _same_position_as_fen(before, move.before_fen)
            or not _same_position_as_fen(after, move.after_fen)
            or move.notation_zh != describe_uci(before, move.uci)
        ):
            raise _api_error(409, "game_projection_mismatch", "棋谱快照与规则重放结果不一致，请修复或重新导入棋局")
    final = history.positions[-1]
    rule_result = history_result(history.positions, [move.uci for move in game.moves])
    expected_status = "finished" if rule_result else "active"
    awaiting_ai = game.status == "awaiting_ai" and expected_status == "active" and any(turn.status == "ai_pending" for turn in game.turns)
    if not _same_position_as_fen(final, game.current_fen) or final.red_to_move != game.red_to_move or (game.status != expected_status and not awaiting_ai):
        raise _api_error(409, "game_projection_mismatch", "当前局面与规则重放结果不一致，请修复或重新导入棋局")
    _validate_game_events(game.initial_fen, game.events or [])


def _validate_game_events(initial_fen: str, events: list[dict]) -> None:
    for event in events:
        if not isinstance(event, dict) or event.get("type") not in {"undo", "hint"}:
            raise _api_error(422, "invalid_game_event", "操作记录类型无效")
        event_id = event.get("id")
        created_at = event.get("createdAt")
        try:
            datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            raise _api_error(422, "invalid_game_event", "操作记录时间无效")
        if not isinstance(event_id, str) or not event_id or len(event_id) > 100:
            raise _api_error(422, "invalid_game_event", "操作记录编号无效")
        moves = event.get("positionMoves")
        position_fen = event.get("positionFen")
        if not isinstance(moves, list) or len(moves) > 400 or not all(isinstance(move, str) for move in moves) or not isinstance(position_fen, str) or len(position_fen) > 220:
            raise _api_error(422, "invalid_game_event", "操作记录局面格式无效")
        history = validate_history(initial_fen, moves)
        if history.issue or len(history.positions) != len(moves) + 1 or not _same_position_as_fen(history.positions[-1], position_fen):
            raise _api_error(422, "invalid_game_event", "操作记录局面无法从起始局面重建")
        if event.get("ply") != len(moves) + 1:
            raise _api_error(422, "invalid_game_event", "操作记录回合号无效")
        if event["type"] == "undo":
            undone = event.get("undoneMoves")
            if not isinstance(undone, list) or not undone or len(undone) > 400 or not all(isinstance(move, str) for move in undone):
                raise _api_error(422, "invalid_game_event", "悔棋记录缺少撤回走法")
            combined = validate_history(initial_fen, [*moves, *undone])
            if combined.issue:
                raise _api_error(422, "invalid_game_event", "悔棋记录中的撤回走法无效")
        else:
            candidates = event.get("candidates")
            if not isinstance(candidates, list) or not candidates or len(candidates) > 5:
                raise _api_error(422, "invalid_game_event", "提示记录缺少候选着法")
            for candidate in candidates:
                if not isinstance(candidate, dict) or not isinstance(candidate.get("move"), str) or not isinstance(candidate.get("label"), str) or len(candidate["label"]) > 100:
                    raise _api_error(422, "invalid_game_event", "提示候选着法格式无效")
                score = candidate.get("score")
                if score is not None and (not isinstance(score, dict) or score.get("type") not in {"cp", "mate"} or not isinstance(score.get("value"), int)):
                    raise _api_error(422, "invalid_game_event", "提示候选分值格式无效")
                checked = validate_candidate(history.positions[-1], candidate["move"], history.positions, moves)
                if checked.issue:
                    raise _api_error(422, "invalid_game_event", "提示记录包含不合法着法")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _game_response(game: Game) -> GameResponse:
    pending_turn = next((turn for turn in game.turns if turn.status == "ai_pending"), None)
    return GameResponse(
        id=game.id,
        name=game.name,
        initial_fen=game.initial_fen,
        current_fen=game.current_fen,
        red_to_move=game.red_to_move,
        status=game.status,
        version=game.version,
        created_at=game.created_at.isoformat(),
        updated_at=game.updated_at.isoformat(),
        engine_settings=_normalized_engine_settings(SavedEngineSettings.model_validate(game.engine_settings or {})),
        moves=[GameMoveResponse(ply=m.ply, side=m.side, uci=m.uci, notation_zh=m.notation_zh, before_fen=m.before_fen, after_fen=m.after_fen) for m in game.moves],
        events=game.events or [],
        mode=game.mode or "legacy",
        user_side=game.user_side,
        opponent_id=game.opponent_id,
        opponent_config_version=game.opponent_config_version,
        opponent_snapshot=game.opponent_snapshot,
        result=game.result,
        termination_reason=game.termination_reason,
        finished_at=_iso(game.finished_at),
        origin=game.origin or "legacy",
        counts_for_stats=bool(game.counts_for_stats),
        pending_turn_id=pending_turn.turn_id if pending_turn else None,
        pending_turn_expected_version=pending_turn.expected_version if pending_turn else None,
        pending_turn_user_uci=pending_turn.user_uci if pending_turn else None,
    )


def _friend_summary(friend: AiFriend) -> AiFriendSummary:
    return AiFriendSummary(
        bot_id=friend.bot_id,
        name=friend.name,
        avatar_key=friend.avatar_key,
        description=friend.description,
        category=friend.category,
        style=list(friend.style),
        personality=list(friend.personality),
        strength_profile=friend.strength_profile,
        config_version=friend.config_version,
        experiences=list(friend.experiences),
        enabled=friend.enabled,
        is_ai=True,
    )


def _owned_game(db: Session, user: User, game_id: str) -> Game:
    game = db.scalar(select(Game).options(selectinload(Game.moves)).where(Game.id == game_id, Game.user_id == user.id))
    if game is None:
        raise _api_error(404, "game_not_found", "棋局不存在")
    if user.status != "active" or game.deleted_at:
        raise _api_error(410, "account_unavailable", "账号或棋局不可用")
    return game


@app.get("/api/me")
async def me(user: User = Depends(get_deletion_user), db: Session = Depends(get_db)) -> dict:
    return {"id": user.id, "display_name": user.display_name, "status": user.status, "privacy_accepted": has_consent(db, user.id), "policy_version": policy_version()}


@app.get("/api/privacy/config")
async def privacy_config() -> dict:
    return {"policy_version": policy_version(), "effective_date": os.getenv("PRIVACY_EFFECTIVE_DATE", "").strip(), "operator_name": os.getenv("PRIVACY_OPERATOR_NAME", "").strip(), "contact_email": os.getenv("PRIVACY_CONTACT_EMAIL", "").strip(), "third_party_disclosure": os.getenv("PRIVACY_THIRD_PARTY_DISCLOSURE", "").strip(), "backup_storage_description": os.getenv("PRIVACY_BACKUP_STORAGE_DESCRIPTION", "").strip(), "ready_for_publication": not publication_missing()}


@app.post("/api/me/privacy-consent")
async def accept_privacy(payload: PrivacyConsentRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    record_consent(db, user, payload.policy_version)
    db.commit()
    return {"policy_version": policy_version(), "accepted": True}


@app.get("/api/auth/methods")
async def auth_methods() -> dict:
    return {"email": True, "oidc": oidc_configured(), "email_verification_required": email_verification_required()}


@app.post("/auth/email/register", status_code=201)
async def email_register(payload: EmailRegisterRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    try:
        user = register_email(request, db, payload.email, payload.password, payload.display_name, payload.policy_version)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        log_auth_event("register", payload.email, outcome="failure", status=exc.status_code,
                       reason_code=str(detail.get("code", "request_failed")))
        raise
    except Exception:
        log_auth_event("register", payload.email, outcome="failure", status=500, reason_code="internal_error")
        raise
    verification_required = email_verification_required()
    log_auth_event("register", payload.email, outcome="success", status=201, user_id=user.id)
    return {"user": {"id": user.id, "display_name": user.display_name, "status": user.status}, "email_verified": not verification_required, "verification_required": verification_required}


@app.post("/auth/email/login")
async def email_login(payload: EmailLoginRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    try:
        user = login_email(request, db, payload.email, payload.password)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        log_auth_event("login", payload.email, outcome="failure", status=exc.status_code,
                       reason_code=str(detail.get("code", "request_failed")))
        raise
    except Exception:
        log_auth_event("login", payload.email, outcome="failure", status=500, reason_code="internal_error")
        raise
    log_auth_event("login", payload.email, outcome="success", status=200, user_id=user.id)
    return {"user": {"id": user.id, "display_name": user.display_name, "status": user.status}}


@app.post("/auth/email/verification/request")
async def email_verification_request(payload: EmailAddressRequest, db: Session = Depends(get_db)) -> dict:
    request_action(db, normalize_email(payload.email), "verify")
    return {"ok": True}


@app.post("/auth/email/verify")
async def email_verify(payload: EmailTokenRequest, db: Session = Depends(get_db)) -> dict:
    credential = consume_token(db, payload.token, "verify")
    credential.email_verified = True
    revoke_tokens(db, credential.user_id, "verify")
    db.commit()
    return {"ok": True}


@app.post("/auth/email/password/forgot")
async def email_password_forgot(payload: EmailAddressRequest, db: Session = Depends(get_db)) -> dict:
    request_action(db, normalize_email(payload.email), "reset")
    return {"ok": True}


@app.post("/auth/email/password/reset")
async def email_password_reset(payload: PasswordResetRequest, db: Session = Depends(get_db)) -> dict:
    credential = consume_token(db, payload.token, "reset")
    credential.password_hash = password_hasher.hash(payload.password)
    credential.email_verified = True
    credential.failed_attempts = 0
    credential.locked_until = None
    user = db.get(User, credential.user_id)
    user.session_version += 1
    revoke_tokens(db, credential.user_id, "reset")
    db.commit()
    return {"ok": True}


@app.get("/auth/oidc/start")
async def oidc_start(request: Request):
    return await oidc.start(request)


@app.get("/auth/oidc/callback")
async def oidc_callback(request: Request):
    try:
        profile = await oidc.callback(request)
    except HTTPException as exc:
        log_auth_event("login", "", outcome="failure", status=exc.status_code,
                       reason_code="oidc_callback_failed", auth_method="oidc")
        raise
    db = next(get_db())
    try:
        identity = db.scalar(select(UserIdentity).where(UserIdentity.issuer == profile["issuer"], UserIdentity.subject == profile["subject"]))
        action = "login"
        if identity is None:
            action = "register"
            user = User(display_name=profile.get("display_name"), avatar_url=profile.get("avatar_url"))
            db.add(user)
            db.flush()
            identity = UserIdentity(user_id=user.id, issuer=profile["issuer"], subject=profile["subject"], email=profile.get("email"), email_verified=bool(profile.get("email_verified")))
            db.add(identity)
        else:
            user = db.get(User, identity.user_id)
            identity.email = profile.get("email")
            identity.email_verified = bool(profile.get("email_verified"))
            identity.last_login_at = datetime.now(timezone.utc)
        db.commit()
        request.session.clear()
        request.session["user_id"] = user.id
        request.session["session_version"] = user.session_version
        log_auth_event(action, str(profile.get("email") or ""), outcome="success", status=302,
                       user_id=user.id, auth_method="oidc")
    finally:
        db.close()
    return RedirectResponse(url=os.getenv("OIDC_SUCCESS_REDIRECT", "http://127.0.0.1:1239/"))


@app.post("/auth/logout")
async def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


@app.get("/api/ai-friends", response_model=AiFriendsResponse)
async def ai_friends(experience: str | None = None) -> AiFriendsResponse:
    if experience is not None and experience not in {"casual", "practice", "challenge"}:
        raise _api_error(400, "invalid_experience", "未知的推荐体验")
    catalog = load_catalog()
    friends = [friend for friend in catalog.friends if friend.enabled and (experience is None or experience in friend.experiences)]
    return AiFriendsResponse(
        catalog_version=catalog.catalog_version,
        friends=[_friend_summary(friend) for friend in friends],
        recommended_ids=[friend.bot_id for friend in friends if "practice" in friend.experiences],
    )


@app.post("/api/matches/recommend", response_model=MatchResponse, status_code=201)
async def recommend_match(payload: MatchRequest) -> MatchResponse:
    try:
        friend = recommend_friend(payload.experience)
    except ValueError as exc:
        raise _api_error(400, "invalid_experience", str(exc)) from exc
    catalog = load_catalog()
    return MatchResponse(match_type="recommend", experience=payload.experience, opponent=_friend_summary(friend), catalog_version=catalog.catalog_version)


@app.post("/api/matches/random", response_model=MatchResponse, status_code=201)
async def random_match(payload: RandomMatchRequest) -> MatchResponse:
    friend = random_friend(set(payload.exclude_opponent_ids))
    catalog = load_catalog()
    return MatchResponse(match_type="random", opponent=_friend_summary(friend), catalog_version=catalog.catalog_version)


# Keep archive replay in FastAPI's worker pool so it cannot block live turns.
@app.get("/api/games", response_model=list[GameResponse])
def list_games(user: User = Depends(get_consented_user), db: Session = Depends(get_db)) -> list[GameResponse]:
    games = db.scalars(select(Game).options(selectinload(Game.moves)).where(Game.user_id == user.id, Game.deleted_at.is_(None)).order_by(Game.updated_at.desc())).all()
    for game in games:
        _validate_game_projection(game, validate_history(game.initial_fen, [move.uci for move in game.moves]))
    return [_game_response(game) for game in games]


@app.post("/api/games", response_model=GameResponse, status_code=201)
async def create_game(payload: GameCreateRequest, user: User = Depends(get_consented_user), db: Session = Depends(get_db)) -> GameResponse:
    if user.status != "active":
        raise _api_error(410, "account_unavailable", "账号正在删除或已删除")
    try:
        position = validate_fen(payload.initial_fen)
    except ValueError as exc:
        raise _api_error(400, "invalid_fen", str(exc)) from exc
    _validate_game_events(payload.initial_fen.strip(), payload.events)
    game = Game(user_id=user.id, name=payload.name, initial_fen=payload.initial_fen.strip(), current_fen=_position_to_fen(position), red_to_move=position.red_to_move, status="finished" if terminal_status(position) else "active", engine_settings=_normalized_engine_settings(payload.engine_settings).model_dump(), events=payload.events)
    db.add(game)
    db.commit()
    db.refresh(game)
    return _game_response(game)


@app.post("/api/hall/games", response_model=GameResponse, status_code=201)
async def create_hall_game(payload: HallGameCreateRequest, user: User = Depends(get_consented_user), db: Session = Depends(get_db)) -> GameResponse:
    if user.status != "active":
        raise _api_error(410, "account_unavailable", "账号正在删除或已删除")
    try:
        friend = get_friend(payload.opponent_id)
    except KeyError as exc:
        raise _api_error(404, "ai_friend_not_found", "AI 棋友不存在或已停用") from exc
    position = Position.from_fen(START_FEN)
    game = Game(
        user_id=user.id,
        name=payload.name or friend.name,
        initial_fen=START_FEN,
        current_fen=START_FEN,
        red_to_move=True,
        status="active",
        mode="ai_hall",
        user_side=payload.user_side,
        opponent_id=friend.bot_id,
        opponent_config_version=friend.config_version,
        opponent_snapshot=friend_snapshot(friend),
        origin="cloud_formal",
        counts_for_stats=False,
        engine_settings=_normalized_engine_settings(SavedEngineSettings(difficulty=friend.strength_profile)).model_dump(),
        events=[],
    )
    if terminal_result(position):
        raise _api_error(409, "invalid_start_position", "标准起始局面不能是终局")
    db.add(game)
    db.commit()
    db.refresh(game)
    return _game_response(game)


@app.post("/api/games/import", response_model=GameResponse, status_code=201)
def import_legacy_game(payload: LegacyGameImportRequest, response: Response, user: User = Depends(get_consented_user), db: Session = Depends(get_db)) -> GameResponse:
    if user.status != "active":
        raise _api_error(410, "account_unavailable", "账号正在删除或已删除")
    try:
        history = validate_history(payload.initial_fen, payload.moves)
    except ValueError as exc:
        raise _api_error(400, "invalid_fen", str(exc)) from exc
    if history.issue:
        code = "rule_violation" if history.issue.code in {"perpetual_check", "perpetual_chase"} else "invalid_move_history"
        raise _api_error(422, code, f"第 {history.issue.ply} 步无效: {history.issue.message}")
    _validate_game_events(payload.initial_fen.strip(), payload.events)
    opponent_snapshot = None
    if payload.mode == "ai_hall":
        if not payload.user_side or not payload.opponent_id or not payload.opponent_snapshot:
            raise _api_error(400, "invalid_guest_game", "导入 AI 棋友局需要执棋方和机器人快照")
        try:
            opponent_snapshot = AiFriendSummary.model_validate(payload.opponent_snapshot)
        except Exception as exc:
            raise _api_error(400, "invalid_guest_game", "机器人快照格式无效") from exc
        if opponent_snapshot.bot_id != payload.opponent_id or opponent_snapshot.is_ai is not True:
            raise _api_error(400, "invalid_guest_game", "机器人身份与快照不一致")

    existing = db.scalar(select(Game).options(selectinload(Game.moves)).where(Game.user_id == user.id, Game.legacy_id == payload.legacy_id))
    if existing:
        same_history = existing.initial_fen.strip() == payload.initial_fen.strip() and [move.uci for move in existing.moves] == payload.moves
        if not same_history:
            raise _api_error(409, "legacy_game_conflict", "该本地棋局编号已导入为其他棋谱")
        _validate_game_projection(existing, validate_history(existing.initial_fen, [move.uci for move in existing.moves]))
        response.status_code = 200
        return _game_response(existing)

    final = history.positions[-1]
    terminal = history_result(history.positions, payload.moves) if payload.mode == "ai_hall" else None
    game = Game(
        user_id=user.id,
        legacy_id=payload.legacy_id,
        name=payload.name,
        initial_fen=payload.initial_fen.strip(),
        current_fen=_position_to_fen(final),
        red_to_move=final.red_to_move,
        status="finished" if (terminal or terminal_status(final)) else "active",
        version=len(payload.moves),
        engine_settings=_normalized_engine_settings(payload.engine_settings).model_dump(),
        events=payload.events,
        mode=payload.mode,
        user_side=payload.user_side,
        opponent_id=payload.opponent_id,
        opponent_config_version=opponent_snapshot.config_version if opponent_snapshot else None,
        opponent_snapshot=opponent_snapshot.model_dump() if opponent_snapshot else None,
        result=terminal[1] if terminal else None,
        termination_reason=terminal[0] if terminal else None,
        finished_at=datetime.now(timezone.utc) if terminal else None,
        origin="guest_import",
        counts_for_stats=False,
    )
    db.add(game)
    db.flush()
    for index, move in enumerate(payload.moves):
        before, after = history.positions[index], history.positions[index + 1]
        db.add(GameMove(
            game_id=game.id,
            ply=index + 1,
            side="red" if before.red_to_move else "black",
            uci=move,
            notation_zh=describe_uci(before, move),
            before_fen=_position_to_fen(before),
            after_fen=_position_to_fen(after),
        ))
    db.commit()
    db.refresh(game)
    return _game_response(_owned_game(db, user, game.id))


@app.get("/api/games/{game_id}", response_model=GameResponse)
def get_game(game_id: str, user: User = Depends(get_consented_user), db: Session = Depends(get_db)) -> GameResponse:
    game = _owned_game(db, user, game_id)
    _validate_game_projection(game, validate_history(game.initial_fen, [move.uci for move in game.moves]))
    return _game_response(game)


@app.patch("/api/games/{game_id}", response_model=GameResponse)
async def update_game(game_id: str, payload: GameUpdateRequest, user: User = Depends(get_consented_user), db: Session = Depends(get_db)) -> GameResponse:
    game = _owned_game(db, user, game_id)
    if game.version != payload.expected_version:
        raise _api_error(409, "stale_game", "棋局已被其他页面更新，请刷新后重试")
    game.name = payload.name
    game.version += 1
    db.commit()
    db.refresh(game)
    return _game_response(game)


@app.patch("/api/games/{game_id}/events", response_model=GameResponse)
def update_game_events(game_id: str, payload: GameEventsUpdateRequest, user: User = Depends(get_consented_user), db: Session = Depends(get_db)) -> GameResponse:
    game = _owned_game(db, user, game_id)
    if game.version != payload.expected_version:
        raise _api_error(409, "stale_game", "棋局已被其他页面更新，请刷新后重试")
    _validate_game_events(game.initial_fen, payload.events)
    known = {event["id"]: event for event in game.events or []}
    for event in payload.events:
        previous = known.get(event["id"])
        if previous is not None and previous != event:
            raise _api_error(409, "game_event_conflict", "操作记录编号已对应其他内容")
        known[event["id"]] = event
    game.events = sorted(known.values(), key=lambda event: event["createdAt"])
    db.commit()
    db.refresh(game)
    return _game_response(game)


@app.post("/api/games/{game_id}/moves", response_model=GameResponse, status_code=201)
async def append_move(game_id: str, payload: MoveCreateRequest, user: User = Depends(get_consented_user), db: Session = Depends(get_db)) -> GameResponse:
    game = _owned_game(db, user, game_id)
    if game.version != payload.expected_version:
        raise _api_error(409, "stale_game", "棋局已被其他页面更新，请刷新后重试")
    if game.status == "finished":
        raise _api_error(409, "game_finished", "棋局已经结束，不能继续落子")
    moves = [move.uci for move in game.moves]
    current_history = validate_history(game.initial_fen, moves)
    _validate_game_projection(game, current_history)
    history = validate_history(game.initial_fen, [*moves, payload.uci])
    if history.issue:
        code = "rule_violation" if history.issue.code in {"perpetual_check", "perpetual_chase"} else "invalid_move"
        raise _api_error(422, code, f"第 {history.issue.ply} 步无效: {history.issue.message}")
    before = current_history.positions[-1]
    after = history.positions[-1]
    before_fen = _position_to_fen(before)
    after_fen = _position_to_fen(after)
    move = GameMove(game_id=game.id, ply=len(game.moves) + 1, side="red" if before.red_to_move else "black", uci=payload.uci, notation_zh=describe_uci(before, payload.uci), before_fen=before_fen, after_fen=after_fen)
    terminal = history_result(history.positions, [*moves, payload.uci])
    values = {
        "current_fen": after_fen,
        "red_to_move": after.red_to_move,
        "status": "finished" if terminal else "active",
        "version": payload.expected_version + 1,
        "updated_at": datetime.now(timezone.utc),
    }
    if payload.engine_settings is not None:
        values["engine_settings"] = _normalized_engine_settings(payload.engine_settings).model_dump()
    if terminal and game.mode == "ai_hall":
        values["result"] = terminal[1]
        values["termination_reason"] = terminal[0]
        values["finished_at"] = datetime.now(timezone.utc)
        values["counts_for_stats"] = game.origin == "cloud_formal"
    changed = db.execute(
        update(Game)
        .where(Game.id == game.id, Game.user_id == user.id, Game.version == payload.expected_version, Game.deleted_at.is_(None))
        .values(**values)
        .execution_options(synchronize_session=False)
    ).rowcount
    if changed != 1:
        db.rollback()
        raise _api_error(409, "stale_game", "棋局已被其他页面更新，请刷新后重试")
    db.add(move)
    db.commit()
    db.expire_all()
    return _game_response(_owned_game(db, user, game.id))


@app.post("/api/games/{game_id}/turns", response_model=HallTurnResponse)
async def hall_turn(game_id: str, payload: TurnRequest, user: User = Depends(get_consented_user), db: Session = Depends(get_db)) -> HallTurnResponse:
    game = _owned_game(db, user, game_id)
    try:
        result = await submit_turn(db, user, game, payload, engine)
    except HallTurnError as exc:
        raise _api_error(exc.status, exc.code, str(exc)) from exc
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="AI 回合处理失败，请重试同一回合编号") from exc
    return HallTurnResponse(
        turn_id=result.turn.turn_id,
        turn_status=result.turn.status,
        game=_game_response(result.game),
        user_move=GameMoveResponse(ply=result.user_move.ply, side=result.user_move.side, uci=result.user_move.uci, notation_zh=result.user_move.notation_zh, before_fen=result.user_move.before_fen, after_fen=result.user_move.after_fen) if result.user_move else None,
        ai_move=GameMoveResponse(ply=result.ai_move.ply, side=result.ai_move.side, uci=result.ai_move.uci, notation_zh=result.ai_move.notation_zh, before_fen=result.ai_move.before_fen, after_fen=result.ai_move.after_fen) if result.ai_move else None,
    )


@app.post("/api/games/{game_id}/resign", response_model=GameResponse)
async def resign_game(game_id: str, payload: ResignRequest, user: User = Depends(get_consented_user), db: Session = Depends(get_db)) -> GameResponse:
    game = _owned_game(db, user, game_id)
    request_turn_id = f"resign:{payload.request_id}"
    fingerprint = hashlib.sha256(f"resign:{game_id}:{payload.expected_version}".encode()).hexdigest()
    previous = db.scalar(select(GameTurn).where(GameTurn.game_id == game.id, GameTurn.turn_id == request_turn_id))
    if previous is not None:
        if previous.request_fingerprint != fingerprint:
            raise _api_error(409, "turn_conflict", "认输请求编号已对应其他棋局版本")
        return _game_response(game)
    if game.mode != "ai_hall" or game.status != "active":
        raise _api_error(409, "game_not_resignable", "当前棋局不能认输")
    if game.version != payload.expected_version:
        raise _api_error(409, "stale_game", "棋局已被其他页面更新，请刷新后重试")
    winner = "black_win" if game.user_side == "red" else "red_win"
    game.status = "finished"
    game.result = winner
    game.termination_reason = "resignation"
    game.finished_at = datetime.now(timezone.utc)
    game.counts_for_stats = game.origin == "cloud_formal"
    game.version += 1
    db.add(GameTurn(turn_id=request_turn_id, game_id=game.id, request_fingerprint=fingerprint, expected_version=payload.expected_version, status="completed"))
    db.commit()
    db.refresh(game)
    return _game_response(game)


@app.get("/api/games/{game_id}/result", response_model=GameResultResponse)
async def game_result(game_id: str, user: User = Depends(get_consented_user), db: Session = Depends(get_db)) -> GameResultResponse:
    game = _owned_game(db, user, game_id)
    if game.status != "finished" or game.result is None or game.termination_reason is None or game.finished_at is None:
        raise _api_error(409, "game_not_finished", "棋局尚未产生正式结果")
    opponent = AiFriendSummary.model_validate(game.opponent_snapshot) if game.opponent_snapshot else None
    return GameResultResponse(game_id=game.id, result=game.result, termination_reason=game.termination_reason, opponent=opponent, finished_at=game.finished_at.isoformat(), counts_for_stats=bool(game.counts_for_stats))


@app.get("/api/me/game-stats", response_model=GameStatsResponse)
async def game_stats(opponent_id: str | None = None, user: User = Depends(get_consented_user), db: Session = Depends(get_db)) -> GameStatsResponse:
    query = select(Game).where(Game.user_id == user.id, Game.mode == "ai_hall", Game.status == "finished", Game.counts_for_stats.is_(True), Game.deleted_at.is_(None))
    if opponent_id:
        query = query.where(Game.opponent_id == opponent_id)
    games = db.scalars(query).all()
    red_wins = sum(game.result == "red_win" for game in games)
    black_wins = sum(game.result == "black_win" for game in games)
    draws = sum(game.result == "draw" for game in games)
    wins = sum(game.result == ("red_win" if game.user_side == "red" else "black_win") for game in games)
    losses = sum(game.result == ("black_win" if game.user_side == "red" else "red_win") for game in games)
    return GameStatsResponse(total=red_wins + black_wins + draws, red_wins=red_wins, black_wins=black_wins, draws=draws, wins=wins, losses=losses)


@app.delete("/api/games/{game_id}", status_code=204)
async def delete_game(game_id: str, user: User = Depends(get_consented_user), db: Session = Depends(get_db)) -> Response:
    game = _owned_game(db, user, game_id)
    game.deleted_at = datetime.now(timezone.utc)
    game.status = "deleted"
    db.commit()
    return Response(status_code=204)


@app.post("/api/me/exports", response_model=DataRequestResponse, status_code=202)
async def request_export(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DataRequestResponse:
    request = DataRequest(user_id=user.id, type="export", status="queued")
    db.add(request)
    db.flush()
    export_root = Path(os.getenv("EXPORT_ROOT", str(Path(__file__).resolve().parents[3] / "exports")))
    export_root.mkdir(parents=True, exist_ok=True)
    archive_path = export_root / f"{request.id}.zip"
    games = db.scalars(select(Game).options(selectinload(Game.moves), selectinload(Game.turns)).where(Game.user_id == user.id)).all()
    reviews = db.scalars(select(Review).options(selectinload(Review.items)).where(Review.user_id == user.id)).all()
    credential = db.scalar(select(LocalCredential).where(LocalCredential.user_id == user.id))
    identities = db.scalars(select(UserIdentity).where(UserIdentity.user_id == user.id)).all()
    consents = db.scalars(select(PrivacyConsent).where(PrivacyConsent.user_id == user.id)).all()
    requests = db.scalars(select(DataRequest).where(DataRequest.user_id == user.id)).all()
    account = {
        "id": user.id, "display_name": user.display_name, "avatar_url": user.avatar_url,
        "status": user.status, "created_at": _iso(user.created_at), "updated_at": _iso(user.updated_at),
        "local_email": credential.email if credential else None,
        "local_email_verified": credential.email_verified if credential else None,
        "identities": [{"issuer": identity.issuer, "subject": identity.subject, "email": identity.email,
                        "email_verified": identity.email_verified, "created_at": _iso(identity.created_at),
                        "last_login_at": _iso(identity.last_login_at)} for identity in identities],
    }
    review_rows = [{
        "id": review.id, "game_id": review.game_id, "game_version": review.game_version,
        "initial_fen_snapshot": review.initial_fen_snapshot, "moves_snapshot": review.moves_snapshot,
        "history_hash": review.history_hash, "engine_name": review.engine_name,
        "engine_version": review.engine_version, "nnue_version": review.nnue_version,
        "parameters": review.parameters, "status": review.status, "summary": review.summary,
        "error_code": review.error_code, "created_at": _iso(review.created_at),
        "completed_at": _iso(review.completed_at),
        "items": [{"ply": item.ply, "side": item.side, "move": item.move,
                   "best_move": item.best_move, "before_score": item.before_score,
                   "after_score": item.after_score, "loss_cp": item.loss_cp,
                   "mate_value": item.mate_value, "grade": item.grade, "pv": item.pv,
                   "rule_stop_kind": item.rule_stop_kind, "rule_stop_message": item.rule_stop_message}
                  for item in review.items],
    } for review in reviews]
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps({"format": "chess-export", "version": 2}, ensure_ascii=False))
        archive.writestr("account.json", json.dumps(account, ensure_ascii=False))
        archive.writestr("privacy_consents.json", json.dumps([{"policy_type": consent.policy_type, "policy_version": consent.policy_version, "accepted_at": _iso(consent.accepted_at), "withdrawn_at": _iso(consent.withdrawn_at)} for consent in consents], ensure_ascii=False))
        archive.writestr("data_requests.json", json.dumps([{"id": item.id, "type": item.type, "status": item.status, "requested_at": _iso(item.requested_at), "completed_at": _iso(item.completed_at), "expires_at": _iso(item.expires_at), "error_code": item.error_code} for item in requests], ensure_ascii=False))
        archive.writestr("games.json", json.dumps([_game_response(game).model_dump() for game in games], ensure_ascii=False, default=str))
        archive.writestr("game_turns.json", json.dumps([{"id": turn.id, "game_id": turn.game_id, "turn_id": turn.turn_id, "request_fingerprint": turn.request_fingerprint, "expected_version": turn.expected_version, "user_uci": turn.user_uci, "user_ply": turn.user_ply, "ai_uci": turn.ai_uci, "ai_ply": turn.ai_ply, "status": turn.status, "error_code": turn.error_code, "attempt_count": turn.attempt_count, "created_at": _iso(turn.created_at), "updated_at": _iso(turn.updated_at)} for game in games for turn in game.turns], ensure_ascii=False))
        archive.writestr("reviews.json", json.dumps(review_rows, ensure_ascii=False))
    request.status = "ready"
    request.artifact_key = str(archive_path)
    request.expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    db.commit()
    return DataRequestResponse(id=request.id, type="export", status=request.status, expires_at=request.expires_at.isoformat(), download_url=f"/api/me/exports/{request.id}/download")


@app.get("/api/me/exports/{request_id}", response_model=DataRequestResponse)
async def get_export(request_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DataRequestResponse:
    request = db.scalar(select(DataRequest).where(DataRequest.id == request_id, DataRequest.user_id == user.id, DataRequest.type == "export"))
    if request is None:
        raise _api_error(404, "export_not_found", "导出请求不存在")
    return DataRequestResponse(id=request.id, type="export", status=request.status, expires_at=_iso(request.expires_at), download_url=f"/api/me/exports/{request.id}/download" if request.status == "ready" else None)


@app.get("/api/me/exports/{request_id}/download")
async def download_export(request_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    request = db.scalar(select(DataRequest).where(DataRequest.id == request_id, DataRequest.user_id == user.id, DataRequest.type == "export"))
    artifact = export_artifact_path(request.artifact_key) if request else None
    if request is None or request.status != "ready" or artifact is None or not artifact.is_file():
        raise _api_error(404, "export_unavailable", "导出文件不可用")
    expires = request.expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires and expires < datetime.now(timezone.utc):
        request.status = "expired"
        db.commit()
        artifact.unlink(missing_ok=True)
        raise _api_error(410, "export_expired", "导出文件已过期")
    return Response(content=artifact.read_bytes(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="chess-export-{request.id}.zip"'})


@app.post("/api/me/deletion", response_model=DataRequestResponse, status_code=202)
async def request_deletion(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DataRequestResponse:
    user.status = "deletion_pending"
    request = DataRequest(user_id=user.id, type="delete", status="pending", expires_at=datetime.now(timezone.utc) + timedelta(days=7))
    db.add(request)
    db.add(DeletionTombstone(user_id=user.id))
    db.commit()
    return DataRequestResponse(id=request.id, type="delete", status="pending", expires_at=request.expires_at.isoformat())


@app.post("/api/me/deletion/cancel", response_model=DataRequestResponse)
async def cancel_deletion(user: User = Depends(get_deletion_user), db: Session = Depends(get_db)) -> DataRequestResponse:
    request = db.scalar(select(DataRequest).where(DataRequest.user_id == user.id, DataRequest.type == "delete", DataRequest.status == "pending").order_by(DataRequest.requested_at.desc()))
    expires = request.expires_at if request else None
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if user.status != "deletion_pending" or expires is None or expires < datetime.now(timezone.utc):
        raise _api_error(410, "deletion_window_closed", "删除恢复窗口已结束")
    user.status = "active"
    request.status = "cancelled"
    tombstone = db.get(DeletionTombstone, user.id)
    if tombstone:
        db.delete(tombstone)
    db.commit()
    return DataRequestResponse(id=request.id, type="delete", status=request.status, expires_at=request.expires_at.isoformat())


@app.get("/api/health")
async def health() -> dict:
    llm_base_url = os.getenv("AGENT_OPENAI_BASE_URL", "").strip()
    llm_api_key = os.getenv("AGENT_OPENAI_API_KEY", "").strip()
    llm_model = os.getenv("AGENT_OPENAI_MODEL", "").strip()
    return {
        "api_ready": True,
        "engine_configured": engine.configured,
        "engine_ready": engine.ready,
        "engine_path": str(engine.path),
        "eval_file": engine.eval_file or None,
        "error": engine.last_error,
        "llm_configured": bool(llm_base_url and llm_api_key and llm_model),
        "llm_model": llm_model or None,
    }


@app.post("/api/engine/analyze", response_model=EngineResponse)
async def analyze(request: EngineRequest) -> EngineResponse:
    try:
        history = validate_history(request.fen, request.moves)
        if history.issue:
            code = "rule_violation" if history.issue.code in {"perpetual_check", "perpetual_chase"} else "invalid_move_history"
            raise _api_error(400, code, f"第 {history.issue.ply} 步无效: {history.issue.message}")
        cpu_count = os.cpu_count() or 1
        if request.threads > cpu_count:
            raise ValueError(f"线程数不能超过本机逻辑处理器数量 {cpu_count}")
        response = await engine.analyze(request.fen, request.moves, request.depth, request.movetime_ms, request.multipv, request.threads, request.hash_mb)
        position = Position.from_fen(request.fen)
        for move in request.moves:
            position.apply_uci(move)
        for line in response.lines:
            line.label = describe_uci(position, line.move)
        return response
    except HTTPException:
        raise
    except EngineRuleViolation as exc:
        raise _api_error(422, exc.code, str(exc)) from exc
    except EngineQueueFull as exc:
        raise _api_error(429, exc.code, str(exc)) from exc
    except EngineQueueTimeout as exc:
        raise _api_error(503, exc.code, str(exc)) from exc
    except ValueError as exc:
        raise _api_error(400, _value_error_code(str(exc), "invalid_fen"), str(exc)) from exc
    except EngineUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pikafish 分析失败: {exc}") from exc


@app.post("/api/engine/move", response_model=EngineMoveResponse)
async def engine_move(request: EngineMoveRequest) -> EngineMoveResponse:
    """Choose a strength-adjusted move; analysis, hints and reviews stay full strength."""
    try:
        history = validate_history(request.fen, request.moves)
        if history.issue:
            code = "rule_violation" if history.issue.code in {"perpetual_check", "perpetual_chase"} else "invalid_move_history"
            raise _api_error(400, code, f"第 {history.issue.ply} 步无效: {history.issue.message}")
        profile = profile_for(
            request.difficulty, depth=request.depth or 15,
            movetime_ms=request.movetime_ms, threads=request.threads, hash_mb=request.hash_mb,
            available_threads=os.cpu_count() or 1,
        )
        cpu_count = os.cpu_count() or 1
        if profile.threads > cpu_count:
            raise ValueError(f"线程数不能超过本机逻辑处理器数量 {cpu_count}")
        response = await engine.analyze(
            request.fen, request.moves, profile.depth, profile.movetime_ms,
            profile.max_rank, profile.threads, profile.hash_mb,
        )
        selection_seed = f"{request.game_id}:{request.ply}"
        if response.terminal_status:
            return EngineMoveResponse(**response.model_dump(), difficulty=profile.key,
                                      difficulty_label=profile.label, selected_rank=0,
                                      selection_seed=selection_seed)
        selected = select_candidate(response.lines, profile, selection_seed, allow_suboptimal=request.allow_suboptimal)
        line = selected.line
        result = response.model_dump()
        result.update(bestmove=line.move, score=line.score, depth=line.depth, pv=line.pv)
        return EngineMoveResponse(**result, difficulty=profile.key,
                                  difficulty_label=profile.label, selected_rank=line.rank,
                                  selection_seed=selection_seed)
    except HTTPException:
        raise
    except EngineRuleViolation as exc:
        raise _api_error(422, exc.code, str(exc)) from exc
    except EngineQueueFull as exc:
        raise _api_error(429, exc.code, str(exc)) from exc
    except EngineQueueTimeout as exc:
        raise _api_error(503, exc.code, str(exc)) from exc
    except ValueError as exc:
        raise _api_error(400, _value_error_code(str(exc), "invalid_parameter"), str(exc)) from exc
    except EngineUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Pikafish 应手失败: {exc}") from exc


@app.post("/api/engine/plan-analysis", response_model=PlanAnalysisResponse)
async def plan_analysis(request: PlanAnalysisRequest) -> PlanAnalysisResponse:
    try:
        history = validate_history(request.fen, request.moves)
        if history.issue:
            code = "rule_violation" if history.issue.code in {"perpetual_check", "perpetual_chase"} else "invalid_move_history"
            raise _api_error(400, code, f"第 {history.issue.ply} 步无效: {history.issue.message}")
        current_position = history.positions[-1]
        candidate_position = Position([row[:] for row in current_position.board], current_position.red_to_move)
        try:
            proposed_move = resolve_move_position(candidate_position, request.move)
        except ValueError as exc:
            raise _api_error(422, "illegal_proposed_move", str(exc)) from exc
        candidate = validate_candidate(current_position, proposed_move, history.positions, request.moves)
        if candidate.issue:
            code = "rule_violation" if candidate.issue.code in {"perpetual_check", "perpetual_chase"} else "illegal_proposed_move"
            raise _api_error(422, code, candidate.issue.message)
        cpu_count = os.cpu_count() or 1
        if request.threads > cpu_count:
            raise ValueError(f"线程数不能超过本机逻辑处理器数量 {cpu_count}")
        best_result = await engine.analyze(request.fen, request.moves, request.depth, request.movetime_ms, 1, request.threads, request.hash_mb)
        proposed_result = await engine.analyze(request.fen, request.moves + [proposed_move], request.depth, request.movetime_ms, 1, request.threads, request.hash_mb)
        best_eval = PlanMoveEvaluation(move=best_result.bestmove, label=describe_uci(current_position, best_result.bestmove), score=best_result.score, depth=best_result.depth, pv=best_result.pv)
        proposed_score = proposed_result.score
        if proposed_score and proposed_score.type == "cp":
            proposed_score = proposed_score.model_copy(update={"value": -proposed_score.value})
        proposed_eval = PlanMoveEvaluation(move=proposed_move, label=describe_uci(current_position, proposed_move), score=proposed_score, depth=proposed_result.depth, pv=[proposed_move, *proposed_result.pv])
        difference = None
        if best_result.score and proposed_score and best_result.score.type == proposed_score.type == "cp":
            difference = best_result.score.value - proposed_score.value
        payload = {"idea": request.idea, "proposed_move": proposed_eval.model_dump(), "best_move": best_eval.model_dump(), "score_difference_cp": difference}
        comparison_status = "cp" if best_result.score and proposed_score and best_result.score.type == proposed_score.type == "cp" else "mate" if best_result.score and proposed_score and best_result.score.type == proposed_score.type == "mate" else "unavailable"
        try:
            explanation = await explain(payload)
            return PlanAnalysisResponse(best=best_eval, proposed=proposed_eval, score_difference_cp=difference, explanation=explanation, ai_available=True, perspective="red" if current_position.red_to_move else "black", comparison_status=comparison_status, best_filter=best_result.filter_summary, proposed_filter=proposed_result.filter_summary)
        except LLMUnavailable as exc:
            return PlanAnalysisResponse(best=best_eval, proposed=proposed_eval, score_difference_cp=difference, explanation=None, ai_available=False, ai_message=str(exc), perspective="red" if current_position.red_to_move else "black", comparison_status=comparison_status, best_filter=best_result.filter_summary, proposed_filter=proposed_result.filter_summary)
    except HTTPException:
        raise
    except EngineRuleViolation as exc:
        raise _api_error(422, exc.code, str(exc)) from exc
    except EngineQueueTimeout as exc:
        raise _api_error(503, exc.code, str(exc)) from exc
    except ValueError as exc:
        raise _api_error(400, _value_error_code(str(exc), "invalid_fen"), str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"思路分析失败: {exc}") from exc


@app.post("/api/engine/validate", response_model=ValidationResponse)
async def validate(request: EngineRequest) -> ValidationResponse:
    try:
        Position.from_fen(request.fen)
        valid, error, error_index = validate_moves(request.fen, request.moves)
    except ValueError as exc:
        return ValidationResponse(valid=False, fen=request.fen, moves=request.moves, error=str(exc), error_index=0)
    return ValidationResponse(valid=valid, fen=request.fen, moves=request.moves, error=error, error_index=error_index)


@app.post("/api/engine/review", response_model=ReviewResponse)
async def review(request: ReviewRequest) -> ReviewResponse:
    try:
        cpu_count = os.cpu_count() or 1
        if request.threads > cpu_count:
            raise ValueError(f"线程数不能超过本机逻辑处理器数量 {cpu_count}")
        return await review_game(engine, request.fen, request.moves, request.depth, request.movetime_ms, request.threads, request.hash_mb)
    except ValueError as exc:
        code = _value_error_code(str(exc), "invalid_move_history")
        raise _api_error(400, code, str(exc)) from exc
    except EngineQueueTimeout as exc:
        raise _api_error(503, exc.code, str(exc)) from exc
    except EngineUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/games/{game_id}/reviews", response_model=PersistedReviewResponse)
async def persist_review(game_id: str, request: ReviewRequest, user: User = Depends(get_consented_user), db: Session = Depends(get_db)) -> PersistedReviewResponse:
    game = _owned_game(db, user, game_id)
    if request.fen.strip() != game.initial_fen.strip() or [move.uci for move in game.moves] != request.moves:
        raise _api_error(409, "game_snapshot_mismatch", "复盘棋谱与当前棋局不一致，请重新加载棋局")
    _validate_game_projection(game, validate_history(game.initial_fen, request.moves))
    try:
        cpu_count = os.cpu_count() or 1
        if request.threads > cpu_count:
            raise ValueError(f"线程数不能超过本机逻辑处理器数量 {cpu_count}")
        result = await review_game(engine, request.fen, request.moves, request.depth, request.movetime_ms, request.threads, request.hash_mb)
    except ValueError as exc:
        raise _api_error(400, _value_error_code(str(exc), "invalid_move_history"), str(exc)) from exc
    except EngineQueueTimeout as exc:
        raise _api_error(503, exc.code, str(exc)) from exc
    except EngineUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    canonical = json.dumps({"fen": request.fen.strip(), "moves": request.moves}, ensure_ascii=False, separators=(",", ":"))
    snapshot_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    saved = Review(game_id=game.id, user_id=user.id, game_version=game.version, initial_fen_snapshot=request.fen.strip(), moves_snapshot=request.moves, history_hash=snapshot_hash, engine_name="Pikafish", engine_version=engine.engine_version, nnue_version=engine.nnue_version, parameters=request.model_dump(), status=result.status, summary=result.stop.message if result.stop else None, error_code=result.stop.kind if result.stop else None, completed_at=datetime.now(timezone.utc))
    db.add(saved)
    db.flush()
    for item in result.items:
        db.add(ReviewItem(review_id=saved.id, ply=item.ply, side=item.side, move=item.move, best_move=item.best_move, before_score=item.before_score.model_dump() if item.before_score else None, after_score=item.after_score.model_dump() if item.after_score else None, loss_cp=item.loss_cp, mate_value=(item.after_score.value if item.after_score and item.after_score.type == "mate" else None), grade=item.grade, pv=item.pv))
    if result.stop and 1 <= result.stop.ply <= len(request.moves):
        db.add(ReviewItem(review_id=saved.id, ply=result.stop.ply, side=result.stop.side, move=request.moves[result.stop.ply - 1], grade="unknown", pv=[], rule_stop_kind=result.stop.kind, rule_stop_message=result.stop.message))
    db.commit()
    return PersistedReviewResponse(review_id=saved.id, game_id=game.id, snapshot_hash=snapshot_hash, **result.model_dump())


@app.get("/api/reviews/{review_id}")
async def get_persisted_review(review_id: str, user: User = Depends(get_consented_user), db: Session = Depends(get_db)) -> dict:
    review = db.scalar(select(Review).options(selectinload(Review.items)).where(Review.id == review_id, Review.user_id == user.id))
    if review is None:
        raise _api_error(404, "review_not_found", "复盘不存在")
    return {"id": review.id, "game_id": review.game_id, "status": review.status, "initial_fen": review.initial_fen_snapshot, "moves": review.moves_snapshot, "history_hash": review.history_hash, "engine_name": review.engine_name, "engine_version": review.engine_version, "nnue_version": review.nnue_version, "parameters": review.parameters, "summary": review.summary, "error_code": review.error_code, "items": [{"ply": item.ply, "side": item.side, "move": item.move, "best_move": item.best_move, "before_score": item.before_score, "after_score": item.after_score, "loss_cp": item.loss_cp, "mate_value": item.mate_value, "grade": item.grade, "pv": item.pv, "rule_stop_kind": item.rule_stop_kind, "rule_stop_message": item.rule_stop_message} for item in review.items]}


@app.post("/api/openings", response_model=OpeningsResponse)
def openings(request: EngineRequest) -> OpeningsResponse:
    try:
        return lookup_openings(request.fen, request.moves)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/coach/chat", response_model=CoachResponse)
async def coach(request: CoachRequest) -> CoachResponse:
    try:
        valid, error, index = validate_moves(request.fen, request.moves)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"FEN 无效: {exc}") from exc
    if not valid:
        raise HTTPException(status_code=400, detail=f"第 {index + 1} 步无效: {error}")
    try:
        return CoachResponse(answer=await coach_chat(request))
    except LLMUnavailable as exc:
        return CoachResponse(answer="", ai_available=False, ai_message=str(exc))


@app.post("/api/setup/image", response_model=SetupImageResponse)
async def setup_image(file: UploadFile = File(...)) -> SetupImageResponse:
    allowed_types = {"image/png", "image/jpeg", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="只支持 PNG、JPEG 或 WebP 棋盘图片")
    content = await file.read(8 * 1024 * 1024 + 1)
    if len(content) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="图片不能超过 8MB")
    if not content:
        raise HTTPException(status_code=400, detail="图片内容为空")
    signatures = {
        "image/png": lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": lambda data: data.startswith(b"\xff\xd8\xff"),
        "image/webp": lambda data: len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP",
    }
    if not signatures[file.content_type](content):
        raise HTTPException(status_code=400, detail="图片内容与文件类型不匹配或文件已损坏")
    try:
        result = await recognize_board_image(content, file.content_type)
        return SetupImageResponse(
            fen=result.fen,
            red_to_move=result.red_to_move,
            piece_count=result.piece_count,
            warnings=result.warnings,
        )
    except VisionRecognitionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/engine/reset")
async def reset() -> dict:
    await engine.reset()
    return await health()

