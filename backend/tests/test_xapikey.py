import json
from io import BytesIO
from unittest.mock import patch

import pytest

from app.arena import intent_reclassifier, line_generator, xapikey_client
from app.arena.intent_detector import Intent


@pytest.mark.parametrize("mode,key,model", [
    ("call", "call-key", "call-model"),
    ("message", "message-key", "message-model"),
])
def test_xapikey_uses_mode_specific_credentials(monkeypatch, mode, key, model):
    monkeypatch.setenv("XAPIKEY_CALL_API_KEY", "call-key")
    monkeypatch.setenv("XAPIKEY_MESSAGE_API_KEY", "message-key")
    monkeypatch.setenv("XAPIKEY_CALL_MODEL", "call-model")
    monkeypatch.setenv("XAPIKEY_MESSAGE_MODEL", "message-model")
    body = {"choices": [{"message": {"content": '{"line":"Xin chào anh chị."}'}}]}
    with patch.object(xapikey_client, "urlopen", return_value=BytesIO(json.dumps(body).encode())) as request:
        result, used_model = xapikey_client.request_json("Reply JSON", {"interaction_mode": mode})
    sent = request.call_args.args[0]
    assert sent.get_header("Authorization") == f"Bearer {key}"
    assert json.loads(sent.data)["model"] == used_model == model
    assert result["line"] == "Xin chào anh chị."


def test_line_providers_use_free_sources_before_paid(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "groq")
    monkeypatch.setenv("OPENROUTER_API_KEY", "router")
    monkeypatch.setenv("XAPIKEY_CALL_API_KEY", "paid")
    calls = []
    def groq(*args):
        calls.append("groq")
        raise TimeoutError
    def router(*args):
        calls.append("router")
        raise ValueError
    def paid(*args):
        calls.append("paid")
        return "Xin chào anh chị."
    with (
        patch.object(line_generator, "_request_groq", side_effect=groq),
        patch.object(line_generator, "_request_openrouter", side_effect=router),
        patch.object(line_generator, "_request_xapikey", side_effect=paid),
    ):
        assert line_generator._request_fallback({"interaction_mode": "call"}, 1) == "Xin chào anh chị."
    assert calls == ["groq", "router", "paid"]


def test_successful_free_provider_never_uses_paid(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "groq")
    monkeypatch.setenv("XAPIKEY_CALL_API_KEY", "paid")
    with (
        patch.object(line_generator, "_request_groq", return_value="Xin chào anh chị."),
        patch.object(line_generator, "_request_xapikey") as paid,
    ):
        assert line_generator._request_fallback({"interaction_mode": "call"}, 1) == "Xin chào anh chị."
    paid.assert_not_called()


def test_reclassification_uses_paid_after_errors(monkeypatch):
    monkeypatch.setenv("LINE_LLM_ENABLED", "true")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("XAPIKEY_CALL_API_KEY", "paid")
    with patch.object(intent_reclassifier, "request_xapikey_json", return_value=(
        {"intent": "verify", "confidence": 0.9}, "test",
    )) as paid:
        assert intent_reclassifier.reclassify_unknown(context={"interaction_mode": "call"}) is Intent.VERIFY
    assert paid.call_args.args[1]["interaction_mode"] == "call"
