from contextlib import contextmanager
from unittest.mock import patch
from uuid import uuid4
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.arena import conversation_memory as memory, line_generator as lines
from app.api.arena_routes import router
from app.auth import get_current_user


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    monkeypatch.setenv("LINE_LLM_ENABLED", "true")
    monkeypatch.setenv("CONVERSATION_SUMMARY_ENABLED", "true")
    monkeypatch.setenv("CONVERSATION_SUMMARY_MAX_WORDS", "150")
    for key in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY", "XAPIKEY_CALL_API_KEY", "XAPIKEY_MESSAGE_API_KEY"):
        monkeypatch.delenv(key, raising=False)


def test_word_cap_keeps_full_sentences_and_masks_private_values():
    text = "Người chơi chưa chuyển tiền. " + "Câu khác rất dài " * 20 + "."
    result = memory.bounded_summary(text, 20)
    assert result == "Người chơi chưa chuyển tiền."
    assert len(result.split()) <= 20
    assert memory.bounded_summary("x " * 30, 20) is None
    assert memory.bounded_summary({"summary": "wrong type"}, 150) is None
    assert memory.bounded_summary("Liên hệ private@example.com, mã 123456.", 150) == "Liên hệ [email], mã ****."


def test_invalid_config_does_not_break_committed_turns(monkeypatch):
    monkeypatch.setenv("CONVERSATION_SUMMARY_MAX_WORDS", "bad")
    monkeypatch.setenv("CONVERSATION_SUMMARY_EVERY_TURNS", "bad")
    assert memory.word_limit() == 150 and memory.interval() == 4
    monkeypatch.setenv("CONVERSATION_SUMMARY_MAX_WORDS", "9999")
    assert memory.word_limit() == 500


