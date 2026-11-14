from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from app.arena.intent_detector import RequestedAction, detect_intent
from app.arena.scorer import improvement_tip
from app.database import get_connection_pool
from app.schemas import (
    CallSummaryResponse,
    CallTurnResponse,
    RiskLevel,
    ScorerFlag,
    SessionRedFlag,
    SessionFeedback,
    StartCallResponse,
    CallHistoryItem,
    CallTranscriptResponse,
    TranscriptMessage,
    IntentCandidate,
    ApproveIntentCandidateRequest,
    IntentCandidateActionResponse,
    FlagTurnResponse,
)
from app.arena.normalization import normalize_phrase
from app.database import clear_intent_rule_cache


def list_scenarios() -> list[dict[str, str]]:
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT scenario_name, title FROM scenarios WHERE status = 'published' ORDER BY scenario_id"
        )
        return [{"key": row["scenario_name"], "label": row["title"]} for row in cursor.fetchall()]


def random_scenario() -> dict[str, str]:
    import random

    scenarios = list_scenarios()
    if not scenarios:
        raise LookupError("Chưa có kịch bản nào được xuất bản.")
    return random.choice(scenarios)


def start_call(scenario_key: str) -> StartCallResponse:
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT scenario_id, scenario_name, title, base_score
            FROM scenarios
            WHERE scenario_name = %s AND status = 'published'
            """,
            (scenario_key,),
        )
        scenario = cursor.fetchone()
        if scenario is None:
            raise KeyError(scenario_key)

        cursor.execute(
            """
            SELECT node_id, node_key, stage, text
            FROM dialogue_nodes
            WHERE scenario_id = %s AND is_start = TRUE
            """,
            (scenario["scenario_id"],),
        )
        node = cursor.fetchone()
        if node is None:
            raise RuntimeError(f"Kịch bản '{scenario_key}' chưa có node bắt đầu.")

        cursor.execute(
            """
            INSERT INTO call_sessions (scenario_id, current_node_id, total_score)
            VALUES (%s, %s, %s)
            RETURNING session_id
            """,
            (scenario["scenario_id"], node["node_id"], scenario["base_score"]),
        )
        session_id = str(cursor.fetchone()["session_id"])
        return StartCallResponse(
            session_id=session_id,
            scenario_key=scenario["scenario_name"],
            scenario_title=scenario["title"],
            bot_text=node["text"],
            stage=node["stage"],
        )


def _masked_text(text: str) -> str:
    """Mask long digit sequences and email addresses before persistence or LLM review."""
    masked = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[email]", text)
    return re.sub(r"\d{4,}", "****", masked)


def _terminal_node(cursor: Any, scenario_id: int, outcome: str) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT node_id AS target_node_id, node_key AS target_node_key,
               stage AS target_stage, text AS target_text,
               is_terminal AS target_is_terminal, outcome AS target_outcome
        FROM dialogue_nodes
        WHERE scenario_id = %s AND is_terminal = TRUE AND outcome = %s
        LIMIT 1
        """,
        (scenario_id, outcome),
    )
    return cursor.fetchone()


