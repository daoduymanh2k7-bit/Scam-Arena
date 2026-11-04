from __future__ import annotations

import os
import tempfile
from pathlib import Path

from faster_whisper import WhisperModel

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = WhisperModel(
            os.getenv("WHISPER_MODEL", "base"),
            device="cpu",
            compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
        )
    return _model


def speech_to_text(audio_bytes: bytes) -> str:
    file_descriptor, path = tempfile.mkstemp(suffix=".webm")
    try:
        with os.fdopen(file_descriptor, "wb") as audio_file:
            audio_file.write(audio_bytes)
        segments, _ = _get_model().transcribe(path, language="vi")
        return "".join(segment.text for segment in segments).strip()
    finally:
        Path(path).unlink(missing_ok=True)
