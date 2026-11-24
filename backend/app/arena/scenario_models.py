from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.arena.intent_detector import Intent, RequestedAction

TERMINAL_STAGES = {"END_SAFE", "END_UNSAFE", "END_NEUTRAL"}


class Persona(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=80)
    claimed_role: str = Field(min_length=2, max_length=120)
    speaking_style: str = Field(min_length=5, max_length=300)
    pressure_level: int = Field(ge=1, le=5)


class Transition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    on_intent: Intent
    next_stage_id: str = Field(pattern=r"^(?:[a-z][a-z0-9_-]{0,49}|END_(?:SAFE|UNSAFE|NEUTRAL))$")
    admin_note: str | None = Field(default=None, max_length=300)


class Stage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,49}$")
    objective: str = Field(min_length=5, max_length=300)
    tactics: list[str] = Field(max_length=8)
    requested_action: RequestedAction
    opening_line: str = Field(min_length=5, max_length=600)
    fallback_lines: list[str] = Field(min_length=1, max_length=5)
    transitions: list[Transition] = Field(min_length=1, max_length=8)
    default_next_stage_id: str = Field(pattern=r"^(?:[a-z][a-z0-9_-]{0,49}|END_(?:SAFE|UNSAFE|NEUTRAL))$")
    max_turns: int = Field(ge=1, le=10)
    timeout_next_stage_id: str = Field(pattern=r"^(?:[a-z][a-z0-9_-]{0,49}|END_(?:SAFE|UNSAFE|NEUTRAL))$")


class RedFlag(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,49}$")
    stage_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,49}$")
    title: str = Field(min_length=3, max_length=120)
    explanation: str = Field(min_length=10, max_length=600)
    severity: Literal["low", "medium", "high"]


class ScoreRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Intent
    stage_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{0,49}$")
    points_delta: int = Field(ge=-100, le=100)
    feedback: str = Field(min_length=5, max_length=500)
    critical: bool


class Scoring(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_score: int = Field(ge=0, le=100)
    rules: list[ScoreRule] = Field(min_length=1, max_length=30)


class CaseBlueprint(BaseModel):
    model_config = ConfigDict(extra='forbid')
    evidence: str = Field(min_length=10,max_length=1500)
    official: str = Field(min_length=10,max_length=1500)


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    scenario_kind: Literal['fraud', 'benign'] = 'fraud'
    family: str = Field(default='legacy', min_length=2, max_length=80)
    case_blueprint: CaseBlueprint | None = None
    id: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=80)
    version: int = Field(ge=1)
    status: Literal["draft", "published", "archived"]
    title: str = Field(min_length=3, max_length=120)
    category: Literal[
        "bank_impersonation", "law_enforcement_impersonation", "fake_prize",
        "fake_investment", "delivery_scam", "account_takeover", "recruitment_scam",
        "fake_payment", "rental_deposit", "loan_scam", "online_marketplace", "other",
    ]
    difficulty: Literal["beginner", "intermediate", "advanced"]
    locale: Literal["vi-VN"]
    summary: str = Field(min_length=10, max_length=500)
    user_context: str = Field(min_length=10, max_length=1000)
    persona: Persona
    start_stage_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,49}$")
    stages: list[Stage] = Field(min_length=1, max_length=30)
    red_flags: list[RedFlag] = Field(max_length=20)
    scoring: Scoring
    lesson_summary: str = Field(min_length=10, max_length=1500)
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None

    @property
    def label(self) -> str:
        """Compatibility alias for the existing scenario picker contract."""
        return self.title

    @property
    def key(self) -> str:
        """Compatibility alias for the existing scenario picker contract."""
        return self.id
