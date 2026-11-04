from __future__ import annotations

from app.arena.intent_detector import is_refusal
from app.arena.scenario_loader import Scenario


def get_reply(scenario: Scenario, scammer_turns: int, user_text: str) -> str:
    if user_text.strip() and is_refusal(user_text):
        return "(Người gọi kết thúc cuộc gọi khi bạn yêu cầu xác minh — bạn đã xử lý an toàn.)"
    if scammer_turns >= len(scenario.script):
        return "(Kịch bản demo đã kết thúc.)"
    return scenario.script[scammer_turns]
