"""Human-facing Pikafish strength profiles and deterministic move selection."""

from dataclasses import dataclass
import hashlib
import random

from .models import EngineLine


@dataclass(frozen=True)
class EngineProfile:
    key: str
    label: str
    depth: int
    movetime_ms: int
    threads: int
    hash_mb: int
    max_rank: int
    max_loss_cp: int | None
    full_strength: bool = False


PROFILE_DEFINITIONS = {
    "companion": EngineProfile("companion", "轻松陪练", 1, 100, 1, 16, 5, 500),
    "beginner": EngineProfile("beginner", "入门练习", 2, 250, 1, 32, 4, 250),
    "progress": EngineProfile("progress", "进阶对手", 4, 700, 1, 64, 3, 100),
    "serious": EngineProfile("serious", "认真对弈", 8, 1500, 2, 256, 2, 30),
    "full": EngineProfile("full", "全力挑战", 15, 5000, 4, 1024, 1, 0, True),
}


def profile_for(
    key: str,
    *,
    depth: int = 15,
    movetime_ms: int = 0,
    threads: int = 1,
    hash_mb: int = 16,
    available_threads: int | None = None,
) -> EngineProfile:
    if key != "custom":
        try:
            profile = PROFILE_DEFINITIONS[key]
            if available_threads is not None:
                return EngineProfile(
                    **{**profile.__dict__, "threads": max(1, min(profile.threads, available_threads))}
                )
            return profile
        except KeyError as exc:
            raise ValueError("未知的对弈难度") from exc
    return EngineProfile(
        "custom", "自定义", max(1, min(int(depth), 64)),
        max(0, min(int(movetime_ms), 120_000)), max(1, min(int(threads), 16)),
        max(16, min(int(hash_mb), 8192)), 1, 0, True,
    )


@dataclass(frozen=True)
class CandidateSelection:
    line: EngineLine
    profile: EngineProfile


def _loss(best: EngineLine, candidate: EngineLine) -> int | None:
    if best.score is None or candidate.score is None:
        return None
    if best.score.type == "mate" or candidate.score.type == "mate":
        if best.score.type == candidate.score.type == "mate":
            # In a mate score, a larger positive value means mate is farther away;
            # a negative value means the side to move is being mated.
            if best.score.value > 0 and candidate.score.value > 0:
                return max(0, candidate.score.value - best.score.value) * 1000
            if best.score.value < 0 and candidate.score.value < 0:
                return max(0, candidate.score.value - best.score.value) * 1000
        return 1_000_000
    return max(0, best.score.value - candidate.score.value)


def select_candidate(
    lines: list[EngineLine], profile: EngineProfile, seed: str, *, allow_suboptimal: bool = True,
) -> CandidateSelection:
    if not lines:
        raise ValueError("没有合法候选着法")
    ordered = sorted(lines, key=lambda line: line.rank)
    if profile.full_strength or not allow_suboptimal:
        return CandidateSelection(ordered[0], profile)
    best = ordered[0]
    if best.score is None:
        return CandidateSelection(best, profile)
    eligible = []
    for line in ordered:
        if line.rank > profile.max_rank:
            continue
        if line.score is None:
            continue
        loss = _loss(best, line)
        if profile.max_loss_cp is not None and loss is not None and loss > profile.max_loss_cp:
            continue
        eligible.append(line)
    if not eligible:
        eligible = [best]
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    chosen = random.Random(int.from_bytes(digest[:8], "big")).choice(eligible)
    return CandidateSelection(chosen, profile)
