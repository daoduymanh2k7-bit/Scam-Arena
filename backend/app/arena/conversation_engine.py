from __future__ import annotations

from app.arena.intent_detector import Intent, detect_intent
from app.arena.scenario_models import TERMINAL_STAGES, Scenario, Stage
from app.schemas import ReplyResponse

MAX_SESSION_USER_TURNS = 40

_TERMINAL_OUTCOMES = {
    "END_SAFE": ("safe", "(Cuộc gọi giả lập kết thúc: bạn đã chọn cách xử lý an toàn.)"),
    "END_UNSAFE": ("unsafe", "(Cuộc gọi giả lập kết thúc sau một hành động rủi ro.)"),
    "END_NEUTRAL": ("neutral", "(Cuộc gọi giả lập kết thúc; chưa đủ thông tin để đánh giá.)"),
}


def _stage_map(scenario: Scenario) -> dict[str, Stage]:
    return {stage.id: stage for stage in scenario.stages}


def _fallback_line(stage: Stage, stage_turn_count: int) -> str:
    return stage.fallback_lines[stage_turn_count % len(stage.fallback_lines)]


def _finish(terminal_id: str, intent: Intent | None = None, matched_rule: str | None = None, evidence: str | None = None) -> ReplyResponse:
    outcome, line = _TERMINAL_OUTCOMES[terminal_id]
    return ReplyResponse(
        reply=line,
        intent=intent,
        matched_rule=matched_rule,
        evidence=evidence,
        current_stage_id=None,
        stage_turn_count=0,
        finished=True,
        outcome=outcome,
    )


def _target_reply(
    scenario: Scenario,
    target_id: str,
    *,
    intent: Intent,
    matched_rule: str | None,
    evidence: str | None,
    fallback: str | None = None,
    next_stage_turn_count: int = 0,
) -> ReplyResponse:
    if target_id in TERMINAL_STAGES:
        response = _finish(target_id, intent, matched_rule, evidence)
        if fallback:
            response.reply = f"{fallback} {response.reply}"
        return response

    target = _stage_map(scenario)[target_id]
    line = f"{fallback} {target.opening_line}" if fallback else target.opening_line
    return ReplyResponse(
        reply=line,
        intent=intent,
        matched_rule=matched_rule,
        evidence=evidence,
        current_stage_id=target.id,
        stage_turn_count=next_stage_turn_count,
        finished=False,
        outcome=None,
    )


def get_reply(
    scenario: Scenario,
    stage_id: str | None,
    stage_turn_count: int,
    user_text: str,
    total_user_turns: int,
) -> ReplyResponse:
    """Advance a scenario graph by one user answer.

    With no ``stage_id`` this returns the scenario's opening line. Subsequent
    calls classify the answer against the current stage and follow its edge.
    Client-provided history is used only for a global turn cap; stage IDs are
    checked against the loaded scenario before they are followed.
    """
    stages = _stage_map(scenario)
    if stage_id is None:
        opening = stages[scenario.start_stage_id]
        return ReplyResponse(
            reply=opening.opening_line,
            current_stage_id=opening.id,
            stage_turn_count=0,
        )

    if total_user_turns >= MAX_SESSION_USER_TURNS:
        return _finish("END_NEUTRAL")
    if stage_id not in stages:
        raise KeyError(f"Kịch bản '{scenario.id}' không có stage '{stage_id}'.")
    if not user_text.strip():
        raise ValueError("Câu trả lời không được để trống.")

    current = stages[stage_id]
    result = detect_intent(
        user_text,
        current.requested_action,
    )
    transition = next(
        (item for item in current.transitions if item.on_intent == result.intent),
        None,
    )
    target_id = transition.next_stage_id if transition else current.default_next_stage_id

    next_stage_turn_count = stage_turn_count + 1
    fallback = _fallback_line(current, stage_turn_count) if result.intent == Intent.UNKNOWN else None

    # A self-loop is bounded by max_turns and then redirected to the timeout edge.
    if target_id == current.id and next_stage_turn_count >= current.max_turns:
        target_id = current.timeout_next_stage_id
        if fallback is None:
            fallback = _fallback_line(current, stage_turn_count)

    if target_id == current.id:
        return ReplyResponse(
            reply=fallback or _fallback_line(current, stage_turn_count),
            intent=result.intent,
            matched_rule=result.matched_rule,
            evidence=result.evidence,
            current_stage_id=current.id,
            stage_turn_count=next_stage_turn_count,
        )

    return _target_reply(
        scenario,
        target_id,
        intent=result.intent,
        matched_rule=result.matched_rule,
        evidence=result.evidence,
        fallback=fallback,
    )
