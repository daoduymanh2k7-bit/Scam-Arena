import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from app.voice import transcription
from test_transcription import client, wav_bytes


@pytest.fixture(autouse=True)
def isolated_decoder(monkeypatch):
    monkeypatch.setattr(transcription, "_inference_lock", threading.Lock())
    from app.voice.scheduling import SpeechScheduler
    monkeypatch.setattr(transcription, "_scheduler", SpeechScheduler())
    monkeypatch.setenv("STT_PROVIDER", "faster_whisper")
    monkeypatch.setenv("STT_PARTIAL_ENABLED", "true")


def test_decoder_failure_releases_scheduler():
    with patch.object(transcription, "_faster_whisper", side_effect=RuntimeError("failure")):
        with pytest.raises(RuntimeError): transcription.speech_to_text_partial(b"audio", user_id="p1")
    with patch.object(transcription, "_faster_whisper", return_value="final"):
        assert transcription.speech_to_text(b"audio", user_id="p2") == "final"
    assert transcription._scheduler.active is None


def test_preview_decoder_uses_bounded_greedy_options():
    def decode(path, **options):
        assert options["beam_size"] == options["best_of"] == 1
        assert options["temperature"] == 0.0
        assert options["condition_on_previous_text"] is False
        return iter([SimpleNamespace(text="draft")]), None
    with patch.object(transcription, "_get_model", return_value=SimpleNamespace(transcribe=decode)):
        assert transcription._faster_whisper(wav_bytes(seconds=1), preview=True) == "draft"


def test_partial_endpoint_is_authenticated_and_never_final():
    with client() as api, patch.object(transcription, "speech_to_text_partial", return_value="Tôi không") as decode:
        response = api.post("/api/voice/transcribe/partial", files={"audio": ("draft.wav", wav_bytes(seconds=1))})
    assert response.status_code == 200
    assert response.json()["text"] == "Tôi không"
    assert response.json()["is_final"] is False
    assert 1000 <= response.json()["next_partial_ms"] <= 5000
    assert decode.call_args.kwargs["user_id"] == "test-client"
    assert response.headers["cache-control"] == "no-store"
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.voice_routes import router
    app = FastAPI(); app.include_router(router)
    with TestClient(app) as api:
        assert api.post("/api/voice/transcribe/partial", files={"audio": ("x.wav", b"bad")}).status_code == 401


@pytest.mark.parametrize("data,status", [(b"bad", 400), (b"x" * (512 * 1024 + 1), 413),
    (wav_bytes(seconds=16), 400), (wav_bytes(rate=48000, seconds=1), 400)],
    ids=["invalid", "oversize", "duration", "sample-rate"])
def test_partial_rejects_unbounded_or_wrong_audio(data, status):
    with client() as api, patch.object(transcription, "speech_to_text_partial") as decode:
        assert api.post("/api/voice/transcribe/partial", files={"audio": ("x.wav", data)}).status_code == status
        decode.assert_not_called()


def test_partial_can_be_disabled_without_affecting_final(monkeypatch):
    monkeypatch.setenv("STT_PARTIAL_ENABLED", "false")
    with client() as api:
        assert api.post("/api/voice/transcribe/partial", files={"audio": ("x.wav", wav_bytes(seconds=1))}).status_code == 409
    with patch.object(transcription, "_faster_whisper", return_value="final"):
        assert transcription.speech_to_text(b"audio") == "final"
