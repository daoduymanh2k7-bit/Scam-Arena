from __future__ import annotations

import io
import os
import wave
from pathlib import Path

from piper import PiperVoice

_voice = None
DEFAULT_MODEL = Path(__file__).resolve().parents[3] / "voices" / "vi_VN-vais1000-medium.onnx"


def _get_voice() -> PiperVoice:
    global _voice
    if _voice is None:
        model_path = Path(os.getenv("PIPER_VOICE_PATH", str(DEFAULT_MODEL)))
        if not model_path.is_file():
            raise FileNotFoundError(f"Không tìm thấy model Piper: {model_path}")
        _voice = PiperVoice.load(str(model_path))
    return _voice


def text_to_speech(text: str) -> bytes:
    chunks = list(_get_voice().synthesize(text))
    if not chunks:
        raise ValueError("Không tạo được âm thanh từ văn bản rỗng.")
    first = chunks[0]
    pause_ms = int(os.getenv("PIPER_SENTENCE_PAUSE_MS", "350"))
    silence = b"\x00" * (int(first.sample_rate * pause_ms / 1000) * first.sample_width * first.sample_channels)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setframerate(first.sample_rate)
        output.setsampwidth(first.sample_width)
        output.setnchannels(first.sample_channels)
        for index, chunk in enumerate(chunks):
            output.writeframes(chunk.audio_int16_bytes)
            if index < len(chunks) - 1:
                output.writeframes(silence)
    return buffer.getvalue()