def submit_turn(session_id: UUID, user_text: str, elapsed_seconds: float | None) -> CallTurnResponse:
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT cs.session_id, cs.scenario_id, cs.current_node_id, cs.ended_at,
                   cs.outcome, cs.total_score, cs.turn_no, cs.unknown_count,
                   s.scenario_name, s.max_turns,
                   n.node_key, n.stage, n.text AS node_text, n.reprompt_text,
                   n.requested_action, n.max_turns AS node_max_turns,
                   n.timeout_next_node_id, n.is_terminal
            FROM call_sessions AS cs
            JOIN scenarios AS s ON s.scenario_id = cs.scenario_id
            JOIN dialogue_nodes AS n ON n.node_id = cs.current_node_id
            WHERE cs.session_id = %s
            FOR UPDATE OF cs
            """,
            (session_id,),
        )
        session = cursor.fetchone()
        if session is None:
            raise KeyError(str(session_id))
        if session["ended_at"] is not None:
            raise ValueError("Phiên gọi này đã kết thúc.")
        if session["is_terminal"]:
            raise ValueError("Phiên gọi đang ở node kết thúc.")
        if not user_text.strip():
            raise ValueError("Câu trả lời không được để trống.")

        result = detect_intent(
            user_text,
            RequestedAction(session["requested_action"]),
            scenario_id=session["scenario_id"],
        )
        intent = result.intent.value
        intent_method = (
            "rasa" if result.matched_rule and result.matched_rule.startswith("rasa:")
            else "rule" if result.matched_rule else "fallback"
        )
        next_turn_no = session["turn_no"] + 1
        unknown_count = session["unknown_count"]
        score_delta = 0
        feedback = None
        critical = False
        target = None

        cursor.execute(
            """
            SELECT transition.score_delta, transition.feedback, transition.critical,
                   destination.node_id AS target_node_id, destination.node_key AS target_node_key,
                   destination.stage AS target_stage, destination.text AS target_text,
                   destination.is_terminal AS target_is_terminal, destination.outcome AS target_outcome
            FROM dialogue_transitions AS transition
            JOIN dialogue_nodes AS destination ON destination.node_id = transition.to_node_id
            WHERE transition.from_node_id = %s AND transition.intent = %s
            """,
            (session["current_node_id"], intent),
        )
        transition = cursor.fetchone()

        if transition is not None:
            target = transition
            score_delta = transition["score_delta"]
            feedback = transition["feedback"]
            critical = transition["critical"]
            unknown_count = 0
        else:
            cursor.execute(
                "SELECT end_outcome, score_delta, feedback, critical FROM intent_defaults WHERE intent = %s",
                (intent,),
            )
            default = cursor.fetchone()
            if default is not None:
                score_delta = default["score_delta"]
                feedback = default["feedback"]
                critical = default["critical"]
                if default["end_outcome"] is not None:
                    target = _terminal_node(cursor, session["scenario_id"], default["end_outcome"])
                else:
                    unknown_count += 1
            else:
                unknown_count += 1

            if target is None:
                cursor.execute(
                    "SELECT count(*) AS visit_count FROM call_turns WHERE session_id = %s AND node_id = %s",
                    (session_id, session["current_node_id"]),
                )
                visit_count = cursor.fetchone()["visit_count"] + 1
                if visit_count >= session["node_max_turns"] and session["timeout_next_node_id"] is not None:
                    cursor.execute(
                        """
                        SELECT node_id AS target_node_id, node_key AS target_node_key,
                               stage AS target_stage, text AS target_text,
                               is_terminal AS target_is_terminal, outcome AS target_outcome
                        FROM dialogue_nodes WHERE node_id = %s
                        """,
                        (session["timeout_next_node_id"],),
                    )
                    target = cursor.fetchone()
                    unknown_count = 0
                elif unknown_count >= 2 or next_turn_no >= session["max_turns"]:
                    target = _terminal_node(cursor, session["scenario_id"], "timeout")
                    unknown_count = 0

        if target is None:
            target_node_id = session["current_node_id"]
            bot_text = session["reprompt_text"] or session["node_text"]
            stage = session["stage"]
            outcome = None
            ended = False
        else:
            target_node_id = target["target_node_id"]
            bot_text = target["target_text"]
            stage = target["target_stage"]
            outcome = target["target_outcome"] if target["target_is_terminal"] else None
            ended = outcome is not None

        total_score = max(0, min(100, session["total_score"] + score_delta))
        cursor.execute(
            """
            INSERT INTO call_turns
                (session_id, turn_no, node_id, user_text_masked, intent, intent_method,
                 score_delta, feedback, critical, elapsed_seconds, bot_reply_text)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING turn_id
            """,
            (
                session_id, next_turn_no, session["current_node_id"], _masked_text(user_text),
                intent, intent_method, score_delta,
                feedback, critical, elapsed_seconds, bot_text,
            ),
        )
        turn_id = cursor.fetchone()["turn_id"]
        if intent == "unknown":
            cursor.execute(
                """INSERT INTO intent_review_candidates
                       (session_id, turn_id, scenario_id, stage, requested_action,
                        caller_text, user_text_masked, detected_intent, source_reason)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'unknown')""",
                (
                    session_id, turn_id, session["scenario_id"], session["stage"],
                    session["requested_action"], session["node_text"], _masked_text(user_text), intent,
                ),
            )
        cursor.execute(
            """
            UPDATE call_sessions
            SET current_node_id = %s,
                turn_no = %s,
                unknown_count = %s,
                total_score = %s,
                outcome = COALESCE(%s::text, outcome),
                ended_at = CASE WHEN %s::text IS NULL THEN ended_at ELSE now() END
            WHERE session_id = %s
            """,
            (target_node_id, next_turn_no, unknown_count, total_score, outcome, outcome, session_id),
        )

        return CallTurnResponse(
            bot_text=bot_text,
            intent=result.intent,
            intent_method=intent_method,
            stage=stage,
            ended=ended,
            outcome=outcome,
            score=total_score,
            score_delta=score_delta,
            feedback=feedback,
        )


def finish_call(session_id: UUID) -> None:
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE call_sessions AS session
            SET current_node_id = COALESCE(
                    (SELECT node_id FROM dialogue_nodes
                     WHERE scenario_id = session.scenario_id AND is_terminal AND outcome = 'timeout' LIMIT 1),
                    current_node_id
                ),
                outcome = COALESCE(outcome, 'timeout'),
                ended_at = COALESCE(ended_at, now())
            WHERE session_id = %s
            RETURNING session_id
            """,
            (session_id,),
        )
        if cursor.fetchone() is None:
            raise KeyError(str(session_id))


