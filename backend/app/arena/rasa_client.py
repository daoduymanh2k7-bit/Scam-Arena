"""Small, fail-open HTTP client for the optional Rasa NLU sidecar."""

from __future__ import annotations

import json
import os
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.arena.intent_detector import Intent


def classify_with_rasa(text: str) -> tuple[Intent | None, float]:
    """Return a Rasa intent when the service is configured and reachable."""
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
    label = prediction.get("name")
    try:
        intent = Intent(label)
        confidence = float(prediction.get("confidence", 0.0))
    except (ValueError, TypeError):
        return None, 0.0
    if intent is Intent.UNKNOWN:
        return None, confidence
    return intent, confidence
