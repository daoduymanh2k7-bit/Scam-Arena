import io
import json
import threading
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

from app.voice import deepgram, transcription
from app.voice.scheduling import SpeechBusy
from test_transcription import wav_bytes, client


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-private-key")
    monkeypatch.setenv("DEEPGRAM_MODEL", "nova-3")
    monkeypatch.setenv("DEEPGRAM_LANGUAGE", "vi")
    monkeypatch.setattr(deepgram, "_active", {})
    monkeypatch.setattr(deepgram, "_lock", threading.Lock())


def test_request_is_vi_pcm_with_server_only_key():
    body = {"results": {"channels": [{"alternatives": [{"transcript": "Tôi chưa đồng ý."}]}]}}
    with patch.object(deepgram, "urlopen", return_value=io.BytesIO(json.dumps(body).encode())) as send:
        assert deepgram.transcribe(wav_bytes(48000, 2), user_id="u") == "Tôi chưa đồng ý."
    request = send.call_args.args[0]
    assert urlparse(request.full_url).hostname == "api.deepgram.com"
    assert parse_qs(urlparse(request.full_url).query)["language"] == ["vi"]
    assert request.get_header("Authorization") == "Token test-private-key"
    assert "test-private-key" not in request.full_url
    import wave
    with wave.open(io.BytesIO(request.data)) as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
        assert wav.getnframes() == 23200  # 100ms fixture plus 1.35s context.
        assert wav.readframes(16000) == b"\0" * 32000
    assert not deepgram._active


def test_cloud_slots_allow_four_users_and_reject_duplicate_accounts():
    with deepgram.slot("a"), deepgram.slot("b"), deepgram.slot("c"), deepgram.slot("d"):
        with pytest.raises(SpeechBusy):
            with deepgram.slot("fifth"): pass
        with pytest.raises(SpeechBusy):
            with deepgram.slot("a"): pass
    assert not deepgram._active


@pytest.mark.parametrize("status,exception", [(401, RuntimeError), (402, RuntimeError), (429, SpeechBusy)])
def test_errors_release_slot_and_do_not_expose_private_upstream_body(status, exception):
    error = HTTPError("https://api.deepgram.com", status, "failed", {}, io.BytesIO(b"private diagnostics"))
    with patch.object(deepgram, "urlopen", side_effect=error):
        with pytest.raises(exception) as result:
            deepgram.transcribe(wav_bytes(), user_id="u")
    assert "private diagnostics" not in str(result.value)
    assert not deepgram._active


def test_missing_key_does_not_send_audio(monkeypatch):
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    with patch.object(deepgram, "urlopen") as send:
        with pytest.raises(RuntimeError, match="not configured"):
            deepgram.transcribe(wav_bytes(), user_id="u")
    send.assert_not_called()


def test_selected_cloud_provider_avoids_local_cpu_lock_and_repeated_previews(monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "deepgram")
    monkeypatch.setattr(transcription, "_inference_lock", threading.Lock())
    transcription._inference_lock.acquire()
    try:
        with patch.object(deepgram, "transcribe", return_value="Để tôi kiểm tra.") as decode:
            assert transcription.speech_to_text(b"clip", user_id="u") == "Để tôi kiểm tra."
            with pytest.raises(ValueError): transcription.speech_to_text_partial(b"clip", user_id="u")
            assert decode.call_count == 1
    finally:
        transcription._inference_lock.release()


def test_api_metadata_reports_deepgram_without_returning_a_key(monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "deepgram")
    with client() as api, patch.object(transcription, "speech_to_text", return_value="Tôi tự kiểm tra."):
        result = api.post("/api/voice/transcribe", files={"audio": ("voice.wav", b"clip", "audio/wav")})
        status = api.get("/api/voice/stt-status")
    assert result.json()["engine"] == "Deepgram" and result.json()["model"] == "nova-3"
    assert status.json()["key_configured"] is True
    assert status.json()["key_verified"] is False
    assert "test-private-key" not in result.text + status.text
