from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from app.arena.intent_detector import Intent, RequestedAction, detect_intent
from app.arena.intent_reclassifier import reclassify_unknown
from app.arena.conversation_memory import memory_context, invalidate_memory
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
    LinePreferenceResponse,
    RegeneratedLineResponse,
    TranscriptMessage,
    IntentCandidate,
    ApproveIntentCandidateRequest,
    IntentCandidateActionResponse,
    FlagTurnResponse,
)
from app.arena.normalization import normalize_phrase
from app.database import clear_intent_rule_cache
from app.arena.line_generator import resolve_bot_line, regenerate_line_for_turn
from app.arena.phone_dialogue import phone_opening, clarification_fallback
from app.arena.scenario_versions import session_seed
from app.arena.practice_catalog import render
import logging

logger = logging.getLogger(__name__)


def list_scenarios() -> list[dict[str, str]]:
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT s.scenario_name,v.definition->>'title' AS title FROM scenarios s
               JOIN scenario_versions v ON v.version_id=s.active_version_id
               WHERE s.status = 'published' AND s.family NOT IN ('delivery','appointment','support') ORDER BY s.scenario_id"""
        )
        return [{"key": row["scenario_name"], "label": row["title"]} for row in cursor.fetchall()] + [
            {'key':'mixed-any','label':'Cuộc gọi bất ngờ — mọi chủ đề'},
            {'key':'mixed-delivery','label':'Giao hàng — cuộc gọi bất ngờ'},
            {'key':'mixed-appointment','label':'Đặt lịch — cuộc gọi bất ngờ'},
            {'key':'mixed-support','label':'Hỗ trợ — cuộc gọi bất ngờ'}]


def list_admin_scenario_graphs() -> list[dict[str, Any]]:
    """Return the stored scenario and dialogue graph for the admin visualizer."""
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT s.scenario_id,s.scenario_name,v.definition->>'title' AS title,s.status,
                      v.definition->'payload' AS payload,s.active_version_id,v.revision,s.scenario_kind,s.family
               FROM scenarios s JOIN scenario_versions v ON v.version_id=s.active_version_id ORDER BY s.scenario_id"""
        )
        scenarios = cursor.fetchall()
        result = []
        for scenario in scenarios:
            cursor.execute(
                """SELECT n.node_id,n.node_key,n.stage,n.objective,n.tactic,n.requested_action,
                          n.max_turns,n.is_start,n.is_terminal,n.outcome,n.timeout_next_node_id,
                          COALESCE(jsonb_agg(jsonb_build_object(
                            'line_id',l.line_id,'line_text',l.line_text,'source',l.source,
                            'intent',l.intent,'is_reprompt',l.is_reprompt,'enabled',l.enabled,
                            'preference_score',l.preference_score
                          ) ORDER BY l.source,l.intent NULLS FIRST,l.is_reprompt,l.line_id)
                          FILTER (WHERE l.line_id IS NOT NULL), '[]'::jsonb) AS lines
                   FROM dialogue_nodes n
                   LEFT JOIN dialogue_lines l ON l.node_id=n.node_id
                   WHERE n.scenario_id=%s AND n.scenario_version_id=%s
                   GROUP BY n.node_id ORDER BY n.is_start DESC,n.node_id""",
                (scenario["scenario_id"],scenario['active_version_id']),
            )
            nodes = cursor.fetchall()
            cursor.execute(
                """SELECT t.from_node_id,t.intent,t.to_node_id,t.score_delta,t.critical,t.feedback
                   FROM dialogue_transitions t
                   JOIN dialogue_nodes n ON n.node_id=t.from_node_id
                   WHERE n.scenario_id=%s AND n.scenario_version_id=%s ORDER BY t.from_node_id,t.intent""",
                (scenario["scenario_id"],scenario['active_version_id']),
            )
            transitions = cursor.fetchall()
            payload = scenario["payload"] if isinstance(scenario["payload"], dict) else {}
            result.append({
                "key": scenario["scenario_name"], "title": scenario["title"], "status": scenario["status"],
                "version_id": scenario['active_version_id'], "revision": scenario['revision'],
                "scenario_kind": scenario['scenario_kind'], "family": scenario['family'],
                "summary": payload.get("summary", ""), "persona": payload.get("persona", {}),
                "lesson_summary": payload.get("lesson_summary", ""), "scoring": payload.get("scoring", {}),
                "red_flags": payload.get("red_flags", []),
                "nodes": [dict(row) for row in nodes],
                "transitions": [dict(row) for row in transitions],
            })
        return result


