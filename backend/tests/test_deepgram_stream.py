import asyncio
import json
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.api import voice_routes
from app.voice import deepgram, deepgram_stream as stream


def result(text, start=0, final=True):
    return {"type": "Results", "start": start, "is_final": final,
            "channel": {"alternatives": [{"transcript": text}]}}


def test_final_text_uses_all_final_segments_never_interim_or_duplicate():
    t = stream.Transcript()
    assert t.update(result("Tôi đồng ý", final=False)) == "Tôi đồng ý"
    assert t.final() == ""
    t.update(result("Tôi chưa đồng ý."))
    t.update(result("Tôi chưa đồng ý."))
    t.update(result("Để tôi kiểm tra.", start=1.5))
    assert t.final() == "Tôi chưa đồng ý. Để tôi kiểm tra."


class Browser:
    def __init__(self, messages):
        self.messages = iter(messages)
        self.events = []

    async def receive(self):
        try:
            return next(self.messages)
        except StopIteration:
            await asyncio.Future()

    async def send_json(self, event):
        self.events.append(event)


def test_relay_waits_for_close_stream_metadata_and_releases_slot(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "server-test-secret")
    monkeypatch.setenv("DEEPGRAM_LANGUAGE", "vi")
    sent = []
    options = {}

    async def run():
        queue = asyncio.Queue()

        class Upstream:
            async def send(self, message):
                sent.append(message)
                if isinstance(message, str):
                    await queue.put(json.dumps(result("Không đọc mã.")))
                    await queue.put(json.dumps(result("Tôi sẽ xác minh.", start=1)))
                    await queue.put('{"type":"Metadata"}')

            def __aiter__(self): return self
            async def __anext__(self): return await queue.get()

        @asynccontextmanager
        async def connect(url, **kwargs):
            options.update(url=url, **kwargs)
            yield Upstream()

        browser = Browser([{"type": "websocket.receive", "bytes": b"\1\0" * 512},
                           {"type": "websocket.receive", "text": '{"type":"finish"}'}])
        with patch.object(stream, "connect", connect):
            await stream.relay(browser, "test-stream-user")
        assert browser.events[-1]["type"] == "final"
        assert browser.events[-1]["text"] == "Không đọc mã. Tôi sẽ xác minh."
        assert browser.events[-1]["transport"] == "websocket"
        assert "server-test-secret" not in json.dumps(browser.events)

    asyncio.run(run())
    assert options["additional_headers"]["Authorization"] == "Token server-test-secret"
    assert "language=vi" in options["url"] and "endpointing=false" in options["url"]
    assert sent[-1] == '{"type": "CloseStream"}'
    assert "test-stream-user" not in deepgram._active


def test_disconnect_and_bad_audio_release_slot(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "server-test-secret")

    class Upstream:
        async def send(self, message): pass
        def __aiter__(self): return self
        async def __anext__(self): await asyncio.Future()

    @asynccontextmanager
    async def connect(*args, **kwargs): yield Upstream()

    for message in [{"type": "websocket.disconnect"}, {"type": "websocket.receive", "bytes": b"x"}]:
        with patch.object(stream, "connect", connect), pytest.raises((ValueError, ConnectionError)):
            asyncio.run(stream.relay(Browser([message]), "test-disconnect"))
        assert "test-disconnect" not in deepgram._active


def test_missing_final_metadata_times_out_without_committing_draft(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "server-test-secret")

    class Upstream:
        async def send(self, message): pass
        def __aiter__(self): return self
        async def __anext__(self): await asyncio.Future()

    @asynccontextmanager
    async def connect(*args, **kwargs): yield Upstream()

    async def no_sleep(delay): pass

    browser = Browser([{"type": "websocket.receive", "bytes": b"\0\0" * 512},
                       {"type": "websocket.receive", "text": '{"type":"finish"}'}])
    with patch.object(stream, "connect", connect), patch.object(stream.asyncio, "sleep", no_sleep):
        with pytest.raises(TimeoutError): asyncio.run(stream.relay(browser, "test-timeout"))
    assert "test-timeout" not in deepgram._active
    assert not any(event["type"] == "final" for event in browser.events)


def test_websocket_rejects_foreign_origin_and_unauthenticated_users():
    app = FastAPI()
    app.include_router(voice_routes.router)
    with TestClient(app) as client:
        with patch.object(voice_routes, "get_current_user") as auth:
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect('/api/voice/transcribe/stream', headers={"origin": "https://evil.example"}): pass
            auth.assert_not_called()
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/api/voice/transcribe/stream', headers={"origin": "http://testserver"}): pass


def test_authenticated_stream_sanitizes_errors_and_disabled_provider(monkeypatch):
    app = FastAPI()
    app.include_router(voice_routes.router)
    monkeypatch.setenv("STT_PROVIDER", "deepgram")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "server-test-secret")

    async def broken(*args): raise RuntimeError("server-test-secret upstream body")

    with TestClient(app) as client, patch.object(voice_routes, "get_current_user", return_value={"user_id": "u"}):
        with patch.object(stream, "relay", broken):
            with client.websocket_connect('/api/voice/transcribe/stream', headers={"origin": "http://testserver"}) as ws:
                event = ws.receive_json()
                assert event["type"] == "error"
                assert "server-test-secret" not in json.dumps(event)
        monkeypatch.setenv("DEEPGRAM_STREAMING_ENABLED", "false")
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/api/voice/transcribe/stream', headers={"origin": "http://testserver"}): pass
