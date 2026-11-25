"""LLM fallback for utterances that the local intent pipeline cannot classify."""
from __future__ import annotations

import json
import logging
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app.arena.intent_detector import Intent
from app.arena.xapikey_client import request_json as request_xapikey_json, settings as xapikey_settings

from app.arena.prompts import INTENT_PROMPT as SYSTEM_PROMPT

log = logging.getLogger(__name__)
SAFE_OVERRIDES = {"verify", "refuse", "doubt", "comply", "hang_up"}


def _enabled() -> bool:
    return os.getenv("LINE_LLM_ENABLED", "false").strip().lower() in {"true", "1"}


def _payload(context: dict) -> str:
    return json.dumps(context, ensure_ascii=False)


def _read_response(request: Request, timeout: float, provider: str) -> dict:
    try:
        with urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"{provider} HTTP {exc.code}") from exc
    if provider == "Gemini":
        candidates = body.get("candidates", [])
        text = "".join(part["text"] for part in (candidates[0] if candidates else {}).get("content", {}).get("parts", [])
                       if isinstance(part.get("text"), str) and not part.get("thought"))
    else:
        message = body.get("choices", [{}])[0].get("message", {})
        text = message.get("content", "")
        if isinstance(text, list):
            text = "".join(part.get("text", "") for part in text if isinstance(part, dict))
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"{provider} returned empty classification")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        decoder = json.JSONDecoder()
        parsed = None
        for index, char in enumerate(text):
            if char == "{":
                try:
                    parsed, _ = decoder.raw_decode(text[index:])
                    break
                except json.JSONDecodeError:
                    continue
        if parsed is None:
            raise ValueError(f"{provider} returned invalid classification JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{provider} returned an invalid classification object")
    return parsed


def _gemini(context: dict, timeout: float, *, instructions=SYSTEM_PROMPT, schema=None, max_tokens=256) -> dict:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    schema = schema or {"type": "OBJECT", "properties": {
        "intent": {"type": "STRING", "enum": sorted(SAFE_OVERRIDES | {"unknown"})},
        "confidence": {"type": "NUMBER"},
    }, "required": ["intent", "confidence"]}
    payload = {"systemInstruction": {"parts": [{"text": instructions}]},
        "contents": [{"role": "user", "parts": [{"text": _payload(context)}]}],
        "generationConfig": {"responseMimeType": "application/json", "responseSchema": schema,
                             "temperature": 0, "maxOutputTokens": max_tokens}}
    if model.startswith("gemini-2.5-flash"):
        payload["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 0}
    request = Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(payload).encode("utf-8"),
        headers={"x-goog-api-key": key, "Content-Type": "application/json"}, method="POST",
    )
    return _read_response(request, timeout, "Gemini")


def _compatible(provider: str, context: dict, timeout: float, *, instructions=SYSTEM_PROMPT, max_tokens=400) -> dict:
    if provider == "Groq":
        key = os.getenv("GROQ_API_KEY", "").strip()
        model = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b").strip()
        endpoint = "https://api.groq.com/openai/v1/chat/completions"
    else:
        key = os.getenv("OPENROUTER_API_KEY", "").strip()
        model = os.getenv("OPENROUTER_MODEL", "openrouter/free").strip()
        endpoint = "https://openrouter.ai/api/v1/chat/completions"
    payload = {"model": model, "messages": [
        {"role": "system", "content": instructions},
        {"role": "user", "content": _payload(context)},
    ], "max_tokens": max_tokens, "temperature": 0}
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if provider == "Groq":
        headers["User-Agent"] = "ScamArena/1.0"
        payload.pop("max_tokens", None)
        payload["max_completion_tokens"] = max_tokens
        if model.startswith("openai/gpt-oss-"):
            payload.update(reasoning_effort="low", reasoning_format="hidden",
                           response_format={"type": "json_object"})
    else:
        headers["HTTP-Referer"] = "https://scam-arena.local"
        headers["X-Title"] = "Scam Arena"
    request = Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    return _read_response(request, timeout, provider)


def reclassify_unknown(*, context: dict) -> Intent | None:
    """Return a conservative LLM label; None means keep the deterministic unknown."""
    if not _enabled():
        return None
    timeout = max(0.1, float(os.getenv("LINE_LLM_TIMEOUT_SECONDS", "3")))
    providers = []
    if os.getenv("GEMINI_API_KEY", "").strip():
        providers.append(("Gemini", _gemini))
    if os.getenv("GROQ_API_KEY", "").strip():
        providers.append(("Groq", lambda ctx, seconds: _compatible("Groq", ctx, seconds)))
    if os.getenv("OPENROUTER_API_KEY", "").strip():
        providers.append(("OpenRouter", lambda ctx, seconds: _compatible("OpenRouter", ctx, seconds)))
    if xapikey_settings(context.get("interaction_mode", "message"))[0]:
        providers.append(("X-APIKEY", lambda ctx, seconds: request_xapikey_json(SYSTEM_PROMPT, ctx, timeout=seconds,
            validate_result=lambda value: value.get("intent") in SAFE_OVERRIDES | {"unknown"}
                and not isinstance(value.get("confidence"), bool)
                and isinstance(value.get("confidence"), (int, float))
                and 0 <= value["confidence"] <= 1)[0]))
    for provider, call in providers:
        try:
            result = call(context, timeout)
            label = result.get("intent")
            confidence = result.get("confidence")
            if not isinstance(label, str) or label not in SAFE_OVERRIDES | {"unknown"}:
                raise ValueError("invalid intent")
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
                raise ValueError("invalid confidence")
            if label == "unknown" or confidence < 0.75:
                return None
            log.info("Unknown intent reclassified by %s as %s confidence=%.2f", provider, label, confidence)
            return Intent(label)
        except Exception as exc:
            log.warning("Intent reclassification provider=%s failed: %s", provider, type(exc).__name__)
    return None