def random_scenario() -> dict[str, str]:
    import random

    scenarios = [item for item in list_scenarios() if not item['key'].startswith('mixed-')]
    if not scenarios:
        raise LookupError("Chưa có kịch bản nào được xuất bản.")
    return random.choice(scenarios)


def start_call(scenario_key: str, user_id: str, interaction_mode: str = "message", practice_difficulty: str = 'adaptive', exercise_mode: str = 'training') -> StartCallResponse:
    requested_key=scenario_key
    mixed=scenario_key.startswith('mixed-')
    if mixed and interaction_mode!='call': raise ValueError('Cuộc gọi bất ngờ dùng trong chế độ Cuộc gọi.')
    seed=session_seed()
    if exercise_mode not in {'training','assessment'}: raise ValueError('Chế độ không hợp lệ.')
    if exercise_mode=='assessment' and not mixed: raise ValueError('Bài đánh giá phải chọn cuộc gọi ngẫu nhiên.')
    if interaction_mode not in {"message", "call"}:
        raise ValueError("Chế độ tương tác không hợp lệ.")
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        if mixed:
            from app.arena.practice_selector import select
            choice,level=select(cursor,user_id,requested_key.removeprefix('mixed-'),practice_difficulty,seed)
            scenario_key=choice['scenario_name']

        cursor.execute(
            """
            SELECT s.scenario_id,s.scenario_name,v.version_id,v.definition->>'title' AS title,
                   (v.definition->>'base_score')::integer AS base_score,v.definition
            FROM scenarios s JOIN scenario_versions v ON v.version_id=s.active_version_id
            WHERE s.scenario_name = %s AND s.status = 'published' AND v.status='published'
            """,
            (scenario_key,),
        )
        scenario = cursor.fetchone()
        if scenario is None:
            raise KeyError(scenario_key)
        if scenario['definition'].get('family') in {'delivery','appointment','support'} and interaction_mode!='call':
            raise ValueError('Tình huống này cần các tương tác trong chế độ Cuộc gọi.')

        cursor.execute(
            """
            SELECT node.node_id, node.node_key, node.stage
            FROM dialogue_nodes AS node
            WHERE node.scenario_version_id = %s AND node.is_start = TRUE
            """,
            (scenario["version_id"],),
        )
        node = cursor.fetchone()
        if node is None:
            raise RuntimeError(f"Kịch bản '{scenario_key}' chưa có node bắt đầu.")

        # Keep opener rotation tied to each persisted session while selecting the least-used variant.
        cursor.execute(
            """UPDATE dialogue_lines
               SET use_count = use_count + 1
               WHERE line_id = (
                   SELECT line_id FROM dialogue_lines
                   WHERE node_id = %s AND source = 'fixed' AND is_reprompt = FALSE
                     AND enabled = TRUE
                   ORDER BY use_count ASC, preference_score DESC, random(), line_id
                   LIMIT 1
               )
               RETURNING line_id, line_text""",
            (node["node_id"],),
        )
        opening_line = cursor.fetchone()
        if opening_line is None:
            raise RuntimeError(f"Kịch bản '{scenario_key}' chưa có lời mở đầu.")

        cursor.execute(
            """
            INSERT INTO call_sessions
                (scenario_id, current_node_id, total_score, user_id, interaction_mode, opening_line_id,scenario_version_id,random_seed,exercise_mode)
            VALUES (%s, %s, %s, %s, %s, %s,%s,%s,%s)
            RETURNING session_id
            """,
            (scenario["scenario_id"], node["node_id"], scenario["base_score"], user_id,
             interaction_mode, opening_line["line_id"],scenario['version_id'],seed,exercise_mode),
        )
        session_id = str(cursor.fetchone()["session_id"])
        from app.arena.practice_catalog import case_variables, render, FAMILIES,case_spec
        from psycopg.types.json import Jsonb
        variables=case_variables(seed)
        family=scenario['definition'].get('family')
        context=render(case_spec(scenario['definition'])['context'],variables) if family in FAMILIES else None
        cursor.execute('UPDATE call_sessions SET case_parameters=%s,world_state=%s WHERE session_id=%s',
                       (Jsonb(variables),Jsonb({'context':context,'case_schema':1,'selection':choice['_selection'] if mixed else None}),session_id))
        if interaction_mode=='call':
            from app.arena.notifications import seed as seed_inbox
            seed_inbox(cursor,session_id,scenario['definition'],variables)
        return StartCallResponse(
            session_id=session_id,
            scenario_key=requested_key if mixed else scenario["scenario_name"],
            scenario_title='Cuộc gọi dịch vụ' if mixed else scenario["title"],
            practice_context=context,
            bot_text=render(phone_opening(opening_line["line_text"]) if interaction_mode == "call" else opening_line["line_text"],variables),
            stage=node["stage"],
        )