def get_call_summary(session_id: UUID) -> CallSummaryResponse:
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT cs.session_id, cs.outcome, cs.total_score, cs.turn_no,
                   s.scenario_name, s.title, s.payload->>'lesson_summary' AS lesson_summary,
                   s.payload->'red_flags' AS red_flags
            FROM call_sessions AS cs
            JOIN scenarios AS s ON s.scenario_id = cs.scenario_id
            WHERE cs.session_id = %s
            """,
            (session_id,),
        )
        session = cursor.fetchone()
        if session is None:
            raise KeyError(str(session_id))

        cursor.execute(
            """
            SELECT turns.turn_no, turns.intent, turns.feedback, turns.score_delta,
                   turns.critical, turns.elapsed_seconds, nodes.stage, nodes.tactic
            FROM call_turns AS turns
            JOIN dialogue_nodes AS nodes ON nodes.node_id = turns.node_id
            WHERE turns.session_id = %s
            ORDER BY turns.turn_no
            """,
            (session_id,),
        )
        turns = cursor.fetchall()

    score = session["total_score"]
    badge = "🏆 Cảnh giác cao" if score >= 80 else "🥈 Cần luyện thêm" if score >= 50 else "⚠️ Dễ bị lừa"
    feedback = [
        SessionFeedback(
            turn_no=turn["turn_no"],
            intent=turn["intent"],
            feedback=turn["feedback"],
            score_delta=turn["score_delta"],
            critical=turn["critical"],
            stage=turn["stage"],
            tactic=turn["tactic"],
        )
        for turn in turns if turn["feedback"]
    ]
    mistakes = [
        ScorerFlag(
            turn_index=turn["turn_no"] - 1,
            mistake=turn["feedback"],
            severity=RiskLevel.HIGH if turn["critical"] else RiskLevel.MEDIUM,
        )
        for turn in turns if turn["feedback"] and (turn["critical"] or turn["score_delta"] < 0)
    ]
    latencies = [turn["elapsed_seconds"] for turn in turns if turn["elapsed_seconds"] is not None]
    return CallSummaryResponse(
        session_id=str(session["session_id"]),
        scenario_key=session["scenario_name"],
        scenario_title=session["title"],
        outcome=session["outcome"],
        total_score=score,
        badge=badge,
        avg_response_latency=sum(latencies) / len(latencies) if latencies else None,
        turn_count=session["turn_no"],
        lesson_summary=session["lesson_summary"],
        feedback=feedback,
        mistakes=mistakes,
        red_flags=[SessionRedFlag.model_validate(flag) for flag in (session["red_flags"] or [])],
    )


def tip(mistake: str) -> str:
    return improvement_tip(mistake)


def list_call_history(limit: int = 30) -> list[CallHistoryItem]:
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT cs.session_id, s.title, cs.started_at, cs.ended_at,
                      cs.outcome, cs.total_score, cs.turn_no
               FROM call_sessions cs JOIN scenarios s ON s.scenario_id = cs.scenario_id
               ORDER BY cs.started_at DESC LIMIT %s""",
            (limit,),
        )
        return [
            CallHistoryItem(
                session_id=str(row["session_id"]), scenario_title=row["title"],
                started_at=row["started_at"].isoformat(),
                ended_at=row["ended_at"].isoformat() if row["ended_at"] else None,
                outcome=row["outcome"], total_score=row["total_score"], turn_count=row["turn_no"],
            )
            for row in cursor.fetchall()
        ]


