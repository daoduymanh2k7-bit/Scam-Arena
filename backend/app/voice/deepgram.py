"""Deepgram REST transcription of bounded clips; credentials stay server-side."""
from contextlib import contextmanager
import io
import json
import os
import threading
import wave
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.voice.scheduling import SpeechBusy

_lock = threading.Lock()
_active = {}


@contextmanager
def slot(user_id):
    user_id = str(user_id)
    with _lock:
        if user_id in _active or len(_active) >= 4:
            raise SpeechBusy("Nhận diện đang bận. Âm thanh đã lưu có thể thử lại sau.", retry_after=3)
        _active[user_id] = True
    try:
        yield
    finally:
        with _lock:
            _active.pop(user_id, None)


def metadata():
    return {"engine": "Deepgram", "model": os.getenv("DEEPGRAM_MODEL", "nova-3").strip() or "nova-3",
            "compute_type": "cloud", "beam_size": 0}


def transcribe(content: bytes, *, user_id: str) -> str:
    from app.voice.audio import normalize_audio

    key = os.getenv("DEEPGRAM_API_KEY", "").strip()
    if not key:
        raise RuntimeError("DEEPGRAM_API_KEY is not configured")
    with slot(user_id):
        audio = normalize_audio(content)
        # Short Vietnamese clips in real API checks lost their onset or returned
        # empty. Give the detector context without altering the spoken samples.
        # This adds 1.35 seconds to transmitted audio and can increase billed usage.
        with wave.open(io.BytesIO(audio), "rb") as source:
            pcm = source.readframes(source.getnframes())
        padded = io.BytesIO()
        with wave.open(padded, "wb") as output:
            output.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            output.writeframes(b"\0" * 32000 + pcm + b"\0" * 11200)
        audio = padded.getvalue()
        query = urlencode({"model": metadata()["model"], "language": os.getenv("DEEPGRAM_LANGUAGE", "vi").strip() or "vi",
                           "punctuate": "true", "smart_format": "false"})
        request = Request("https://api.deepgram.com/v1/listen?" + query, data=audio,
                          headers={"Authorization": "Token " + key, "Content-Type": "audio/wav"}, method="POST")
        try:
            timeout = max(1., min(30., float(os.getenv("DEEPGRAM_TIMEOUT_SECONDS", "15"))))
            with urlopen(request, timeout=timeout) as response:
                body = json.loads(response.read(2 * 1024 * 1024).decode("utf-8"))
        except HTTPError as exc:
            if exc.code == 429:
                raise SpeechBusy("Deepgram đang giới hạn yêu cầu. Vui lòng thử lại sau.", retry_after=5) from None
            # Do not return upstream response bodies or credentials to logs/UI.
            raise RuntimeError(f"Deepgram HTTP {exc.code}") from None
        try:
            text = body["results"]["channels"][0]["alternatives"][0]["transcript"]
        except (KeyError, IndexError, TypeError):
            raise ValueError("Deepgram returned an invalid transcript") from None
        if not isinstance(text, str) or len(text) > 10000:
            raise ValueError("Deepgram returned an invalid transcript")
        return text.strip()