def _masked_text(text: str) -> str:
    """Mask long digit sequences and email addresses before persistence or LLM review."""
    masked = re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "[email]", text)
    return re.sub(r"\d{4,}", "****", masked)


def _terminal_node(cursor: Any, scenario_version_id: int, outcome: str) -> dict[str, Any] | None:
    cursor.execute(
        """
        SELECT node.node_id AS target_node_id, node.node_key AS target_node_key,
               node.stage AS target_stage, line.line_text AS target_text,
               line.line_id AS target_line_id,
               node.is_terminal AS target_is_terminal, node.outcome AS target_outcome
        FROM dialogue_nodes AS node
        JOIN dialogue_lines AS line ON line.node_id = node.node_id
          AND line.source = 'fixed' AND line.is_reprompt = FALSE
        WHERE node.scenario_version_id = %s AND node.is_terminal = TRUE AND node.outcome = %s
        LIMIT 1
        """,
        (scenario_version_id, outcome),
    )
    return cursor.fetchone()


def submit_turn(session_id: UUID, user_text: str, elapsed_seconds: float | None, user_id: str) -> CallTurnResponse:
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT cs.session_id, cs.scenario_id, cs.scenario_version_id, cs.current_node_id, cs.ended_at,
                   cs.outcome, cs.total_score, cs.turn_no, cs.unknown_count, cs.interaction_mode,cs.case_parameters,cs.exercise_mode,
                   s.scenario_name, v.definition->>'title' AS scenario_title, v.definition->'payload' AS scenario_payload,
                   (v.definition->>'max_turns')::integer AS max_turns,v.definition->'intent_defaults' AS intent_defaults,
                   n.node_key, n.stage, n.objective, n.tactic,
                   main_line.line_text AS node_text, main_line.line_id AS node_line_id,
                   reprompt_line.line_text AS reprompt_text, reprompt_line.line_id AS reprompt_line_id,
                   n.requested_action, n.max_turns AS node_max_turns,
                   n.timeout_next_node_id, n.is_terminal,
                   COALESCE(previous_turn.bot_reply_text, opening_line.line_text, main_line.line_text, '') AS caller_line
            FROM call_sessions AS cs
            JOIN scenarios AS s ON s.scenario_id = cs.scenario_id
            JOIN scenario_versions v ON v.version_id=cs.scenario_version_id
            JOIN dialogue_nodes AS n ON n.node_id = cs.current_node_id
            LEFT JOIN dialogue_lines AS main_line ON main_line.node_id = n.node_id
              AND main_line.source = 'fixed' AND main_line.is_reprompt = FALSE
            LEFT JOIN dialogue_lines AS reprompt_line ON reprompt_line.node_id = n.node_id
              AND reprompt_line.source = 'fixed' AND reprompt_line.is_reprompt = TRUE
            LEFT JOIN dialogue_lines AS opening_line ON opening_line.line_id = cs.opening_line_id
            LEFT JOIN LATERAL (
                SELECT bot_reply_text FROM call_turns
                WHERE session_id = cs.session_id
                ORDER BY turn_no DESC LIMIT 1
            ) AS previous_turn ON TRUE
            WHERE cs.session_id = %s AND cs.user_id = %s
            FOR UPDATE OF cs
            """,
            (session_id, user_id),
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
        if session["interaction_mode"] == "call" and session["turn_no"] == 0:
            session["caller_line"] = phone_opening(session["caller_line"])
        session['caller_line']=render(session['caller_line'],session['case_parameters'])

        result = detect_intent(
            user_text,
            RequestedAction(session["requested_action"]),
            scenario_id=session["scenario_id"],
            caller_line=session["caller_line"],
        )
        intent = result.intent.value
        if (session['scenario_payload'].get('scenario_kind')=='benign' and session['requested_action']=='other'):
            normalized=normalize_phrase(user_text)
            scheduling=re.search(r'\b(?:nhan o|giao o|toi xuong|goi lai|hen luc|theo lich|de o)\b',normalized)
            if session['scenario_payload'].get('family') in {'delivery','appointment'}:
                scheduling=scheduling or re.search(r'\b(?:[0-2]?\d)\s*(?:gio|h)\b',normalized)
            if not re.search(r'\b(?:khong|chua|dung)\b',normalized) and scheduling:
                intent='comply'
        intent_method = (
            "rasa" if result.matched_rule and result.matched_rule.startswith("rasa:")
            else "rule" if result.matched_rule else "fallback"
        )
        caller_line = _masked_text(session["caller_line"])
        user_text_masked = _masked_text(user_text)
        from app.arena.service_completion import service_completion
        completion = service_completion(session.get('scenario_payload') or {}, session['node_key'],
            session['requested_action'], session['caller_line'], user_text, intent)
        if completion:
            intent = 'comply'
            intent_method = 'rule'
        if intent == 'unknown' and result.matched_rule is None:
            # Reclassify unresolved replies with masked context before transition lookup.
            try:
                scenario_payload = session.get("scenario_payload") or {}
                cursor.execute(
                    """SELECT turn_no, user_text_masked, bot_reply_text FROM call_turns
                       WHERE session_id=%s ORDER BY turn_no DESC LIMIT 3""",
                    (session_id,),
                )
                recent_turns = [
                    {
                        "player_text_masked": turn["user_text_masked"],
                        "caller_line": _masked_text(turn["bot_reply_text"] or ""),
                    }
                    for turn in reversed(cursor.fetchall())
                ]
                context = {
                    "interaction_mode": session["interaction_mode"],
                    "scenario_title": session["scenario_title"],
                    "scenario_category": scenario_payload.get("category") if isinstance(scenario_payload, dict) else None,
                    "persona": scenario_payload.get("persona") if isinstance(scenario_payload, dict) else None,
                    "user_context": scenario_payload.get("user_context") if isinstance(scenario_payload, dict) else None,
                    "stage": session["stage"],
                    "objective": session["objective"],
                    "tactics": session["tactic"],
                    "requested_action": session["requested_action"],
                    "caller_line": caller_line,
                    "recent_turns": recent_turns,
                    "player_text_masked": user_text_masked,
                }
                context.update(memory_context(cursor,session_id,before_turn=session["turn_no"]+1,
                    recent_start=max(1,session["turn_no"]-2)))
                revised_intent = reclassify_unknown(context=context)
                if revised_intent is not None:
                    intent = revised_intent.value
                    intent_method = "llm"
            except Exception as exc:
                # Supplemental classification must never break the deterministic game flow.
                logger.warning("Unknown intent reclassification failed: %s", type(exc).__name__)
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
                   destination.stage AS target_stage, line.line_text AS target_text,
                   line.line_id AS target_line_id,
                   destination.is_terminal AS target_is_terminal, destination.outcome AS target_outcome
            FROM dialogue_transitions AS transition
            JOIN dialogue_nodes AS destination ON destination.node_id = transition.to_node_id
            LEFT JOIN dialogue_lines AS line ON line.node_id = destination.node_id
              AND line.source = 'fixed' AND line.is_reprompt = FALSE
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
            default = next((item for item in session['intent_defaults'] if item['intent']==intent),None)
            if default is not None:
                score_delta = default["score_delta"]
                feedback = default["feedback"]
                critical = default["critical"]
                if default["end_outcome"] is not None:
                    target = _terminal_node(cursor, session["scenario_version_id"], default["end_outcome"])
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
                               stage AS target_stage,
                               is_terminal AS target_is_terminal, outcome AS target_outcome
                        FROM dialogue_nodes WHERE node_id = %s
                        """,
                        (session["timeout_next_node_id"],),
                    )
                    target = cursor.fetchone()
                    if target is not None:
                        cursor.execute(
                            """SELECT line_text AS target_text,line_id AS target_line_id
                               FROM dialogue_lines WHERE node_id=%s AND source='fixed' AND is_reprompt=FALSE""",
                            (target["target_node_id"],),
                        )
                        target.update(cursor.fetchone() or {})
                    unknown_count = 0
                elif unknown_count >= 2 or next_turn_no >= session["max_turns"]:
                    target = _terminal_node(cursor, session["scenario_version_id"], "timeout")
                    unknown_count = 0

        if completion:
            terminal = _terminal_node(cursor, session['scenario_version_id'], 'safe')
            if terminal is not None:
                target = terminal
                target['target_text'] = completion.closing
                score_delta, feedback, critical, unknown_count = 0, None, False, 0
                from psycopg.types.json import Jsonb
                cursor.execute("UPDATE call_sessions SET world_state=world_state || %s WHERE session_id=%s",
                    (Jsonb({'service_completion': {'reason': completion.reason, 'turn_no': next_turn_no}}),session_id))

        if next_turn_no >= session['max_turns'] and (target is None or not target['target_is_terminal']):
            target=_terminal_node(cursor,session['scenario_version_id'],'timeout')
            unknown_count=0

        if target is None:
            target_node_id = session["current_node_id"]
            bot_text = session["reprompt_text"] or session["node_text"]
            stage = session["stage"]
            outcome = None
            ended = False
            if session["interaction_mode"] == "call" and session["stage"] == "intro" and intent == "unknown":
                payload = session.get("scenario_payload") or {}
                bot_text = clarification_fallback(user_text, caller_line, bot_text, payload.get("category", ""))
        else:
            target_node_id = target["target_node_id"]
            bot_text = target["target_text"]
            stage = target["target_stage"]
            outcome = target["target_outcome"] if target["target_is_terminal"] else None
            ended = outcome is not None

        bot_text=render(bot_text,session["case_parameters"])
        from app.arena.notifications import request_artifact,brief
        if session['interaction_mode']=='call' and not ended:
            cursor.execute('SELECT requested_action FROM dialogue_nodes WHERE node_id=%s',(target_node_id,))
            request_artifact(cursor,session_id,cursor.fetchone()['requested_action'])
        available_messages=brief(cursor,session_id)
        line_result = None
        if not (target is not None and target["target_is_terminal"]):
            # The session row is locked here; keep LINE_LLM_TIMEOUT_SECONDS short (default 3s).
            line_result = resolve_bot_line(
                scenario_id=session["scenario_id"], session_id=session_id,
                target_node=target_node_id, intent=intent, user_text_masked=user_text_masked,
                original_user_text=user_text, fixed_text=bot_text, is_reprompt=(target is None),
                context={"conversation_ending": False, "sample_line": bot_text, "intent": intent, "player_text": user_text_masked,
                         "caller_line": caller_line, "case_facts": session["case_parameters"],
                         "available_messages": available_messages,
                         "interaction_mode": session["interaction_mode"]},
            )
            bot_text = line_result.text
        else:
            from app.arena.line_generator import LineResult
            line_result = LineResult(bot_text, None, "fixed", 0)
        logger.info("session_id=%s node=%s intent=%s line_source=%s line_latency_ms=%s", session_id, target_node_id, intent, line_result.source, line_result.latency_ms)

        total_score = max(0, min(100, session["total_score"] + score_delta))
        cursor.execute(
            """
            INSERT INTO call_turns
                (session_id, turn_no, node_id, target_node_id, is_reprompt, user_text_masked, intent, intent_method,
                 score_delta, feedback, critical, elapsed_seconds, bot_reply_text,
                 line_id, line_source, line_latency_ms)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING turn_id
            """,
            (
                session_id, next_turn_no, session["current_node_id"], target_node_id, target is None, user_text_masked,
                intent, intent_method, score_delta,
                feedback, critical, elapsed_seconds, bot_text, line_result.line_id,
                line_result.source, line_result.latency_ms,
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
                    session["requested_action"], caller_line, user_text_masked, intent,
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
            intent=Intent(intent),
            intent_method=intent_method,
            line_source=line_result.source,
            line_latency_ms=line_result.latency_ms,
            line_id=line_result.line_id,
            turn_no=next_turn_no,
            stage=stage,
            ended=ended,
            outcome=outcome,
            score=total_score,
            score_delta=score_delta,
            feedback=feedback,
        )


def _adjust_line_preference(cursor, line_id: int, delta: int) -> int:
    cursor.execute(
        """UPDATE dialogue_lines
           SET preference_score=GREATEST(-100,LEAST(100,preference_score+%s))
           WHERE line_id=%s AND source='llm' RETURNING preference_score""",
        (delta, line_id),
    )
    result = cursor.fetchone()
    if not result:
        raise KeyError(line_id)
    return result["preference_score"]


def rate_generated_line(session_id: UUID, turn_no: int, line_id: int, user_id: str) -> LinePreferenceResponse:
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute("""SELECT gl.line_id FROM call_turns t
                       JOIN call_sessions s USING(session_id)
                       JOIN dialogue_lines gl ON gl.line_id=%s AND gl.node_id=t.target_node_id
                         AND gl.source='llm' AND gl.intent=t.intent AND gl.is_reprompt=t.is_reprompt
                       WHERE t.session_id=%s AND s.user_id=%s AND t.turn_no=%s""",(line_id,session_id,user_id,turn_no))
        if not cursor.fetchone(): raise KeyError(line_id)
        score=_adjust_line_preference(cursor,line_id,1)
    return LinePreferenceResponse(line_id=line_id,reaction='like',preference_score=score)


def _check_regeneration_turn(turn, turn_no, old_line_id):
    if not turn:
        raise KeyError(turn_no)
    if turn.get('exercise_mode')=='assessment': raise ValueError('Không tạo lại câu trong bài đánh giá.')
    if turn["interaction_mode"] == "call" and (turn["latest_turn_no"] != turn_no or turn["ended_at"] is not None):
        raise ValueError("Chỉ có thể tạo lại câu trả lời mới nhất khi cuộc gọi đang diễn ra.")
    if old_line_id is not None and old_line_id != turn["line_id"]:
        raise ValueError("Câu trả lời đã thay đổi. Hãy dùng câu mới nhất.")


def regenerate_turn_line(session_id: UUID, turn_no: int, old_line_id: int | None, user_id: str) -> RegeneratedLineResponse:
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute("""SELECT t.target_node_id,t.intent,t.is_reprompt,s.scenario_id,
                              t.line_id,t.line_source,t.bot_reply_text,s.interaction_mode,s.exercise_mode,s.ended_at,s.turn_no AS latest_turn_no
                       FROM call_turns t JOIN call_sessions s USING(session_id)
                       WHERE t.session_id=%s AND s.user_id=%s AND t.turn_no=%s""",(session_id,user_id,turn_no))
        turn=cursor.fetchone()
        _check_regeneration_turn(turn, turn_no, old_line_id)
        if not turn['target_node_id'] or not turn['intent']: raise ValueError('Lượt này chưa hỗ trợ tạo lại lời thoại.')
        cursor.execute("SELECT is_terminal FROM dialogue_nodes WHERE node_id=%s",(turn['target_node_id'],))
        target=cursor.fetchone()
        if not target or target['is_terminal']: raise ValueError('Không thể tạo lại lời thoại cho node kết thúc.')
        if old_line_id is not None:
            cursor.execute("""SELECT line_id FROM dialogue_lines WHERE line_id=%s
                           AND node_id=%s AND source='llm' AND intent=%s AND is_reprompt=%s""",
                           (old_line_id,turn['target_node_id'],turn['intent'],turn['is_reprompt']))
            if not cursor.fetchone(): raise KeyError(old_line_id)
    result=regenerate_line_for_turn(session_id=session_id,turn_no=turn_no,old_line_id=old_line_id,user_id=user_id)
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        # Generation happens outside locks. Recheck under the session/turn locks so
        # a double click or a concurrent new turn cannot penalize/replace stale text.
        cursor.execute("""SELECT t.line_id,t.bot_reply_text,s.interaction_mode,s.exercise_mode,s.ended_at,s.turn_no AS latest_turn_no
                          FROM call_turns t JOIN call_sessions s USING(session_id)
                          WHERE t.session_id=%s AND s.user_id=%s AND t.turn_no=%s FOR UPDATE OF s,t""",
                       (session_id,user_id,turn_no))
        current = cursor.fetchone()
        _check_regeneration_turn(current, turn_no, old_line_id)
        if current['line_id'] != turn['line_id'] or current['bot_reply_text'] != turn['bot_reply_text']:
            raise ValueError("Câu trả lời đã được tạo lại. Hãy dùng câu mới nhất.")
        if turn['line_id'] is not None and turn['line_source'] != 'fixed':
            _adjust_line_preference(cursor,turn['line_id'],-1)
        cursor.execute("""UPDATE call_turns SET bot_reply_text=%s,line_id=%s,line_source=%s,line_latency_ms=%s
                       WHERE session_id=%s AND turn_no=%s""",
                       (result.text,result.line_id,result.source,result.latency_ms,session_id,turn_no))
        invalidate_memory(cursor, session_id)
    return RegeneratedLineResponse(bot_text=result.text,line_source=result.source,
        line_latency_ms=result.latency_ms,line_id=result.line_id,turn_no=turn_no)


def finish_call(session_id: UUID, user_id: str) -> None:
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE call_sessions AS session
            SET current_node_id = COALESCE(
                    (SELECT node_id FROM dialogue_nodes
                     WHERE scenario_version_id = session.scenario_version_id AND is_terminal AND outcome = 'timeout' LIMIT 1),
                    current_node_id
                ),
                outcome = COALESCE(outcome, 'timeout'),
                ended_at = COALESCE(ended_at, now())
            WHERE session_id = %s AND user_id = %s
            RETURNING session_id
            """,
            (session_id, user_id),
        )
        if cursor.fetchone() is None:
            raise KeyError(str(session_id))


def get_call_summary(session_id: UUID, user_id: str) -> CallSummaryResponse:
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT cs.session_id, cs.outcome, cs.total_score, cs.turn_no,v.definition->>'family' AS family,
                   EXISTS(SELECT 1 FROM practice_judgements j WHERE j.session_id=cs.session_id) AS judged,
                   (SELECT evaluation FROM practice_judgements j WHERE j.session_id=cs.session_id) AS evaluation,
                   s.scenario_name, v.definition->>'title' AS title, v.definition->'payload'->>'lesson_summary' AS lesson_summary,
                   v.definition->'payload'->'red_flags' AS red_flags
            FROM call_sessions AS cs
            JOIN scenarios AS s ON s.scenario_id = cs.scenario_id
            JOIN scenario_versions v ON v.version_id=cs.scenario_version_id
            WHERE cs.session_id = %s AND cs.user_id = %s
            """,
            (session_id, user_id),
        )
        session = cursor.fetchone()
        if session is None:
            raise KeyError(str(session_id))
        if session.get('family') in {'delivery','appointment','support'} and not session['judged']:
            raise ValueError('Hãy đưa ra nhận định sau cuộc gọi trước khi xem đáp án.')

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
    practice=session.get('family') in {'delivery','appointment','support'}
    evaluation=session.get('evaluation')
    if practice and evaluation:
        score=evaluation['evaluation_score']
        badge='Đánh giá và kiểm tra tốt' if score>=80 else 'Cần luyện thêm cách kiểm tra' if score>=50 else 'Cần xem lại bằng chứng và hành động'
        session['outcome']='scammed' if evaluation['risk_action_recorded'] else 'safe' if evaluation['correct'] else 'timeout'
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
    if practice: mistakes=[]
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


