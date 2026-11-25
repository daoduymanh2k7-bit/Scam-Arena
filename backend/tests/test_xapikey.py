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


@pytest.fixture(autouse=True)
def isolated_gateway_state():
    xapikey_client._cooldowns.clear()
    yield
    xapikey_client._cooldowns.clear()


def response(value):
    return BytesIO(json.dumps({"choices": [{"message": {"content": value}}]}).encode())


def setup_chain(monkeypatch):
    monkeypatch.setenv("XAPIKEY_CALL_API_KEY", "secret-test")
    monkeypatch.setenv("XAPIKEY_CALL_MODEL", "primary")
    monkeypatch.setenv("XAPIKEY_CALL_FALLBACK_MODELS", "backup,last,backup,primary")
    monkeypatch.setenv("XAPIKEY_TIMEOUT_SECONDS", "15")
    monkeypatch.setenv("XAPIKEY_MODEL_TIMEOUT_SECONDS", "6")


def test_disabled_model_fails_over_and_is_skipped_until_cooldown(monkeypatch):
    from urllib.error import HTTPError
    setup_chain(monkeypatch)
    clock = [100.]
    monkeypatch.setattr(xapikey_client.time, "monotonic", lambda: clock[0])
    seen = []
    def send(req, timeout):
        model = json.loads(req.data)["model"]
        seen.append(model)
        assert req.get_header("Authorization") == "Bearer secret-test"
        if model == "primary":
            raise HTTPError(req.full_url, 403, "denied", {}, BytesIO(b'{"error":{"code":"model_disabled"}}'))
        return response('{"line":"Xin chao"}')
    monkeypatch.setattr(xapikey_client, "urlopen", send)
    assert xapikey_client.model_order("call") == ["primary", "backup", "last"]
    assert xapikey_client.request_json("test", {"interaction_mode":"call"})[1] == "backup"
    assert xapikey_client.request_json("test", {"interaction_mode":"call"})[1] == "backup"
    assert seen == ["primary", "backup", "backup"]
    clock[0] += 601
    xapikey_client.request_json("test", {"interaction_mode":"call"})
    assert seen[-2:] == ["primary", "backup"]


@pytest.mark.parametrize("status", [401, 402, 403, 429])
def test_shared_credential_errors_do_not_try_more_models(monkeypatch, status):
    from urllib.error import HTTPError
    setup_chain(monkeypatch)
    error = HTTPError("https://test", status, "SECRET must not leak", {}, BytesIO(b'{"error":{"message":"SECRET"}}'))
    with patch.object(xapikey_client,"urlopen",side_effect=error) as send:
        with pytest.raises(RuntimeError,match=f"^X-APIKEY HTTP {status}$"):
            xapikey_client.request_json("test", {"interaction_mode":"call"})
    assert send.call_count == 1


def test_bad_json_and_invalid_schema_try_next_model(monkeypatch):
    setup_chain(monkeypatch)
    with patch.object(xapikey_client,"urlopen",side_effect=[
        response('not json'), response('{"wrong":"shape"}'), response('{"line":"Xin chao"}'),
    ]) as send:
        result, model = xapikey_client.request_json("test", {"interaction_mode":"call"},
            validate_result=lambda value:isinstance(value.get("line"),str))
    assert model == "last" and result["line"] == "Xin chao"
    assert send.call_count == 3


def test_timeout_budget_is_not_multiplied_by_model_count(monkeypatch):
    setup_chain(monkeypatch)
    clock = [100.]
    monkeypatch.setattr(xapikey_client.time,"monotonic",lambda:clock[0])
    timeouts=[]
    def send(req,timeout):
        timeouts.append(timeout)
        clock[0] += timeout
        raise TimeoutError()
    monkeypatch.setattr(xapikey_client,"urlopen",send)
    with pytest.raises(RuntimeError,match="no usable model"):
        xapikey_client.request_json("test",{"interaction_mode":"call"},timeout=7)
    assert timeouts == [6,1]


def test_model_cooldowns_do_not_cross_keys_or_modes(monkeypatch):
    setup_chain(monkeypatch)
    monkeypatch.setenv("XAPIKEY_MESSAGE_API_KEY","message-secret")
    monkeypatch.setenv("XAPIKEY_MESSAGE_MODEL","primary")
    monkeypatch.setenv("XAPIKEY_MESSAGE_FALLBACK_MODELS","")
    with patch.object(xapikey_client,"urlopen",side_effect=[TimeoutError(),response('{"ok":true}')]):
        assert xapikey_client.request_json("test",{"interaction_mode":"call"})[1]=="backup"
    with patch.object(xapikey_client,"urlopen",side_effect=lambda *a,**kw:response('{"ok":true}')) as send:
        assert xapikey_client.request_json("test",{"interaction_mode":"message"})[1]=="primary"
        monkeypatch.setenv("XAPIKEY_CALL_API_KEY","rotated-secret")
        assert xapikey_client.request_json("test",{"interaction_mode":"call"})[1]=="primary"
    assert send.call_count==2


def test_empty_fallback_list_keeps_single_model(monkeypatch):
    setup_chain(monkeypatch)
    monkeypatch.setenv("XAPIKEY_CALL_FALLBACK_MODELS","")
    assert xapikey_client.model_order("call")==["primary"]
    with patch.object(xapikey_client,"urlopen",side_effect=TimeoutError()) as send:
        with pytest.raises(RuntimeError):xapikey_client.request_json("test",{"interaction_mode":"call"})
    assert send.call_count==1
