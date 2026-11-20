"""Small, fail-open HTTP client for the optional Rasa NLU sidecar."""

from __future__ import annotations

import json
import os
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.arena.intent_detector import Intent


_CONTEXT_PREFIX = "scam-arena-context-v1 "


def classify_with_rasa(text: str) -> tuple[Intent | None, float]:
    """Return a Rasa intent when the service is configured and reachable."""
    return _classify(text)


def classify_context_with_rasa(caller_line: str, polarity: str) -> tuple[Intent | None, float]:
    """Ask Rasa to interpret a short yes/no reply using the actual caller line."""
    if not caller_line.strip():
        return None, 0.0
    context = json.dumps({"caller_line": caller_line[-600:], "polarity": polarity}, ensure_ascii=False)
    return _classify(_CONTEXT_PREFIX + context, contextual=True)


def _classify(text: str, *, contextual: bool = False) -> tuple[Intent | None, float]:
    endpoint = os.getenv("RASA_NLU_URL", "").strip()
    if not endpoint or not text.strip():
        return None, 0.0

    try:
        timeout = float(os.getenv("RASA_NLU_TIMEOUT_SECONDS", "2"))
    except ValueError:
        timeout = 2.0
    request = Request(
        endpoint,
        data=json.dumps({"text": text}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, ValueError, OSError):
        return None, 0.0

    if not isinstance(payload, dict):
        return None, 0.0
    prediction = payload.get("intent") or {}
    if not isinstance(prediction, dict):
        return None, 0.0
    if contextual and prediction.get("contextual") is not True:
        return None, 0.0
    label = prediction.get("name")
    try:
        intent = Intent(label)
        confidence = float(prediction.get("confidence", 0.0))
    except (ValueError, TypeError):
        return None, 0.0
    if intent is Intent.UNKNOWN:
        return None, confidence
    return intent, confidence
