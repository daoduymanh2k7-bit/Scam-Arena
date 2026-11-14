"""Optional post-session intent review using the OpenAI Responses API."""

from __future__ import annotations

import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

from app.database import get_connection_pool

ALLOWED_INTENTS = {
    "verify", "refuse", "doubt", "comply", "share_sensitive",
    "transfer_money", "hang_up", "unknown",
}


def _request_review(candidate: dict[str, object]) -> dict[str, object]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("not_configured")

    model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini").strip()
    endpoint = os.getenv("OPENAI_RESPONSES_URL", "https://api.openai.com/v1/responses").strip()
    payload = {
        "model": model,
        "instructions": (
            "Bạn là công cụ rà soát nhãn ý định cho trò chơi phòng chống lừa đảo. "
            "Chỉ phân loại câu trả lời của người chơi vào một trong: verify, refuse, doubt, comply, "
            "share_sensitive, transfer_money, hang_up, unknown. Không suy diễn hành động đã xảy ra "
            "nếu người chơi chỉ nhắc đến từ khóa. Phân biệt phủ định với đồng ý. Nếu chưa rõ, chọn unknown. "
            "Hãy kiểm tra nhãn máy đã gán và có thể kết luận nhãn đó hợp lý hay không. "
            "Đề xuất một cụm ngắn 2-80 ký tự có thể giúp bộ luật nhận diện câu tương tự; không bịa dữ liệu cá nhân. "
            "Trả về duy nhất JSON: intent, phrase, confidence (0-1), rationale (tiếng Việt ngắn)."
        ),
        "input": json.dumps({
            "caller_line": candidate["caller_text"],
            "requested_action": candidate["requested_action"],
            "detector_intent": candidate["detected_intent"],
            "player_answer_masked": candidate["user_text_masked"],
        }, ensure_ascii=False),
        "text": {"format": {"type": "json_object"}},
        "max_output_tokens": 180,
    }
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=35) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"LLM request failed: {exc}") from exc

    output_text = ""
    for item in result.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                output_text = content.get("text", "")
                break
        if output_text:
            break
    if not output_text:
        raise ValueError("LLM response did not contain output text")
    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError:
        start, end = output_text.find("{"), output_text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("LLM response was not JSON")
        parsed = json.loads(output_text[start:end + 1])

    intent = parsed.get("intent")
    if intent not in ALLOWED_INTENTS:
        intent = "unknown"
    phrase = re.sub(r"\s+", " ", str(parsed.get("phrase", ""))).strip()[:120]
    confidence = parsed.get("confidence", 0)
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.0
    rationale = re.sub(r"\s+", " ", str(parsed.get("rationale", ""))).strip()[:500]
    return {"intent": intent, "phrase": phrase, "confidence": confidence, "rationale": rationale}


def analyze_session_candidates(session_id: UUID) -> None:
    """Analyze unreviewed unknown answers; never activate or approve a rule."""
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT candidate_id, caller_text, requested_action, user_text_masked,
                      detected_intent
               FROM intent_review_candidates
               WHERE session_id = %s AND review_status = 'pending'
                 AND analysis_status IN ('pending', 'not_configured', 'failed')
               ORDER BY candidate_id""",
            (session_id,),
        )
        candidates = cursor.fetchall()

    for candidate in candidates:
        try:
            suggestion = _request_review(candidate)
            status = "analyzed"
        except RuntimeError as exc:
            status = "not_configured" if str(exc) == "not_configured" else "failed"
            suggestion = {"intent": None, "phrase": None, "confidence": None, "rationale": str(exc)[:500]}
        except (ValueError, KeyError, TypeError) as exc:
            status = "failed"
            suggestion = {"intent": None, "phrase": None, "confidence": None, "rationale": str(exc)[:500]}

        with get_connection_pool().connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """UPDATE intent_review_candidates
                   SET suggested_intent = %s, suggested_phrase = %s, confidence = %s,
                       rationale = %s, analysis_status = %s
                   WHERE candidate_id = %s AND review_status = 'pending'""",
                (
                    suggestion["intent"], suggestion["phrase"], suggestion["confidence"],
                    suggestion["rationale"], status, candidate["candidate_id"],
                ),
            )