def list_call_history(limit: int, user_id: str) -> list[CallHistoryItem]:
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT cs.session_id, CASE WHEN v.definition->>'family' IN ('delivery','appointment','support') THEN 'Cuộc gọi dịch vụ' ELSE v.definition->>'title' END AS title, cs.started_at, cs.ended_at,
                      CASE WHEN v.definition->>'family' IN ('delivery','appointment','support') THEN
                        CASE WHEN j.evaluation IS NULL THEN NULL WHEN j.evaluation->>'risk_action_recorded'='true' THEN 'scammed'
                             WHEN j.evaluation->>'correct'='true' THEN 'safe' ELSE 'timeout' END ELSE cs.outcome END AS outcome,
                      CASE WHEN v.definition->>'family' IN ('delivery','appointment','support') THEN COALESCE((j.evaluation->>'evaluation_score')::integer,0) ELSE cs.total_score END AS total_score,
                      (v.definition->>'family' IN ('delivery','appointment','support') AND j.evaluation IS NULL) AS awaiting_judgement,cs.turn_no
               FROM call_sessions cs JOIN scenarios s ON s.scenario_id = cs.scenario_id
               JOIN scenario_versions v ON v.version_id=cs.scenario_version_id
               LEFT JOIN practice_judgements j ON j.session_id=cs.session_id
               WHERE cs.user_id = %s ORDER BY cs.started_at DESC LIMIT %s""",
            (user_id, limit),
        )
        return [
            CallHistoryItem(
                session_id=str(row["session_id"]), scenario_title=row["title"],
                started_at=row["started_at"].isoformat(),
                ended_at=row["ended_at"].isoformat() if row["ended_at"] else None,
                outcome=row["outcome"], total_score=row["total_score"], turn_count=row["turn_no"],
                awaiting_judgement=row['awaiting_judgement'],
            )
            for row in cursor.fetchall()
        ]


def get_call_transcript(session_id: UUID, user_id: str) -> CallTranscriptResponse:
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT cs.session_id,cs.case_parameters, CASE WHEN v.definition->>'family' IN ('delivery','appointment','support') THEN 'Cuộc gọi dịch vụ' ELSE v.definition->>'title' END AS title, COALESCE(chosen.line_text, fallback.line_text) AS opening_line
               FROM call_sessions cs
               JOIN scenarios s ON s.scenario_id = cs.scenario_id
               JOIN scenario_versions v ON v.version_id=cs.scenario_version_id
               JOIN dialogue_nodes start_node
                 ON start_node.scenario_version_id = cs.scenario_version_id AND start_node.is_start = TRUE
               LEFT JOIN dialogue_lines chosen ON chosen.line_id = cs.opening_line_id
               LEFT JOIN LATERAL (
                   SELECT line_text FROM dialogue_lines
                   WHERE node_id = start_node.node_id AND source='fixed' AND is_reprompt=FALSE
                   ORDER BY line_id LIMIT 1
               ) fallback ON TRUE
               WHERE cs.session_id = %s AND cs.user_id = %s""",
            (session_id, user_id),
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

    messages = [TranscriptMessage(role="caller", text=render(session["opening_line"],session['case_parameters']))]
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
            """SELECT c.candidate_id, c.session_id, v.definition->>'title' AS scenario_title, c.stage,
                      c.requested_action, c.caller_text, c.user_text_masked,
                      c.detected_intent, c.source_reason,
                      c.suggested_intent, c.suggested_phrase, c.confidence, c.rationale,
                      c.analysis_status, c.created_at
               FROM intent_review_candidates c
               JOIN scenarios s ON s.scenario_id = c.scenario_id
               JOIN call_sessions cs ON cs.session_id=c.session_id
               JOIN scenario_versions v ON v.version_id=cs.scenario_version_id
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


def flag_turn_for_review(session_id: UUID, turn_no: int, user_id: str) -> FlagTurnResponse:
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT s.scenario_id, n.stage, n.requested_action, line.line_text AS caller_text,
                      t.turn_id, t.intent, t.user_text_masked
               FROM call_sessions s
               JOIN call_turns t ON t.session_id = s.session_id
               JOIN dialogue_nodes n ON n.node_id = t.node_id
               LEFT JOIN dialogue_lines line ON line.node_id=n.node_id
                 AND line.source='fixed' AND line.is_reprompt=FALSE
               WHERE s.session_id = %s AND s.user_id = %s AND t.turn_no = %s""",
            (session_id, user_id, turn_no),
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
