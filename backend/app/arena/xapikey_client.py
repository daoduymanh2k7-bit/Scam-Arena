"""Mode-specific, optional paid fallback using the OpenAI-compatible gateway."""

import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def settings(mode="message"):
    if mode not in {"call", "message"}:
        raise ValueError("Unsupported interaction mode")
    prefix = f"XAPIKEY_{mode.upper()}"
    key = os.getenv(f"{prefix}_API_KEY", "").strip()
    default_model = "minimax-m3.1-flash" if mode == "call" else "gpt-6-luna"
    model = os.getenv(f"{prefix}_MODEL", default_model).strip() or default_model
    return key, model


def request_json(instructions, context, *, max_tokens=400, timeout=None):
    mode = context.get("interaction_mode", "message")
    key, model = settings(mode)
    if not key:
        raise RuntimeError("X-APIKEY is not configured for this interaction mode")
    base_url = os.getenv("XAPIKEY_BASE_URL", "https://api.x-apikey.com/v1").strip().rstrip("/")
    if not base_url.startswith("https://"):
        raise ValueError("X-APIKEY requires an HTTPS endpoint")
    timeout = max(0.1, float(os.getenv("XAPIKEY_TIMEOUT_SECONDS", "15"))) if timeout is None else max(.1, timeout)
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ],
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    request = Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "ScamArena/1.0"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"X-APIKEY HTTP {exc.code}") from exc
    choices = body.get("choices") or []
    text = (choices[0].get("message") or {}).get("content") if choices else None
    if not isinstance(text, str) or not text.strip():
        raise ValueError("X-APIKEY returned no text content")
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            result, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(result, dict):
            return result, model
    raise ValueError("X-APIKEY returned invalid JSON")
