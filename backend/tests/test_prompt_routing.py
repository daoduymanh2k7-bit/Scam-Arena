"""Check provider fallbacks receive the same trusted dialogue contract."""
import json
from unittest.mock import patch

import pytest

from app.arena import line_generator as lines
from app.arena.prompts import DIALOGUE_PROMPT


@pytest.mark.parametrize("provider", ["gemini", "groq", "openrouter", "xapikey"])
def test_dialogue_prompt_is_identical_across_providers(provider):
    context = {"player_text": "Tôi chưa hiểu.", "_private": "not sent"}
    if provider == "xapikey":
        with patch.object(lines, "request_xapikey_json", return_value=({"line": "Bạn muốn hỏi điều gì?"}, "test")) as request:
            lines._request_xapikey(context, 1)
        assert request.call_args.args[0] == DIALOGUE_PROMPT
        assert request.call_args.args[1] == {"player_text": "Tôi chưa hiểu."}
        return

    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self):
            content = json.dumps({"line": "Bạn muốn hỏi điều gì?"})
            body = ({"candidates": [{"content": {"parts": [{"text": content}]}}]}
                    if provider == "gemini" else {"choices": [{"message": {"content": content}}]})
            return json.dumps(body).encode()

    with patch.dict("os.environ", {"GEMINI_API_KEY": "fake", "GROQ_API_KEY": "fake", "OPENROUTER_API_KEY": "fake"}), \
         patch.object(lines, "urlopen", return_value=Response()) as request:
        if provider == "gemini":
            lines._request_line(context, "test", 1)
        else:
            getattr(lines, "_request_" + provider)(context, 1)
    body = json.loads(request.call_args.args[0].data)
    if provider == "gemini":
        assert body["systemInstruction"]["parts"][0]["text"] == DIALOGUE_PROMPT
        sent = body["contents"][0]["parts"][0]["text"]
    else:
        assert body["messages"][0]["content"] == DIALOGUE_PROMPT
        sent = body["messages"][1]["content"]
    assert json.loads(sent) == {"player_text": "Tôi chưa hiểu."}
