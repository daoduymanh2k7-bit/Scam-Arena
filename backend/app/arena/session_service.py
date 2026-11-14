from __future__ import annotations

import random

from app.arena.conversation_engine import get_reply
from app.arena.scenario_loader import Scenario, load_scenarios
from app.arena.scorer import improvement_tip, score_session
from app.schemas import CallSession, DialogueTurn, ReplyResponse


def list_scenarios() -> list[dict[str, str]]:
    return [
        {"key": item.key, "label": item.label}
        for item in load_scenarios().values()
        if item.status == "published"
    ]


def random_scenario() -> dict[str, str]:
    published = [item for item in load_scenarios().values() if item.status == "published"]
    if not published:
        raise LookupError("Chưa có kịch bản nào được xuất bản.")
    scenario = random.choice(published)
    return {"key": scenario.key, "label": scenario.label}


def reply(
    scenario_key: str,
    history: list[DialogueTurn],
    user_text: str,
    stage_id: str | None,
    stage_turn_count: int,
) -> ReplyResponse:
    scenarios = load_scenarios()
    if scenario_key not in scenarios:
        raise KeyError(scenario_key)
    if scenarios[scenario_key].status != "published":
        raise KeyError(scenario_key)
    user_turns = sum(turn.role == "user" for turn in history) + bool(user_text.strip())
    return get_reply(scenarios[scenario_key], stage_id, stage_turn_count, user_text, user_turns)


def score(session_id: str, scenario_type: str, transcript: list[DialogueTurn]) -> CallSession:
    return score_session(session_id, scenario_type, transcript)


def tip(mistake: str) -> str:
    return improvement_tip(mistake)
