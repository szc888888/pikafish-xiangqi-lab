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

from .engine import EngineRuleViolation, EngineUnavailable, PikafishEngine
from .engine_strength import profile_for, select_candidate
from .llm import LLMUnavailable, VisionRecognitionError, coach_chat, explain, recognize_board_image
from .models import CoachRequest, CoachResponse, DataRequestResponse, EmailAddressRequest, EmailLoginRequest, EmailRegisterRequest, EmailTokenRequest, PasswordResetRequest, PrivacyConsentRequest, EngineRequest, EngineMoveRequest, EngineMoveResponse, EngineResponse, GameCreateRequest, GameMoveResponse, GameResponse, GameUpdateRequest, MoveCreateRequest, OpeningsResponse, PersistedReviewResponse, PlanAnalysisRequest, PlanAnalysisResponse, PlanExplanation, PlanMoveEvaluation, ReviewRequest, ReviewResponse, SavedEngineSettings, SetupImageResponse, ValidationResponse
from .auth import get_current_user, get_consented_user, get_deletion_user, login_email, oidc_configured, register_email, normalize_email, password_hasher, log_auth_event
from .email_flow import consume_token, email_verification_required, request_action, revoke_tokens
from .privacy import has_consent, policy_version, publication_missing, record_consent, validate_publication_configuration
from .database import assert_database_migrated, get_db, init_database
from .persistence import DataRequest, DeletionTombstone, Game, GameMove, LocalCredential, PrivacyConsent, Review, ReviewItem, User, UserIdentity
from .deletion_ledger import export_artifact_path, purge_expired_deletions, purge_expired_exports
from .openings import lookup_openings
from .review import review_game
from .xiangqi import Position, describe_uci, resolve_move_position, validate_candidate, validate_fen, validate_history, validate_moves
from sqlalchemy import select
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
        try:
            body = json.loads(await request.body())
            email = body.get("email", "") if isinstance(body, dict) else ""
        except (ValueError, UnicodeDecodeError):
            email = ""
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


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _game_response(game: Game) -> GameResponse:
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


@app.get("/api/games", response_model=list[GameResponse])
async def list_games(user: User = Depends(get_consented_user), db: Session = Depends(get_db)) -> list[GameResponse]:
    games = db.scalars(select(Game).options(selectinload(Game.moves)).where(Game.user_id == user.id, Game.deleted_at.is_(None)).order_by(Game.updated_at.desc())).all()
    return [_game_response(game) for game in games]


@app.post("/api/games", response_model=GameResponse, status_code=201)
async def create_game(payload: GameCreateRequest, user: User = Depends(get_consented_user), db: Session = Depends(get_db)) -> GameResponse:
    if user.status != "active":
        raise _api_error(410, "account_unavailable", "账号正在删除或已删除")
    try:
        position = validate_fen(payload.initial_fen)
    except ValueError as exc:
        raise _api_error(400, "invalid_fen", str(exc)) from exc
    game = Game(user_id=user.id, name=payload.name, initial_fen=payload.initial_fen.strip(), current_fen=payload.initial_fen.strip(), red_to_move=position.red_to_move, engine_settings=_normalized_engine_settings(payload.engine_settings).model_dump())
    db.add(game)
    db.commit()
    db.refresh(game)
    return _game_response(game)


@app.get("/api/games/{game_id}", response_model=GameResponse)
async def get_game(game_id: str, user: User = Depends(get_consented_user), db: Session = Depends(get_db)) -> GameResponse:
    return _game_response(_owned_game(db, user, game_id))


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


