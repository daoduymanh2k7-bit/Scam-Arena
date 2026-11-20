from __future__ import annotations

import os
import tempfile
import threading
import logging
import time
from pathlib import Path

_model = None
_inference_lock = threading.Lock()
logger = logging.getLogger(__name__)


class SpeechBusy(RuntimeError):
    pass


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        _model = WhisperModel(
            os.getenv("WHISPER_MODEL", "base"),
            device="cpu",
            compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
            cpu_threads=2,
        )
    return _model


def speech_to_text(audio_bytes: bytes) -> str:
    # Do not accumulate a long request queue or run multiple CPU decoders at once.
    if not _inference_lock.acquire(blocking=False):
        raise SpeechBusy("Nhận diện đang bận. Vui lòng nói lại sau vài giây.")
    provider = os.getenv("STT_PROVIDER", "faster_whisper")
    started = time.monotonic()
    try:
        if provider == "whisper_cpp":
            from app.voice.whisper_cpp import transcribe

            return transcribe(audio_bytes)
        if provider == "faster_whisper":
            return _faster_whisper(audio_bytes)
        raise RuntimeError("STT_PROVIDER must be whisper_cpp or faster_whisper")
    finally:
        logger.info("speech_to_text provider=%s elapsed_ms=%d", provider,
                    round((time.monotonic() - started) * 1000))
        _inference_lock.release()


def _faster_whisper(audio_bytes: bytes) -> str:
    from app.voice.whisper_cpp import normalize_audio

    audio_bytes = normalize_audio(audio_bytes)
    file_descriptor, path = tempfile.mkstemp(suffix=".wav")
    try:
        with os.fdopen(file_descriptor, "wb") as audio_file:
            audio_file.write(audio_bytes)
        segments, _ = _get_model().transcribe(path, language="vi")
        return "".join(segment.text for segment in segments).strip()
    finally:
        Path(path).unlink(missing_ok=True)


def warmup_speech() -> None:
    """Preload the selected local model without racing an incoming request."""
    if os.getenv("STT_PROVIDER", "faster_whisper") != "faster_whisper":
        return
    if not _inference_lock.acquire(blocking=False):
        return
    try:
        _get_model()
    finally:
        _inference_lock.release()
