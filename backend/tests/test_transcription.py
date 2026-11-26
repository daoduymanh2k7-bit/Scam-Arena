import asyncio
import io
import struct
import threading
import wave
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import voice_routes
from app.auth import get_current_user
from app.voice import transcription, audio


def wav_bytes(rate=16000, channels=1, seconds=0.1):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(struct.pack("<h", 1000) * round(rate * seconds) * channels)
    return output.getvalue()


def test_normalizes_stereo_48khz_to_mono_pcm16():
    data = audio.normalize_audio(wav_bytes(48000, 2))
    with wave.open(io.BytesIO(data)) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
        assert wav.getnframes() == 1600


def test_normalizes_webm_from_message_recorder():
    import av
    import numpy as np

    source = io.BytesIO()
    with av.open(source, mode="w", format="webm") as container:
        stream = container.add_stream("libopus", rate=48000)
        frame = av.AudioFrame.from_ndarray(np.full((1, 4800), 0.05, dtype=np.float32),
                                          format="flt", layout="mono")
        frame.sample_rate = 48000
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    data = audio.normalize_audio(source.getvalue())
    with wave.open(io.BytesIO(data)) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
        assert 1500 <= wav.getnframes() <= 1800


@pytest.mark.parametrize("content", [b"invalid", b"", wav_bytes(seconds=31)], ids=["invalid", "empty", "too_long"])
def test_rejects_invalid_or_long_audio(content):
    with pytest.raises(audio.InvalidAudio):
        audio.normalize_audio(content)


def test_cpu_busy_and_failure_release_lock(monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "faster_whisper")
    transcription._inference_lock.acquire()
    try:
        with pytest.raises(transcription.SpeechBusy):
            transcription.speech_to_text(b"unused")
    finally:
        transcription._inference_lock.release()
    with patch.object(transcription, "_faster_whisper", side_effect=RuntimeError("failed")):
        with pytest.raises(RuntimeError):
            transcription.speech_to_text(b"unused")
    with patch.object(transcription, "_faster_whisper", return_value="Tôi không đồng ý."):
        assert transcription.speech_to_text(b"unused") == "Tôi không đồng ý."


def test_explicit_legacy_provider(monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "faster_whisper")
    with patch.object(transcription, "_faster_whisper", return_value="Alo") as old:
        assert transcription.speech_to_text(b"audio") == "Alo"
        old.assert_called_once_with(b"audio")


def test_default_selects_faster_whisper(monkeypatch):
    monkeypatch.delenv("STT_PROVIDER", raising=False)
    with patch.object(transcription, "_faster_whisper", return_value="Tôi không đồng ý.") as selected:
        assert transcription.speech_to_text(b"audio") == "Tôi không đồng ý."
        selected.assert_called_once_with(b"audio")


def test_faster_normalizes_audio_and_removes_temporary_file():
    paths = []

    def decode(path, **kwargs):
        from pathlib import Path

        paths.append(Path(path))
        with wave.open(path) as wav:
            assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
        assert kwargs["language"] == "vi"
        return iter([SimpleNamespace(text="Tôi không chuyển tiền.")]), None

    with patch.object(transcription, "_get_model", return_value=SimpleNamespace(transcribe=decode)):
        assert transcription._faster_whisper(wav_bytes(48000, 2)) == "Tôi không chuyển tiền."
    assert paths and not paths[0].exists()


def test_warmup_only_loads_selected_engine_and_respects_inference(monkeypatch):
    with patch.object(transcription, "_get_model") as load:
        monkeypatch.setenv("STT_PROVIDER", "deepgram")
        transcription.warmup_speech()
        load.assert_not_called()
        monkeypatch.setenv("STT_PROVIDER", "faster_whisper")
        transcription._inference_lock.acquire()
        try:
            transcription.warmup_speech()
            load.assert_not_called()
        finally:
            transcription._inference_lock.release()
        transcription.warmup_speech()
        load.assert_called_once()


def client():
    app = FastAPI()
    app.include_router(voice_routes.router)
    app.dependency_overrides[get_current_user] = lambda: {"role": "user", "user_id": "test-client"}
    return TestClient(app)


@pytest.mark.parametrize("error,status", [
    (transcription.SpeechBusy("busy"), 429),
    (audio.InvalidAudio("bad audio"), 400),
    (TimeoutError("private internal error"), 503),
])
def test_api_maps_audio_errors_without_leaking_details(error, status):
    with client() as api, patch.object(transcription, "speech_to_text", side_effect=error):
        result = api.post("/api/voice/transcribe", files={"audio": ("voice.wav", b"audio", "audio/wav")})
    assert result.status_code == status
    assert "private internal error" not in result.text
    if status == 429:
        assert result.headers["retry-after"] == "2"


def test_api_runs_decoder_off_event_loop(monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "deepgram")

    def decode(_, **options):
        assert threading.current_thread() is not threading.main_thread()
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        return "Tôi sẽ tự xác minh."

    with client() as api, patch.object(transcription, "speech_to_text", side_effect=decode):
        result = api.post("/api/voice/transcribe", files={"audio": ("voice.wav", b"audio", "audio/wav")})
    assert result.status_code == 200
    assert result.json()["text"] == "Tôi sẽ tự xác minh."
    assert result.json()["engine"] == "Deepgram"
    assert result.json()["model"] == "nova-3"
    assert isinstance(result.json()["elapsed_ms"], int)


def test_api_requires_auth():
    app = FastAPI()
    app.include_router(voice_routes.router)
    with TestClient(app) as api:
        assert api.post("/api/voice/transcribe", files={"audio": ("voice.wav", b"audio")}).status_code == 401


@pytest.mark.parametrize("beam", [1, 3, 5])
def test_beam_selection_is_applied_to_decoder(monkeypatch, beam):
    monkeypatch.setenv("WHISPER_BEAM_SIZE", str(beam))
    def decode(path, **kwargs):
        assert kwargs["beam_size"] == beam
        return iter([SimpleNamespace(text="Không đồng ý.")]), None
    with patch.object(transcription, "_get_model", return_value=SimpleNamespace(transcribe=decode)):
        assert transcription._faster_whisper(wav_bytes()) == "Không đồng ý."


def test_invalid_beam_is_not_silently_applied(monkeypatch):
    monkeypatch.setenv("WHISPER_BEAM_SIZE", "999")
    with pytest.raises(ValueError):
        transcription.decoder_beam_size()


def test_tts_returns_server_timing_without_changing_audio():
    import sys
    fake = SimpleNamespace(available_caller_voices=lambda: [], synthesize_cached=lambda *_: (b"RIFFtest",False))
    with patch.dict(sys.modules, {"app.voice.synthesis": fake}), client() as api:
        result = api.post("/api/voice/speak", json={"text": "Alo"})
    assert result.status_code == 200
    assert result.content == b"RIFFtest"
    assert result.headers["server-timing"].startswith("tts;dur=")
    assert result.headers["cache-control"] == "no-store"
