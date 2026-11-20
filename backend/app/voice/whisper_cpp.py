"""Private whisper.cpp sidecar client; public uploads go through FastAPI auth."""
from __future__ import annotations

import io
import json
import os
import uuid
import wave
from urllib.request import Request, urlopen

MAX_AUDIO_SECONDS = 30


class InvalidAudio(ValueError):
    pass


def normalize_audio(audio: bytes) -> bytes:
    """Decode WAV/WebM into bounded mono 16-kHz PCM16 for whisper-server."""
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


def transcribe(audio: bytes) -> str:
    wav = normalize_audio(audio)
    boundary = "scam-arena-" + uuid.uuid4().hex
    fields = {"language": "vi", "response_format": "json", "temperature": "0.0",
              "temperature_inc": "0.0", "translate": "false"}
    chunks = []
    for name, value in fields.items():
        chunks.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
                       f'\r\n\r\n{value}\r\n').encode())
    chunks.extend([
        (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
         'filename="speech.wav"\r\nContent-Type: audio/wav\r\n\r\n').encode(),
        wav, f"\r\n--{boundary}--\r\n".encode(),
    ])
    base_url = os.getenv("WHISPER_CPP_URL", "http://whisper-cpp:8080").rstrip("/")
    request = Request(base_url + "/inference", data=b"".join(chunks), method="POST",
                      headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    timeout = float(os.getenv("WHISPER_CPP_TIMEOUT_SECONDS", "45"))
    with urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    if not isinstance(payload, dict) or not isinstance(payload.get("text"), str):
        raise RuntimeError("whisper.cpp returned an invalid transcription response")
    return payload["text"].strip()
