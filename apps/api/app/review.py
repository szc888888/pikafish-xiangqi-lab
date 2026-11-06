from .engine import PikafishEngine
from .models import ReviewItem, ReviewResponse, ReviewStop, Score
from .xiangqi import Position, describe_uci, validate_history


def invert_score(score: Score | None) -> Score | None:
    if score is None:
        return None
    return score.model_copy(update={"value": -score.value})


def classify_loss(before: Score | None, after_for_mover: Score | None) -> tuple[str, int | None]:
    if before is None or after_for_mover is None:
        return "unknown", None
    if before.type == "mate" or after_for_mover.type == "mate":
        # After normalization, positive mate favors the player who just moved;
        # negative mate means the opponent can force mate (UCI convention).
        if before.type == after_for_mover.type == "mate" and before.value < 0 and after_for_mover.value < 0:
            # Already losing: mate distances from separate searches are not a
            # reliable new loss, even when the move differs from the engine PV.
            return "unknown", None
        if after_for_mover.type == "mate" and after_for_mover.value < 0:
            return "blunder", None
        if after_for_mover.type == "mate" and after_for_mover.value > 0:
            return "good", None
        return "unknown", None
    loss = max(0, before.value - after_for_mover.value)
    if loss < 30:
        return "good", loss
    if loss < 80:
        return "inaccuracy", loss
    if loss < 200:
        return "mistake", loss
    return "blunder", loss


async def review_game(engine: PikafishEngine, fen: str, moves: list[str], depth: int, movetime_ms: int, threads: int, hash_mb: int) -> ReviewResponse:
    history = validate_history(fen, moves)
    issue = history.issue
    if issue and issue.code == "invalid_move":
        raise ValueError(f"第 {issue.ply} 步无效: {issue.message}")
    analyzed_plies = issue.ply - 1 if issue else len(moves)
    stop = ReviewStop(
        ply=issue.ply,
        side=issue.side,
        kind=issue.code,
        message=issue.message,
    ) if issue else None

    results = []
    for ply in range(analyzed_plies + 1):
        results.append(await engine.analyze(fen, moves[:ply], depth, movetime_ms, 1, threads, hash_mb))

    items: list[ReviewItem] = []
    for index in range(analyzed_plies):
        move = moves[index]
        position = history.positions[index]
        side = "red" if position.red_to_move else "black"
        before = results[index]
        after = results[index + 1]
        after_for_mover = invert_score(after.score)
        grade, loss = classify_loss(before.score, after_for_mover)
        items.append(ReviewItem(
            ply=index + 1,
            side=side,
            move=move,
            label=describe_uci(position, move),
            best_move=before.bestmove if before.bestmove not in {"0000", "(none)", "none"} else None,
            best_label=describe_uci(position, before.bestmove) if before.bestmove not in {"0000", "(none)", "none"} else None,
            before_score=before.score,
            after_score=after_for_mover,
            loss_cp=loss,
            grade=grade,
            pv=before.pv,
        ))
    return ReviewResponse(
        items=items,
        final_score=results[-1].score,
        analyzed_plies=analyzed_plies,
        status="stopped_rule_violation" if stop else "complete",
        stop=stop,
    )
