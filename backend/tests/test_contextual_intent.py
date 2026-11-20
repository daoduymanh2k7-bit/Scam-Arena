import json
from io import BytesIO
from unittest.mock import patch

import pytest

from app.arena.intent_detector import Intent, RequestedAction, detect_intent
from app.arena.rasa_client import classify_context_with_rasa


@pytest.mark.parametrize(
    "reply, caller, action, expected, rule",
    [
        ("Dạ được ạ.", "Anh còn nghe máy chứ?", "other", Intent.UNKNOWN, "contextual_acknowledgement"),
        ("Dạ được ạ.", "Anh có đồng ý làm theo hướng dẫn không?", "other", Intent.COMPLY, "contextual_affirmation"),
        ("Dạ được ạ.", "Anh muốn tự gọi tổng đài để kiểm tra không?", "other", Intent.VERIFY, "contextual_verify"),
        ("Không ạ.", "Anh nghe rõ không?", "share_sensitive", Intent.UNKNOWN, "contextual_acknowledgement"),
        ("Không ạ.", "Anh vui lòng đọc mã OTP.", "share_sensitive", Intent.REFUSE, "contextual_refusal"),
        ("Vâng.", "Anh vui lòng đọc mã OTP. Anh nhận được tin nhắn chưa?", "share_sensitive", Intent.UNKNOWN, "contextual_acknowledgement"),
        ("Vâng.", "Anh vui lòng đọc mã OTP.", "share_sensitive", Intent.UNKNOWN, "contextual_unconfirmed_action"),
        ("Vâng.", "Anh có đồng ý làm theo hướng dẫn không?", "share_sensitive", Intent.UNKNOWN, "contextual_unconfirmed_action"),
        ("da duoc a", "anh can chuyen tien vao tai khoan nay", "transfer_money", Intent.UNKNOWN, "contextual_unconfirmed_action"),
        ("Được rồi, để tôi xem đã.", "Chị bấm vào đường link giúp em.", "click_link", Intent.UNKNOWN, None),
        ("Tôi không đọc mã OTP.", "Anh vui lòng đọc mã OTP.", "share_sensitive", Intent.REFUSE, "explicit_refusal"),
        ("Tôi đã chuyển tiền rồi.", "Anh còn nghe máy chứ?", "transfer_money", Intent.TRANSFER_MONEY, "affirmative_money_transfer"),
    ],
)
def test_contextual_reply(reply, caller, action, expected, rule):
    # Deliberately confident standalone Rasa guess to catch accidental use for short replies.
    prediction = (None, 0.0) if rule == "explicit_refusal" else (Intent.COMPLY, 0.99)
    with (
        patch("app.arena.rasa_client.classify_with_rasa", return_value=prediction) as rasa,
        patch("app.arena.rasa_client.classify_context_with_rasa", return_value=(None, 0.0)),
    ):
        result = detect_intent(reply, RequestedAction(action), caller_line=caller)
    assert result.intent == expected
    assert result.matched_rule == rule
    if rule != "explicit_refusal":
        rasa.assert_not_called()


def test_full_utterance_can_still_use_rasa():
    text = "Lời anh nói nghe hơi kỳ lạ đó."
    with patch("app.arena.rasa_client.classify_with_rasa", return_value=(Intent.DOUBT, 0.9)) as rasa:
        result = detect_intent(text, caller_line="Anh nghe rõ không?")
    assert result.intent is Intent.DOUBT
    assert result.matched_rule == "rasa:0.90"
    rasa.assert_called_once_with(text)


@pytest.mark.parametrize(
    "action, caller, rasa_intent, expected, called",
    [
        ("other", "Chị tải phần mềm hỗ trợ nhé.", Intent.COMPLY, Intent.COMPLY, True),
        ("transfer_money", "Chị tải phần mềm hỗ trợ nhé.", Intent.COMPLY, Intent.UNKNOWN, True),
        ("other", "Chị tải phần mềm hỗ trợ nhé.", Intent.SHARE_SENSITIVE, Intent.UNKNOWN, True),
        ("share_sensitive", "Anh nghe rõ không?", Intent.COMPLY, Intent.UNKNOWN, False),
    ],
)
def test_contextual_rasa_respects_safety(action, caller, rasa_intent, expected, called):
    with patch("app.arena.rasa_client.classify_context_with_rasa", return_value=(rasa_intent, 0.91)) as rasa:
        result = detect_intent("Được ạ.", action, caller_line=caller)
    assert result.intent == expected
    if called:
        rasa.assert_called_once_with(caller, "yes")
    else:
        rasa.assert_not_called()
    if expected is Intent.COMPLY:
        assert result.matched_rule == "rasa:context:0.91"


def test_contextual_request_rejects_standalone_rasa_prediction(monkeypatch):
    monkeypatch.setenv("RASA_NLU_URL", "http://rasa:5005/model/parse")
    old_response = {"intent": {"name": "comply", "confidence": 0.99}}
    with patch("app.arena.rasa_client.urlopen", return_value=BytesIO(json.dumps(old_response).encode())) as urlopen:
        assert classify_context_with_rasa("Chị bật quyền điều khiển từ xa nhé.", "yes") == (None, 0.0)
    request = urlopen.call_args.args[0]
    prefix, context = json.loads(request.data)["text"].split(" ", 1)
    assert prefix == "scam-arena-context-v1"
    assert json.loads(context) == {"caller_line": "Chị bật quyền điều khiển từ xa nhé.", "polarity": "yes"}
