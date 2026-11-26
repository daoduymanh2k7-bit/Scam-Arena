from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.arena.intent_detector import Intent


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class DialogueTurn(BaseModel):
    role: Literal["user", "scammer_ai"]
    text: str
    elapsed_seconds: float | None = None
    stage_id: str | None = None
    intent: Intent | None = None


class ScorerFlag(BaseModel):
    turn_index: int
    mistake: str
    severity: RiskLevel


class CallSession(BaseModel):
    session_id: str
    scenario_type: str
    transcript: list[DialogueTurn] = Field(default_factory=list)
    mistakes: list[ScorerFlag] = Field(default_factory=list)
    user_score: int = 100
    badge: str | None = None
    avg_response_latency: float | None = None


class ReplyRequest(BaseModel):
    scenario_key: str
    history: list[DialogueTurn] = Field(default_factory=list)
    user_text: str = Field(max_length=4000)
    stage_id: str | None = Field(default=None, max_length=50)
    stage_turn_count: int = Field(default=0, ge=0, le=10)


class ReplyResponse(BaseModel):
    reply: str
    intent: Intent | None = None
    matched_rule: str | None = None
    evidence: str | None = None
    current_stage_id: str | None = None
    stage_turn_count: int = Field(ge=0, le=10)
    finished: bool = False
    outcome: Literal["safe", "unsafe", "neutral"] | None = None


class ScoreRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    scenario_type: str = Field(min_length=1, max_length=120)
    transcript: list[DialogueTurn] = Field(max_length=100)


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class StartCallRequest(BaseModel):
    scenario_key: str = Field(min_length=1, max_length=80)
    interaction_mode: Literal["message", "call"] = "message"
    practice_difficulty: Literal['adaptive','beginner','intermediate','advanced'] = 'adaptive'
    exercise_mode: Literal['training','assessment'] = 'training'


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=3, max_length=128)


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class AuthUserResponse(BaseModel):
    username: str
    role: Literal["user", "admin"]
    onboarding_completed: bool = False


class StartCallResponse(BaseModel):
    session_id: str
    scenario_key: str
    scenario_title: str
    bot_text: str
    stage: str
    practice_context: str | None = None


class CallTurnRequest(BaseModel):
    user_text: str = Field(min_length=1, max_length=4000)
    elapsed_seconds: float | None = Field(default=None, ge=0, le=3600)


class CallTurnResponse(BaseModel):
    bot_text: str
    intent: Intent
    intent_method: Literal["rule", "rasa", "llm", "fallback"]
    line_source: Literal["cache_exact", "cache_pool", "llm", "fixed"] = "fixed"
    line_latency_ms: int = 0
    line_id: int | None = None
    turn_no: int | None = None
    stage: str | None = None
    ended: bool = False
    outcome: Literal["safe", "scammed", "timeout"] | None = None
    score: int = Field(ge=0, le=100)
    score_delta: int = 0
    feedback: str | None = None


class LinePreferenceResponse(BaseModel):
    line_id: int
    reaction: Literal["like", "dislike"]
    preference_score: int


class RegeneratedLineResponse(BaseModel):
    bot_text: str
    line_source: Literal["llm", "cache_pool"]
    line_latency_ms: int
    line_id: int | None
    turn_no: int


class SessionFeedback(BaseModel):
    turn_no: int
    intent: Intent
    feedback: str
    score_delta: int
    critical: bool
    stage: str | None = None
    tactic: str | None = None


class SessionRedFlag(BaseModel):
    id: str
    title: str
    explanation: str
    severity: Literal["low", "medium", "high"]
    stage_id: str


class CallSummaryResponse(BaseModel):
    session_id: str
    scenario_key: str
    scenario_title: str
    outcome: Literal["safe", "scammed", "timeout"] | None
    total_score: int = Field(ge=0, le=100)
    badge: str
    avg_response_latency: float | None = None
    turn_count: int = 0
    lesson_summary: str | None = None
    feedback: list[SessionFeedback] = Field(default_factory=list)
    mistakes: list[ScorerFlag] = Field(default_factory=list)
    red_flags: list[SessionRedFlag] = Field(default_factory=list)


class CallHistoryItem(BaseModel):
    interaction_mode: Literal['message','call'] = 'message'
    preview: str = ''
    updated_at: str | None = None
    abandoned: bool = False
    awaiting_judgement: bool = False
    session_id: str
    scenario_title: str
    started_at: str
    ended_at: str | None = None
    outcome: Literal["safe", "scammed", "timeout"] | None = None
    total_score: int
    turn_count: int


class TranscriptMessage(BaseModel):
    created_at: str | None = None
    turn_no: int | None = None
    role: Literal["caller", "player"]
    text: str
    intent: Intent | None = None
    stage: str | None = None


class CallTranscriptResponse(BaseModel):
    interaction_mode: Literal['message','call'] = 'message'
    ended: bool = False
    abandoned: bool = False
    session_id: str
    scenario_title: str
    messages: list[TranscriptMessage] = Field(default_factory=list)


class IntentCandidate(BaseModel):
    candidate_id: int
    session_id: str
    scenario_title: str
    stage: str
    requested_action: str
    caller_text: str
    user_text_masked: str
    detected_intent: Intent
    source_reason: Literal["unknown", "player_flagged"]
    suggested_intent: Intent | None = None
    suggested_phrase: str | None = None
    confidence: float | None = None
    rationale: str | None = None
    analysis_status: Literal["pending", "analyzed", "not_configured", "failed"]
    created_at: str


class ApproveIntentCandidateRequest(BaseModel):
    intent: Intent
    phrase: str = Field(min_length=2, max_length=120)


class IntentCandidateActionResponse(BaseModel):
    candidate_id: int
    review_status: Literal["approved", "rejected"]
    intent_rule_id: int | None = None


class FlagTurnResponse(BaseModel):
    session_id: str
    turn_no: int
    queued_for_review: bool
