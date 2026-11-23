"""Bounded audio decoding shared by cloud and local speech recognition."""
from __future__ import annotations

import io
import wave

MAX_AUDIO_SECONDS = 30


class InvalidAudio(ValueError):
    pass


def normalize_audio(audio: bytes) -> bytes:
    """Decode WAV/WebM into bounded mono 16-kHz PCM16 for speech recognition."""
    import av

    pcm = bytearray()
    limit = 16000 * 2 * MAX_AUDIO_SECONDS
    try:
        with av.open(io.BytesIO(audio)) as container:
            if not container.streams.audio:
                raise InvalidAudio("Không tìm thấy âm thanh trong tệp.")
            resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
            for frame in container.decode(audio=0):
                for converted in resampler.resample(frame):
                    pcm.extend(converted.to_ndarray().tobytes())
                    if len(pcm) > limit:
                        raise InvalidAudio("Mỗi đoạn nhận diện tối đa 30 giây.")
            for converted in resampler.resample(None):
                pcm.extend(converted.to_ndarray().tobytes())
    except InvalidAudio:
        raise
    except Exception as exc:
        raise InvalidAudio("Tệp âm thanh không hợp lệ hoặc không đọc được.") from exc
    if not pcm:
        raise InvalidAudio("Tệp âm thanh rỗng.")
    if len(pcm) > limit:
        raise InvalidAudio("Mỗi đoạn nhận diện tối đa 30 giây.")
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(pcm)
    return output.getvalue()
