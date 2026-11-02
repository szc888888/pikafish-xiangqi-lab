from typing import Literal

from pydantic import BaseModel, Field


class EngineRequest(BaseModel):
    fen: str = Field(min_length=1, max_length=200)
    moves: list[str] = Field(default_factory=list, max_length=400)
    depth: int | None = Field(default=None, ge=1, le=64)
    movetime_ms: int = Field(default=0, ge=0, le=120_000)
    multipv: int = Field(default=1, ge=1, le=5)
    threads: int = Field(default=1, ge=1, le=1024)
    hash_mb: int = Field(default=16, ge=16, le=8192)


class EngineMoveRequest(EngineRequest):
    difficulty: Literal["companion", "beginner", "progress", "serious", "full", "custom"] = "progress"
    allow_suboptimal: bool = True
    game_id: str = Field(min_length=1, max_length=200)
    ply: int = Field(ge=0, le=400)


class Score(BaseModel):
    type: Literal["cp", "mate"]
    value: int


class EngineLine(BaseModel):
    rank: int
    move: str
    label: str
    score: Score | None = None
    depth: int | None = None
    pv: list[str] = Field(default_factory=list)


class CandidateRejection(BaseModel):
    move: str
    code: str
    reason: str


class CandidateFilterSummary(BaseModel):
    requested: int = 0
    returned: int = 0
    rejected: list[CandidateRejection] = Field(default_factory=list)


class EngineResponse(BaseModel):
    bestmove: str
    score: Score | None = None
    depth: int | None = None
    nodes: int | None = None
    nps: int | None = None
    pv: list[str] = Field(default_factory=list)
    raw_info: list[str] = Field(default_factory=list)
    lines: list[EngineLine] = Field(default_factory=list)
    filter_summary: CandidateFilterSummary = Field(default_factory=CandidateFilterSummary)
    terminal_status: Literal["checkmate", "stalemate"] | None = None


class EngineMoveResponse(EngineResponse):
    difficulty: str
    difficulty_label: str
    selected_rank: int
    selection_seed: str


class ValidationResponse(BaseModel):
    valid: bool
    fen: str
    moves: list[str]
    error: str | None = None
    error_index: int | None = None


class PlanAnalysisRequest(BaseModel):
    fen: str = Field(min_length=1, max_length=200)
    moves: list[str] = Field(default_factory=list, max_length=400)
    idea: str = Field(min_length=1, max_length=1200)
    move: str = Field(min_length=1, max_length=40)
    depth: int = Field(default=10, ge=1, le=64)
    movetime_ms: int = Field(default=1500, ge=0, le=120_000)
    threads: int = Field(default=1, ge=1, le=1024)
    hash_mb: int = Field(default=256, ge=16, le=8192)


class PlanMoveEvaluation(BaseModel):
    move: str
    label: str
    score: Score | None = None
    depth: int | None = None
    pv: list[str] = Field(default_factory=list)


class PlanExplanation(BaseModel):
    advantages: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    engine_assessment: str
    suggestion: str


class PlanAnalysisResponse(BaseModel):
    best: PlanMoveEvaluation
    proposed: PlanMoveEvaluation
    score_difference_cp: int | None = None
    explanation: PlanExplanation | None = None
    ai_available: bool
    ai_message: str | None = None
    perspective: Literal["red", "black"] = "red"
    comparison_status: Literal["cp", "mate", "unavailable"] = "unavailable"
    best_filter: CandidateFilterSummary | None = None
    proposed_filter: CandidateFilterSummary | None = None


class ReviewRequest(BaseModel):
    fen: str = Field(min_length=1, max_length=200)
    moves: list[str] = Field(default_factory=list, max_length=120)
    depth: int = Field(default=8, ge=1, le=16)
    movetime_ms: int = Field(default=250, ge=0, le=2000)
    threads: int = Field(default=1, ge=1, le=16)
    hash_mb: int = Field(default=128, ge=16, le=1024)


