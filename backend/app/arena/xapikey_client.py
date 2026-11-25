"""Mode-specific gateway models with bounded failover and temporary circuit breaks."""

import hashlib
import json
import logging
import os
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)
_lock = threading.Lock()
_cooldowns = {}
DEFAULT_FALLBACKS = {
    "call": "gpt-6.2-sol,deepseek-v4.1-flash-1017,gpt-6-luna",
    "message": "gpt-6.1-sol,gpt-6.2-sol,deepseek-v4.1-flash-1017",
}


def settings(mode="message"):
    if mode not in DEFAULT_FALLBACKS:
        raise ValueError("Unsupported interaction mode")
    prefix = f"XAPIKEY_{mode.upper()}"
    key = os.getenv(f"{prefix}_API_KEY", "").strip()
    default = "gpt-6.1-sol" if mode == "call" else "gpt-6-luna"
    return key, os.getenv(f"{prefix}_MODEL", default).strip() or default


def model_order(mode="message"):
    _, primary = settings(mode)
    backups = os.getenv(f"XAPIKEY_{mode.upper()}_FALLBACK_MODELS", DEFAULT_FALLBACKS[mode])
    return list(dict.fromkeys([primary] + [m.strip() for m in backups.split(",") if m.strip()]))[:8]


def _cooldown(key, seconds):
    with _lock:
        now = time.monotonic()
        for old in list(_cooldowns):
            if _cooldowns[old] <= now:
                del _cooldowns[old]
        _cooldowns[key] = now + seconds


def _parse(body):
    choices = body.get("choices") or []
    text = (choices[0].get("message") or {}).get("content") if choices else None
    if not isinstance(text, str) or not text.strip():
        raise ValueError("empty_response")
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char == "{":
            try:
                result, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(result, dict):
                return result
    raise ValueError("invalid_json")


def request_json(instructions, context, *, max_tokens=400, timeout=None, validate_result=None):
    mode = context.get("interaction_mode", "message")
    key, _ = settings(mode)
    if not key:
        raise RuntimeError("X-APIKEY is not configured for this interaction mode")
    base_url = os.getenv("XAPIKEY_BASE_URL", "https://api.x-apikey.com/v1").strip().rstrip("/")
    if not base_url.startswith("https://"):
        raise ValueError("X-APIKEY requires an HTTPS endpoint")
    budget = max(.1, float(os.getenv("XAPIKEY_TIMEOUT_SECONDS", "15")))
    if timeout is not None:
        budget = min(budget, max(.1, timeout))
    per_model = max(.1, float(os.getenv("XAPIKEY_MODEL_TIMEOUT_SECONDS", "6")))
    deadline = time.monotonic() + budget
    # Never share circuit state between credentials, modes or gateways; never log credentials.
    identity = (base_url, mode, hashlib.sha256(key.encode()).hexdigest())
    models = model_order(mode)
    with _lock:
        now = time.monotonic()
        models = [m for m in models if _cooldowns.get((*identity, m), 0) <= now]
    last_failure = "temporarily_unavailable"
    for model in models:
        remaining = deadline - time.monotonic()
        if remaining < .1:
            last_failure = "timeout"
            break
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            ],
            "max_tokens": max_tokens, "temperature": 0,
        }
        request = Request(
            f"{base_url}/chat/completions", data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": "ScamArena/1.0"},
            method="POST",
        )
        cooldown = 30
        try:
            with urlopen(request, timeout=min(per_model, remaining)) as response:
                body = json.loads(response.read().decode("utf-8"))
            if time.monotonic() >= deadline:
                raise TimeoutError()
            result = _parse(body)
            if validate_result is not None and not validate_result(result):
                raise ValueError("invalid_result")
            return result, model
        except HTTPError as exc:
            code = ""
            try:
                error = json.loads(exc.read(4096).decode("utf-8")).get("error", {})
                if isinstance(error, dict):
                    code = str(error.get("code", ""))
            except (ValueError, UnicodeError, AttributeError):
                pass
            # Disabled/missing models are model-specific; authentication/quota are shared.
            if code in {"model_disabled", "model_not_found", "model_not_available"} or exc.code == 404:
                last_failure, cooldown = "model_unavailable", 600
            elif exc.code in {401, 402, 403, 429}:
                # Trying the same credential on more models would waste time/money.
                raise RuntimeError(f"X-APIKEY HTTP {exc.code}") from None
            elif exc.code >= 500 or exc.code in {408, 504}:
                last_failure = "upstream_error"
            else:
                raise RuntimeError(f"X-APIKEY HTTP {exc.code}") from None
        except (TimeoutError, URLError, OSError):
            last_failure = "timeout_or_network"
        except (ValueError, TypeError, AttributeError, IndexError):
            last_failure = "invalid_response"
        _cooldown((*identity, model), cooldown)
        log.warning("X-APIKEY model=%s failed=%s; trying next available model", model, last_failure)
    raise RuntimeError(f"X-APIKEY: no usable model ({last_failure})")