def get_call_transcript(session_id: UUID) -> CallTranscriptResponse:
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT cs.session_id, s.title, start_node.text AS opening_line
               FROM call_sessions cs
               JOIN scenarios s ON s.scenario_id = cs.scenario_id
               JOIN dialogue_nodes start_node
                 ON start_node.scenario_id = cs.scenario_id AND start_node.is_start = TRUE
               WHERE cs.session_id = %s""",
            (session_id,),
        )
        session = cursor.fetchone()
        if session is None:
            raise KeyError(str(session_id))
        cursor.execute(
            """SELECT turns.turn_no, turns.user_text_masked, turns.intent,
                      turns.bot_reply_text, nodes.stage
               FROM call_turns turns JOIN dialogue_nodes nodes ON nodes.node_id = turns.node_id
               WHERE turns.session_id = %s ORDER BY turns.turn_no""",
            (session_id,),
        )
        turns = cursor.fetchall()

    messages = [TranscriptMessage(role="caller", text=session["opening_line"])]
    for turn in turns:
        messages.append(TranscriptMessage(
            turn_no=turn["turn_no"], role="player", text=turn["user_text_masked"],
            intent=turn["intent"], stage=turn["stage"],
        ))
        if turn["bot_reply_text"]:
            messages.append(TranscriptMessage(
                turn_no=turn["turn_no"], role="caller", text=turn["bot_reply_text"], stage=turn["stage"],
            ))
    return CallTranscriptResponse(
        session_id=str(session["session_id"]), scenario_title=session["title"], messages=messages,
    )


def list_intent_candidates(status: str = "pending") -> list[IntentCandidate]:
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT c.candidate_id, c.session_id, s.title AS scenario_title, c.stage,
                      c.requested_action, c.caller_text, c.user_text_masked,
                      c.detected_intent, c.source_reason,
                      c.suggested_intent, c.suggested_phrase, c.confidence, c.rationale,
                      c.analysis_status, c.created_at
               FROM intent_review_candidates c
               JOIN scenarios s ON s.scenario_id = c.scenario_id
               WHERE c.review_status = %s
               ORDER BY c.created_at DESC LIMIT 100""",
            (status,),
        )
        return [IntentCandidate(
            candidate_id=row["candidate_id"], session_id=str(row["session_id"]),
            scenario_title=row["scenario_title"], stage=row["stage"],
            requested_action=row["requested_action"], caller_text=row["caller_text"],
            user_text_masked=row["user_text_masked"], suggested_intent=row["suggested_intent"],
            detected_intent=row["detected_intent"], source_reason=row["source_reason"],
            suggested_phrase=row["suggested_phrase"], confidence=row["confidence"],
            rationale=row["rationale"], analysis_status=row["analysis_status"],
            created_at=row["created_at"].isoformat(),
        ) for row in cursor.fetchall()]


