from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class DialogueTurn(BaseModel):
    role: Literal["user", "scammer_ai"]
    text: str
    elapsed_seconds: float | None = None


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


class ScoreRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=100)
    scenario_type: str = Field(min_length=1, max_length=120)
    transcript: list[DialogueTurn] = Field(max_length=100)


class SpeakRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
