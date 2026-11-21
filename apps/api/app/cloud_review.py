"""Persist segmented engine reviews in the existing review lifecycle tables."""
from datetime import datetime, timezone
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .models import CloudReviewProgress, CloudReviewRequest, PersistedReviewResponse, ReviewItem as ResultItem, ReviewResponse, Score
from .persistence import Game, Review, ReviewItem, User
from .xiangqi import describe_uci, validate_history


def metadata(review: Review) -> dict:
    return review.parameters["_segmented"]


def _legacy_metadata(review: Review) -> dict | None:
    """Recover completed reviews written by the original single-request API."""
    history = validate_history(review.initial_fen_snapshot, review.moves_snapshot)
    issue = history.issue
    if issue and issue.code == "invalid_move":
        return None
    completed = issue.ply - 1 if issue else len(review.moves_snapshot)
    items = sorted((item for item in review.items if not item.rule_stop_kind), key=lambda item: item.ply)
    if [item.ply for item in items] != list(range(1, completed + 1)):
        return None
    if any(item.move != review.moves_snapshot[item.ply - 1] for item in items):
        return None
    stops = [item for item in review.items if item.rule_stop_kind]
    stop = None
    if issue:
        if review.status != "stopped_rule_violation" or len(stops) != 1:
            return None
        row = stops[0]
        if (row.ply, row.side, row.rule_stop_kind) != (issue.ply, issue.side, issue.code):
            return None
        stop = {"ply": row.ply, "side": row.side, "kind": row.rule_stop_kind,
                "message": row.rule_stop_message or issue.message}
    elif review.status != "complete" or stops:
        return None
    # Stored after_score is from the mover's perspective; final_score is from
    # the next side to move. Keep unknown scores unknown, including mate scores.
    final_score = None
    if items and items[-1].after_score is not None:
        score = Score.model_validate(items[-1].after_score)
        final_score = score.model_copy(update={"value": -score.value}).model_dump()
    return {"completed_plies": completed, "final_score": final_score, "stop": stop}


def progress(review: Review, meta: dict | None = None) -> CloudReviewProgress:
    if meta is None:
        meta = metadata(review)
    result = None
    if review.status in {"complete", "stopped_rule_violation"}:
        history = validate_history(review.initial_fen_snapshot, review.moves_snapshot)
        items = []
        for item in review.items:
            if item.rule_stop_kind:
                continue
            position = history.positions[item.ply - 1]
            items.append(ResultItem(
                ply=item.ply, side=item.side, move=item.move,
                label=describe_uci(position, item.move), best_move=item.best_move,
                best_label=describe_uci(position, item.best_move) if item.best_move else None,
                before_score=Score.model_validate(item.before_score) if item.before_score else None,
                after_score=Score.model_validate(item.after_score) if item.after_score else None,
                loss_cp=item.loss_cp, grade=item.grade, pv=item.pv,
            ))
        result = PersistedReviewResponse(
            review_id=review.id, game_id=review.game_id, snapshot_hash=review.history_hash,
            items=items, final_score=meta.get("final_score"), analyzed_plies=meta["completed_plies"],
            status=review.status, stop=meta.get("stop"),
        )
    return CloudReviewProgress(review_id=review.id, completed_plies=meta["completed_plies"],
                               total_plies=len(review.moves_snapshot), status=review.status, result=result)


def start(db: Session, user: User, game: Game, request: CloudReviewRequest, engine) -> CloudReviewProgress:
    parameters = request.model_dump(exclude={"reuse"})
    canonical = json.dumps({"fen": request.fen.strip(), "moves": request.moves}, ensure_ascii=False, separators=(",", ":"))
    snapshot_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if request.reuse:
        existing = db.scalars(select(Review).options(selectinload(Review.items)).where(
            Review.game_id == game.id, Review.user_id == user.id, Review.history_hash == snapshot_hash,
            Review.status.in_(["in_progress", "complete", "stopped_rule_violation"]),
        ).order_by(Review.created_at.desc())).all()
        for saved in existing:
            if {k: v for k, v in saved.parameters.items() if k != "_segmented"} != parameters:
                continue
            if "_segmented" in saved.parameters:
                return progress(saved)
            legacy = _legacy_metadata(saved)
            if legacy is not None:
                return progress(saved, legacy)
    saved = Review(
        game_id=game.id, user_id=user.id, game_version=game.version,
        initial_fen_snapshot=request.fen.strip(), moves_snapshot=list(request.moves), history_hash=snapshot_hash,
        engine_name="Pikafish", engine_version=engine.engine_version, nnue_version=engine.nnue_version,
        parameters={**parameters, "_segmented": {"version": 1, "completed_plies": 0, "final_score": None, "stop": None}},
        status="in_progress",
    )
    db.add(saved)
    db.commit()
    return progress(saved)


def save_segment(db: Session, saved: Review, result: ReviewResponse, end: int) -> CloudReviewProgress:
    """Write one whole batch atomically; never persist a partly analyzed batch."""
    start_ply = metadata(saved)["completed_plies"]
    if [item.ply for item in result.items] != list(range(start_ply + 1, result.analyzed_plies + 1)):
        raise ValueError("复盘结果不连续，未保存此批结果")
    if result.status == "complete" and result.analyzed_plies != end:
        raise ValueError("复盘结果不完整，未保存此批结果")
    for item in result.items:
        db.add(ReviewItem(
            review_id=saved.id, ply=item.ply, side=item.side, move=item.move, best_move=item.best_move,
            before_score=item.before_score.model_dump() if item.before_score else None,
            after_score=item.after_score.model_dump() if item.after_score else None, loss_cp=item.loss_cp,
            mate_value=item.after_score.value if item.after_score and item.after_score.type == "mate" else None,
            grade=item.grade, pv=item.pv,
        ))
    if result.stop:
        db.add(ReviewItem(review_id=saved.id, ply=result.stop.ply, side=result.stop.side,
                          move=saved.moves_snapshot[result.stop.ply - 1], grade="unknown", pv=[],
                          rule_stop_kind=result.stop.kind, rule_stop_message=result.stop.message))
    meta = {"version": 1, "completed_plies": result.analyzed_plies,
            "final_score": result.final_score.model_dump() if result.final_score else None,
            "stop": result.stop.model_dump() if result.stop else None}
    saved.parameters = {**saved.parameters, "_segmented": meta}
    finished = result.stop is not None or end == len(saved.moves_snapshot)
    saved.status = result.status if finished else "in_progress"
    if finished:
        saved.completed_at = datetime.now(timezone.utc)
        saved.summary = result.stop.message if result.stop else None
        saved.error_code = result.stop.kind if result.stop else None
    db.commit()
    db.expire(saved, ["items"])
    return progress(saved)