def approve_intent_candidate(
    candidate_id: int, request: ApproveIntentCandidateRequest,
) -> IntentCandidateActionResponse:
    if request.intent.value == "unknown":
        raise ValueError("Không thể thêm nhãn unknown thành luật nhận diện.")
    phrase = _masked_text(request.phrase).strip()
    phrase_norm = normalize_phrase(phrase)
    if len(phrase_norm) < 2:
        raise ValueError("Cụm từ sau khi chuẩn hóa quá ngắn.")
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT scenario_id FROM intent_review_candidates
               WHERE candidate_id = %s AND review_status = 'pending' FOR UPDATE""",
            (candidate_id,),
        )
        candidate = cursor.fetchone()
        if candidate is None:
            raise KeyError(candidate_id)
        cursor.execute(
            """SELECT id FROM intent_phrase_rules
               WHERE intent = %s AND phrase_norm = %s AND scenario_id = %s
               ORDER BY id LIMIT 1""",
            (request.intent.value, phrase_norm, candidate["scenario_id"]),
        )
        existing = cursor.fetchone()
        if existing:
            rule_id = existing["id"]
        else:
            cursor.execute(
                """INSERT INTO intent_phrase_rules
                       (scenario_id, intent, phrase, phrase_norm, match_type, priority, enabled)
                   VALUES (%s, %s, %s, %s, 'contains', 75, TRUE) RETURNING id""",
                (candidate["scenario_id"], request.intent.value, phrase, phrase_norm),
            )
            rule_id = cursor.fetchone()["id"]
        cursor.execute(
            """UPDATE intent_review_candidates SET review_status = 'approved', reviewed_at = now()
               WHERE candidate_id = %s""",
            (candidate_id,),
        )
    clear_intent_rule_cache()
    return IntentCandidateActionResponse(
        candidate_id=candidate_id, review_status="approved", intent_rule_id=rule_id,
    )


def reject_intent_candidate(candidate_id: int) -> IntentCandidateActionResponse:
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """UPDATE intent_review_candidates SET review_status = 'rejected', reviewed_at = now()
               WHERE candidate_id = %s AND review_status = 'pending' RETURNING candidate_id""",
            (candidate_id,),
        )
        if cursor.fetchone() is None:
            raise KeyError(candidate_id)
    return IntentCandidateActionResponse(candidate_id=candidate_id, review_status="rejected")


def flag_turn_for_review(session_id: UUID, turn_no: int) -> FlagTurnResponse:
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT s.scenario_id, n.stage, n.requested_action, n.text AS caller_text,
                      t.turn_id, t.intent, t.user_text_masked
               FROM call_sessions s
               JOIN call_turns t ON t.session_id = s.session_id
               JOIN dialogue_nodes n ON n.node_id = t.node_id
               WHERE s.session_id = %s AND t.turn_no = %s""",
            (session_id, turn_no),
        )
        row = cursor.fetchone()
        if row is None:
            raise KeyError(turn_no)
        cursor.execute(
            """INSERT INTO intent_review_candidates
                   (session_id, turn_id, scenario_id, stage, requested_action,
                    caller_text, user_text_masked, detected_intent, source_reason)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (turn_id) DO UPDATE SET
                   source_reason = CASE
                       WHEN intent_review_candidates.detected_intent = 'unknown' THEN 'unknown'
                       ELSE 'player_flagged'
                   END,
                   analysis_status = CASE
                       WHEN intent_review_candidates.review_status = 'pending' THEN 'pending'
                       ELSE intent_review_candidates.analysis_status
                   END
               RETURNING candidate_id""",
            (
                session_id, row["turn_id"], row["scenario_id"], row["stage"],
                row["requested_action"], row["caller_text"], row["user_text_masked"],
                row["intent"], "unknown" if row["intent"] == "unknown" else "player_flagged",
            ),
        )
    return FlagTurnResponse(session_id=str(session_id), turn_no=turn_no, queued_for_review=True)
