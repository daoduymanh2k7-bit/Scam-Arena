from __future__ import annotations

import io
import os
import re
import wave
import hashlib
import json
import threading
from app.voice.tts_cache import AudioCache

_audio_cache=AudioCache()
_synthesis_lock=threading.Lock()
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


def _render_audio(text: str, voice_id: str = "default") -> bytes:
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


def synthesize_cached(text: str,voice_id: str='default'):
    path=_default_voice_path()
    if voice_id in CALLER_PRESETS:path=path.with_name(CALLER_MODEL)
    signature=[]
    for file in [path,path.with_suffix('.onnx.json')]:
        stat=file.stat();signature.append((str(file.resolve()),stat.st_size,stat.st_mtime_ns))
    preset=CALLER_PRESETS.get(voice_id)
    settings={name:getattr(preset,name,None) for name in ['speaker_id','length_scale','noise_scale','noise_w_scale']}
    key=hashlib.sha256(json.dumps([text,voice_id,signature,settings,os.getenv('PIPER_SENTENCE_PAUSE_MS','350')],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    def build():
        # Avoid oversubscribing the small VPS with concurrent ONNX inference.
        with _synthesis_lock:return _render_audio(text,voice_id)
    if os.getenv('TTS_CACHE_ENABLED','true').lower() not in {'true','1'}:return build(),False
    return _audio_cache.get(key,build)


def text_to_speech(text: str,voice_id: str='default') -> bytes:
    return synthesize_cached(text,voice_id)[0]


def prewarm_audio():
    if os.getenv('TTS_PREWARM_ENABLED','true').lower() in {'true','1'}:
        for voice in ['default']+available_caller_voices():text_to_speech('Alo?',voice)
