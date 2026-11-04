from __future__ import annotations

import random

from app.arena.conversation_engine import get_reply
from app.arena.scenario_loader import Scenario, load_scenarios
from app.arena.scorer import improvement_tip, score_session
from app.schemas import CallSession, DialogueTurn


def list_scenarios() -> list[dict[str, str]]:
    return [{"key": item.key, "label": item.label} for item in load_scenarios().values()]


def random_scenario() -> dict[str, str]:
    scenario = random.choice(list(load_scenarios().values()))
    return {"key": scenario.key, "label": scenario.label}


def reply(scenario_key: str, history: list[DialogueTurn], user_text: str) -> str:
    scenarios = load_scenarios()
    if scenario_key not in scenarios:
        raise KeyError(scenario_key)
    scammer_turns = sum(turn.role == "scammer_ai" for turn in history)
    return get_reply(scenarios[scenario_key], scammer_turns, user_text)


def score(session_id: str, scenario_type: str, transcript: list[DialogueTurn]) -> CallSession:
    return score_session(session_id, scenario_type, transcript)


def tip(mistake: str) -> str:
    return improvement_tip(mistake)