@app.post("/api/games/{game_id}/moves", response_model=GameResponse, status_code=201)
async def append_move(game_id: str, payload: MoveCreateRequest, user: User = Depends(get_consented_user), db: Session = Depends(get_db)) -> GameResponse:
    game = _owned_game(db, user, game_id)
    if game.version != payload.expected_version:
        raise _api_error(409, "stale_game", "棋局已被其他页面更新，请刷新后重试")
    moves = [move.uci for move in game.moves]
    history = validate_history(game.initial_fen, [*moves, payload.uci])
    if history.issue:
        code = "rule_violation" if history.issue.code in {"perpetual_check", "perpetual_chase"} else "invalid_move"
        raise _api_error(422, code, f"第 {history.issue.ply} 步无效: {history.issue.message}")
    before = history.positions[-2]
    after = history.positions[-1]
    before_fen = _position_to_fen(before)
    after_fen = _position_to_fen(after)
    move = GameMove(game_id=game.id, ply=len(game.moves) + 1, side="red" if before.red_to_move else "black", uci=payload.uci, notation_zh=describe_uci(before, payload.uci), before_fen=before_fen, after_fen=after_fen)
    game.current_fen = after_fen
    game.red_to_move = after.red_to_move
    if payload.engine_settings is not None:
        game.engine_settings = _normalized_engine_settings(payload.engine_settings).model_dump()
    game.version += 1
    if history.positions[-1].red_to_move == before.red_to_move:
        game.status = "finished"
    db.add(move)
    db.commit()
    db.refresh(game)
    return _game_response(_owned_game(db, user, game.id))


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
    games = db.scalars(select(Game).options(selectinload(Game.moves)).where(Game.user_id == user.id)).all()
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
    except EngineUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/games/{game_id}/reviews", response_model=PersistedReviewResponse)
async def persist_review(game_id: str, request: ReviewRequest, user: User = Depends(get_consented_user), db: Session = Depends(get_db)) -> PersistedReviewResponse:
    game = _owned_game(db, user, game_id)
    if request.fen.strip() != game.initial_fen.strip() or [move.uci for move in game.moves] != request.moves:
        raise _api_error(409, "game_snapshot_mismatch", "复盘棋谱与当前棋局不一致，请重新加载棋局")
    try:
        cpu_count = os.cpu_count() or 1
        if request.threads > cpu_count:
            raise ValueError(f"线程数不能超过本机逻辑处理器数量 {cpu_count}")
        result = await review_game(engine, request.fen, request.moves, request.depth, request.movetime_ms, request.threads, request.hash_mb)
    except ValueError as exc:
        raise _api_error(400, _value_error_code(str(exc), "invalid_move_history"), str(exc)) from exc
    except EngineUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    canonical = json.dumps({"fen": request.fen.strip(), "moves": request.moves}, ensure_ascii=False, separators=(",", ":"))
    snapshot_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    saved = Review(game_id=game.id, user_id=user.id, game_version=game.version, initial_fen_snapshot=request.fen.strip(), moves_snapshot=request.moves, history_hash=snapshot_hash, engine_name="Pikafish", parameters=request.model_dump(), status=result.status, summary=result.stop.message if result.stop else None, error_code=result.stop.kind if result.stop else None, completed_at=datetime.now(timezone.utc))
    db.add(saved)
    db.flush()
    for item in result.items:
        db.add(ReviewItem(review_id=saved.id, ply=item.ply, side=item.side, move=item.move, best_move=item.best_move, before_score=item.before_score.model_dump() if item.before_score else None, after_score=item.after_score.model_dump() if item.after_score else None, loss_cp=item.loss_cp, grade=item.grade, pv=item.pv))
    db.commit()
    return PersistedReviewResponse(review_id=saved.id, game_id=game.id, snapshot_hash=snapshot_hash, **result.model_dump())


@app.get("/api/reviews/{review_id}")
async def get_persisted_review(review_id: str, user: User = Depends(get_consented_user), db: Session = Depends(get_db)) -> dict:
    review = db.scalar(select(Review).options(selectinload(Review.items)).where(Review.id == review_id, Review.user_id == user.id))
    if review is None:
        raise _api_error(404, "review_not_found", "复盘不存在")
    return {"id": review.id, "game_id": review.game_id, "status": review.status, "initial_fen": review.initial_fen_snapshot, "moves": review.moves_snapshot, "history_hash": review.history_hash, "items": [{"ply": item.ply, "side": item.side, "move": item.move, "best_move": item.best_move, "before_score": item.before_score, "after_score": item.after_score, "loss_cp": item.loss_cp, "grade": item.grade, "pv": item.pv} for item in review.items]}


@app.post("/api/openings", response_model=OpeningsResponse)
async def openings(request: EngineRequest) -> OpeningsResponse:
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

