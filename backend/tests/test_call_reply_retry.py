from unittest.mock import patch

import pytest

from app.arena import call_service as calls
from app.arena.line_generator import LineResult, validate_line
from app.arena.phone_dialogue import phone_opening, clarification_fallback


def test_phone_opening_removes_only_redundant_courtesy():
    text = "Xin phép hỏi anh/chị có tiện nghe máy không ạ? Tôi gọi về một giao dịch cần kiểm tra."
    assert phone_opening(text) == "Tôi gọi về một giao dịch cần kiểm tra."
    assert phone_opening("Alo, bên ngân hàng đây ạ.") == "bên ngân hàng đây ạ."
    assert phone_opening("Alo anh/chị, tôi gọi từ bộ phận hỗ trợ.") == "tôi gọi từ bộ phận hỗ trợ."
    assert phone_opening("Xin chào anh/chị, tôi gọi về giao dịch.") == "tôi gọi về giao dịch."
    assert phone_opening("Tài khoản cần kiểm tra.") == "Tài khoản cần kiểm tra."


def test_clear_acknowledgement_and_question_are_not_gibberish():
    original = "Anh/chị còn nghe máy chứ?"
    assert "giao dịch" in clarification_fallback("Giao dịch gì vậy?", "", original, "bank_impersonation")
    assert "còn nghe" not in clarification_fallback("Có, tôi đang nghe máy.", "", original, "bank_impersonation")
    assert clarification_fallback("Tôi không muốn nghe nữa", "", original, "bank_impersonation") == original
    assert validate_line("Bạn có thể giải thích lại nội dung yêu cầu của mình được không?",
                         "Có, tôi đang nghe máy.", {"interaction_mode": "call"}) is None
    assert validate_line("Anh/chị còn nghe máy chứ?", "Có, tôi đang nghe máy.", {})


class Pool:
    def __init__(self, turn, stale=False):
        self.turn = turn
        self.stale = stale
        self.sql = []
    def connection(self): return self
    def cursor(self): return self
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, sql, params=None): self.sql.append((sql, params)); self.query = sql
    def fetchone(self):
        if "FOR UPDATE OF s,t" in self.query:
            return {**self.turn, "bot_reply_text": "Concurrent replacement"} if self.stale else dict(self.turn)
        if "FROM call_turns t" in self.query: return dict(self.turn)
        if "SELECT is_terminal" in self.query: return {"is_terminal": False}
        if "SELECT line_id" in self.query: return {"line_id": self.turn["line_id"]}
        if "RETURNING preference_score" in self.query: return {"preference_score": -1}
        return None


def turn(**changes):
    return {"target_node_id": 2, "intent": "unknown", "is_reprompt": True, "scenario_id": 1,
            "line_id": 7, "line_source": "llm", "bot_reply_text": "Original response",
            "interaction_mode": "call", "ended_at": None, "latest_turn_no": 1, **changes}


def test_success_replaces_same_turn_and_decrements_original_once():
    pool = Pool(turn())
    with patch.object(calls, "get_connection_pool", return_value=pool), \
         patch.object(calls, "regenerate_line_for_turn", return_value=LineResult("New response", 8, "llm", 20)):
        response = calls.regenerate_turn_line("session", 1, 7, "owner")
    changes = [(q, p) for q, p in pool.sql if "preference_score=GREATEST" in q]
    assert len(changes) == 1 and changes[0][1] == (-1, 7)
    assert response.turn_no == 1 and response.line_id == 8
    assert not any("UPDATE call_sessions" in q or "INSERT INTO call_turns" in q for q, _ in pool.sql)


@pytest.mark.parametrize("mode", ["provider_failure", "stale", "wrong_line", "older_turn", "ended"])
def test_failure_or_stale_request_never_decrements_priority(mode):
    old = turn()
    if mode == "older_turn": old["latest_turn_no"] = 2
    if mode == "ended": old["ended_at"] = "ended"
    pool = Pool(old, stale=mode == "stale")
    with patch.object(calls, "get_connection_pool", return_value=pool), \
         patch.object(calls, "regenerate_line_for_turn", side_effect=RuntimeError("provider unavailable") if mode == "provider_failure" else None,
                      return_value=LineResult("New response", 8, "llm", 20)):
        with pytest.raises((RuntimeError, ValueError)):
            calls.regenerate_turn_line("session", 1, 99 if mode == "wrong_line" else 7, "owner")
    assert not any("UPDATE dialogue_lines" in q or "UPDATE call_turns" in q for q, _ in pool.sql)


@pytest.mark.parametrize("source", ["fixed", "llm"])
def test_uncatalogued_or_fixed_reply_can_regenerate_without_preference_change(source):
    pool = Pool(turn(line_id=None, line_source=source))
    with patch.object(calls, "get_connection_pool", return_value=pool), \
         patch.object(calls, "regenerate_line_for_turn", return_value=LineResult("New response", None, "llm", 20)):
        calls.regenerate_turn_line("session", 1, None, "owner")
    assert not any("UPDATE dialogue_lines" in q for q, _ in pool.sql)
