from __future__ import annotations

import os
import tempfile
import threading
import logging
import time
from pathlib import Path

_model = None
_inference_lock = threading.Lock()
_state_lock = threading.Lock()
_preview_active = False
_final_waiting = False
_last_preview_at = float("-inf")
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
    return _transcribe(audio_bytes, preview=False)


def speech_to_text_partial(audio_bytes: bytes) -> str:
    if (os.getenv("STT_PARTIAL_ENABLED", "true").strip().lower() not in {"true", "1"}
            or os.getenv("STT_PROVIDER", "faster_whisper") != "faster_whisper"):
        raise ValueError("Incremental transcription is unavailable")
    return _transcribe(audio_bytes, preview=True)


def _claim_decoder(preview: bool) -> None:
    """One CPU decoder; at most one final may wait for an active preview."""
    global _preview_active, _final_waiting, _last_preview_at
    with _state_lock:
        if preview and (_final_waiting or time.monotonic() - _last_preview_at < 2.0):
            raise SpeechBusy("Nhận diện tạm đang bận.")
        if _inference_lock.acquire(blocking=False):
            _preview_active = preview
            if preview:
                _last_preview_at = time.monotonic()
            return
        if preview or not _preview_active or _final_waiting:
            raise SpeechBusy("Nhận diện đang bận. Vui lòng nói lại sau vài giây.")
        _final_waiting = True
    try:
        if not _inference_lock.acquire(timeout=5):
            raise SpeechBusy("Nhận diện đang bận. Vui lòng nói lại sau vài giây.")
        with _state_lock:
            _preview_active = False
    finally:
        with _state_lock:
            _final_waiting = False


def _transcribe(audio_bytes: bytes, *, preview: bool) -> str:
    global _preview_active
    _claim_decoder(preview)
    provider = os.getenv("STT_PROVIDER", "faster_whisper")
    started = time.monotonic()
    try:
        if provider == "whisper_cpp":
            from app.voice.whisper_cpp import transcribe

            return transcribe(audio_bytes)
        if provider == "faster_whisper":
            return _faster_whisper(audio_bytes, preview=True) if preview else _faster_whisper(audio_bytes)
        raise RuntimeError("STT_PROVIDER must be whisper_cpp or faster_whisper")
    finally:
        logger.info("speech_to_text provider=%s partial=%s elapsed_ms=%d", provider, preview,
                    round((time.monotonic() - started) * 1000))
        with _state_lock:
            _preview_active = False
            _inference_lock.release()


def decoder_beam_size() -> int:
    value = int(os.getenv("WHISPER_BEAM_SIZE", "3"))
    if value not in (1, 3, 5):
        raise ValueError("WHISPER_BEAM_SIZE must be 1, 3 or 5")
    return value


def _faster_whisper(audio_bytes: bytes, *, beam_size: int | None = None, preview: bool = False) -> str:
    from app.voice.whisper_cpp import normalize_audio

    audio_bytes = normalize_audio(audio_bytes)
    file_descriptor, path = tempfile.mkstemp(suffix=".wav")
    try:
        with os.fdopen(file_descriptor, "wb") as audio_file:
            audio_file.write(audio_bytes)
        options = {"beam_size": decoder_beam_size() if beam_size is None else beam_size}
        if preview:
            options.update(beam_size=1, best_of=1, temperature=0.0, condition_on_previous_text=False)
        segments, _ = _get_model().transcribe(path, language="vi", **options)
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
