from __future__ import annotations

import io
import os
import re
import wave
from functools import lru_cache
from pathlib import Path

from piper import PiperVoice, SynthesisConfig

DEFAULT_MODEL = Path(__file__).resolve().parents[3] / "voices" / "vi_VN-vais1000-medium.onnx"
CALLER_MODEL = "vi_VN-csa-voice-piper-v3-medium.onnx"
CALLER_PRESETS = {
    "ngoc-lan": SynthesisConfig(speaker_id=0, length_scale=1.0),
    "minh-anh": SynthesisConfig(speaker_id=1, length_scale=1.2),
    "quang-huy": SynthesisConfig(speaker_id=2, length_scale=1.2),
}


def _default_voice_path() -> Path:
    return Path(os.getenv("PIPER_VOICE_PATH", str(DEFAULT_MODEL)))


def available_caller_voices() -> list[str]:
    path = _default_voice_path().with_name(CALLER_MODEL)
    if path.is_file() and path.with_suffix(".onnx.json").is_file():
        return list(CALLER_PRESETS)
    return []


@lru_cache(maxsize=2)
def _get_voice(model_path: Path) -> PiperVoice:
    if not model_path.is_file():
        raise FileNotFoundError(f"Không tìm thấy model Piper: {model_path}")
    return PiperVoice.load(str(model_path))


def text_to_speech(text: str, voice_id: str = "default") -> bytes:
    path = _default_voice_path()
    preset = CALLER_PRESETS.get(voice_id)
    if preset is not None:
        path = path.with_name(CALLER_MODEL)
        text = re.sub(r"\bOTP\b", "ô tê pê", text, flags=re.IGNORECASE)
    chunks = list(_get_voice(path).synthesize(text, preset))
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