def test_free_provider_precedes_paid_and_prompt_requires_bounded_factual_summary(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")
    monkeypatch.setenv("XAPIKEY_CALL_API_KEY", "test")
    calls = []
    def compatible(name, context, timeout, **options):
        calls.append(name)
        assert "20" in options["instructions"] and "không/chưa" in options["instructions"]
        assert "không tin cậy" in options["instructions"]
        if name == "Groq": raise TimeoutError()
        return {"summary": "Người chơi chưa đồng ý và muốn tự xác minh."}
    with patch.object(memory.llm, "_compatible", side_effect=compatible), patch.object(memory, "request_json") as paid:
        result = memory.request_summary({"interaction_mode": "call", "new_turns": []}, 20)
    assert calls == ["Groq", "OpenRouter"] and result[1] == "OpenRouter"
    paid.assert_not_called()


class Pool:
    def __init__(self, handler):
        self.handler = handler; self.active = 0; self.sql = []
    @contextmanager
    def connection(self):
        self.active += 1
        try: yield self
        finally: self.active -= 1
    @contextmanager
    def cursor(self): yield self
    def execute(self, sql, parameters=()):
        self.sql.append((sql, parameters)); self.query = sql
    def fetchone(self): return self.handler(self.query, False)
    def fetchall(self): return self.handler(self.query, True)


def test_summary_cadence_no_database_lock_during_llm_and_stale_write_guard():
    state = {"turn_no": 4, "interaction_mode": "call", "title": "Mô phỏng", "ended_at": None,
             "summary_text": None, "covered_turn": None, "max_words": None, "updated_at": None, "opening": "Xin chào"}
    turns = [{"turn_no": i, "user_text_masked": "Tôi chưa chuyển tiền", "bot_reply_text": "Bạn muốn xác minh?"} for i in range(1, 5)]
    pool = Pool(lambda sql, many: turns if many else state)
    def summarize(context, limit):
        assert pool.active == 0
        assert len(context["new_turns"]) == 4 and limit == 150
        return "Người chơi chưa chuyển tiền và muốn xác minh.", "test"
    with patch.object(memory, "get_connection_pool", return_value=pool), patch.object(memory, "request_summary", side_effect=summarize) as llm:
        state["turn_no"] = 3; memory.update_summary(uuid4(), "owner"); llm.assert_not_called()
        state["turn_no"] = 4; memory.update_summary(uuid4(), "owner")
    inserts = [(q, p) for q, p in pool.sql if "INSERT INTO conversation_memories" in q]
    assert len(inserts) == 1
    assert "updated_at IS NOT DISTINCT FROM" in inserts[0][0]
    assert inserts[0][1][2:5] == (4, 150, 9)


def test_future_summary_not_used_for_regeneration_and_gap_is_included():
    pool = Pool(lambda sql, many: [{"turn_no": 2, "user_text_masked": "Không", "bot_reply_text": "Đã rõ"}] if many else None)
    with patch.object(memory, "get_connection_pool", return_value=pool):
        result = memory.memory_context(pool, "session", before_turn=4, recent_start=3)
    assert result["conversation_summary"] == ""
    assert result["earlier_unsummarized_turns"][0]["turn_no"] == 2
    assert pool.sql[0][1] == ("session", 4) and "covered_turn<%s" in pool.sql[0][0]


def test_contextual_line_bypasses_shared_cache_and_is_not_published():
    def handler(sql, many):
        if "SELECT payload" in sql: return {"payload": {"title": "Mô phỏng", "persona": {}}}
        if "SELECT node_key" in sql: return {"objective": "Hỏi rõ", "requested_action": "other"}
        if "SELECT turn_no" in sql: return [{"turn_no": 5, "user_text_masked": "Không", "intent": "refuse", "bot_reply_text": "Đã rõ"}]
        if many: return [{"line_text": "Cached reply", "line_id": 3}]
        return {"bot_reply_text": "Đã rõ"}
    pool = Pool(handler)
    with patch.object(lines, "get_connection_pool", return_value=pool), patch.object(lines, "_config", return_value=(True, True, "test", "v2", 1, 1)), \
         patch.object(lines, "memory_context", return_value={"conversation_summary": "Người chơi đã từ chối."}), \
         patch.object(lines, "_request_line", return_value="Bạn muốn làm rõ điều gì?") as generate:
        result = lines.resolve_bot_line(scenario_id=1,session_id="s",target_node=2,intent="refuse",user_text_masked="Không",fixed_text="Fixed reply.",is_reprompt=False)
    assert result.source == "llm" and result.line_id is None
    assert generate.call_args.args[0]["conversation_summary"]
    assert not any("INSERT INTO dialogue_lines" in q or "player_text_norm=%s" in q for q, _ in pool.sql)


def test_summary_view_is_private_to_session_owner():
    app = FastAPI(); app.include_router(router)
    session = uuid4()
    with TestClient(app) as client:
        assert client.get(f"/api/arena/calls/{session}/memory").status_code == 401
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "owner"}
    with patch("app.api.arena_routes.read_memory", side_effect=KeyError()) as read, TestClient(app) as client:
        assert client.get(f"/api/arena/calls/{session}/memory").status_code == 404
        assert read.call_args.args == (session, "owner")


def test_background_queue_is_bounded_and_finish_is_coalesced(monkeypatch):
    class Executor:
        def __init__(self): self.jobs = []
        def submit(self, *args): self.jobs.append(args)
    executor = Executor()
    monkeypatch.setattr(memory, "_executor", executor)
    monkeypatch.setattr(memory, "_pending", set())
    monkeypatch.setattr(memory, "_forced", set())
    for i in range(5): memory.schedule_summary(str(i), "owner")
    assert len(executor.jobs) == 4
    memory.schedule_summary("0", "owner", force=True)
    assert len(executor.jobs) == 4
    with patch.object(memory, "update_summary") as update:
        callback, *arguments = executor.jobs[0]
        callback(*arguments)
    assert update.call_count == 2 and update.call_args.args[-1] is True
    assert "0" not in memory._pending


def test_summary_fallback_obeys_total_deadline(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    monkeypatch.setenv("GROQ_API_KEY", "test")
    monkeypatch.setenv("CONVERSATION_SUMMARY_TIMEOUT_SECONDS", "1")
    now = [0.0]
    def slow(*args, **options):
        now[0] = 2.0
        raise TimeoutError()
    with patch.object(memory.time, "monotonic", side_effect=lambda: now[0]), \
         patch.object(memory.llm, "_gemini", side_effect=slow), patch.object(memory.llm, "_compatible") as fallback:
        assert memory.request_summary({"interaction_mode": "call"}, 150) is None
    fallback.assert_not_called()