class ReviewItem(BaseModel):
    ply: int
    side: Literal["red", "black"]
    move: str
    label: str
    best_move: str | None = None
    best_label: str | None = None
    before_score: Score | None = None
    after_score: Score | None = None
    loss_cp: int | None = None
    mate_value: int | None = None
    grade: Literal["good", "inaccuracy", "mistake", "blunder", "unknown"]
    pv: list[str] = Field(default_factory=list)
    rule_stop_kind: Literal["perpetual_check", "perpetual_chase"] | None = None
    rule_stop_message: str | None = None


class ReviewStop(BaseModel):
    ply: int
    side: Literal["red", "black"]
    kind: Literal["perpetual_check", "perpetual_chase"]
    message: str


class ReviewResponse(BaseModel):
    items: list[ReviewItem]
    final_score: Score | None = None
    analyzed_plies: int
    status: Literal["complete", "stopped_rule_violation"] = "complete"
    stop: ReviewStop | None = None


class PersistedReviewResponse(ReviewResponse):
    review_id: str
    game_id: str
    snapshot_hash: str


class OpeningLine(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    source: str
    matched_plies: int
    next_moves: list[dict[str, str]] = Field(default_factory=list)


class OpeningsResponse(BaseModel):
    matches: list[OpeningLine] = Field(default_factory=list)


class CoachMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class CoachRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1200)
    fen: str = Field(min_length=1, max_length=200)
    moves: list[str] = Field(default_factory=list, max_length=120)
    messages: list[CoachMessage] = Field(default_factory=list, max_length=20)
    context: str = Field(default="", max_length=5000)


class CoachResponse(BaseModel):
    answer: str
    ai_available: bool = True
    ai_message: str | None = None


class SetupImageResponse(BaseModel):
    fen: str
    red_to_move: bool
    piece_count: int
    warnings: list[str] = Field(default_factory=list)


class SavedEngineSettings(BaseModel):
    difficulty: Literal["companion", "beginner", "progress", "serious", "full", "custom"] = "progress"
    allow_suboptimal: bool = True
    depth: int = Field(default=4, ge=1, le=64)
    movetime_ms: int = Field(default=700, ge=0, le=120_000)
    threads: int = Field(default=1, ge=1, le=16)
    hash_mb: int = Field(default=64, ge=16, le=8192)


class GameCreateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    initial_fen: str = Field(min_length=1, max_length=200)
    engine_settings: SavedEngineSettings = Field(default_factory=SavedEngineSettings)


class LegacyGameImportRequest(BaseModel):
    legacy_id: str = Field(min_length=1, max_length=200)
    name: str | None = Field(default=None, max_length=120)
    initial_fen: str = Field(min_length=1, max_length=200)
    moves: list[str] = Field(default_factory=list, max_length=400)
    engine_settings: SavedEngineSettings = Field(default_factory=SavedEngineSettings)


class MoveCreateRequest(BaseModel):
    expected_version: int = Field(ge=0)
    uci: str = Field(min_length=4, max_length=8)
    engine_settings: SavedEngineSettings | None = None


class GameUpdateRequest(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    expected_version: int = Field(ge=0)


class GameMoveResponse(BaseModel):
    ply: int
    side: Literal["red", "black"]
    uci: str
    notation_zh: str
    before_fen: str
    after_fen: str


class GameResponse(BaseModel):
    id: str
    name: str | None
    initial_fen: str
    current_fen: str
    red_to_move: bool
    status: str
    version: int
    created_at: str
    updated_at: str
    engine_settings: SavedEngineSettings = Field(default_factory=SavedEngineSettings)
    moves: list[GameMoveResponse] = Field(default_factory=list)


class DataRequestResponse(BaseModel):
    id: str
    type: Literal["export", "delete"]
    status: str
    expires_at: str | None = None
    download_url: str | None = None


class EmailRegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(default=None, max_length=120)
    accept_privacy: Literal[True]
    policy_version: str = Field(min_length=1, max_length=64)


class EmailLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class EmailAddressRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class EmailTokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=256)


class PasswordResetRequest(EmailTokenRequest):
    password: str = Field(min_length=8, max_length=128)


class PrivacyConsentRequest(BaseModel):
    accepted: Literal[True]
    policy_version: str = Field(min_length=1, max_length=64)

