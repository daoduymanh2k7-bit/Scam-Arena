from __future__ import annotations

import os
import time
import io
import wave
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from app.schemas import SpeakRequest
from app.auth import get_current_user
from app.database import get_connection_pool

router = APIRouter(prefix="/api/voice", tags=["voice"])
MAX_AUDIO_BYTES = 15 * 1024 * 1024


@router.get("/stt-status")
def stt_status(user: dict = Depends(get_current_user)):
    """Configuration presence only, never a paid probe or key validity claim."""
    provider = os.getenv("STT_PROVIDER", "faster_whisper")
    if provider == "deepgram":
        from app.voice.deepgram import metadata
        return {"provider": provider, **metadata(), "key_configured": bool(os.getenv("DEEPGRAM_API_KEY", "").strip()),
                "language": os.getenv("DEEPGRAM_LANGUAGE", "vi"), "transport": "bounded_audio_clips",
                "streaming_enabled": os.getenv("DEEPGRAM_STREAMING_ENABLED", "true").lower() in {"true", "1"},
                "key_verified": False}
    return {"provider": provider, "key_required": False, "key_verified": False}


@router.websocket("/transcribe/stream")
async def transcribe_stream(websocket: WebSocket):
    # Cookie authentication alone is insufficient for cross-site WebSocket requests.
    origin = urlsplit(websocket.headers.get("origin", ""))
    if origin.scheme not in {"http", "https"} or origin.netloc != websocket.headers.get("host"):
        await websocket.close(code=1008)
        return
    from app.auth import COOKIE_NAME
    try:
        user = await run_in_threadpool(get_current_user, token=websocket.cookies.get(COOKIE_NAME))
    except HTTPException:
        await websocket.close(code=1008)
        return
    from app.voice.deepgram_stream import enabled, relay
    if not enabled():
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        await relay(websocket, str(user["user_id"]))
    except (WebSocketDisconnect, ConnectionError):
        pass
    except Exception:
        # Never expose provider messages, credentials or audio through diagnostics.
        try:
            await websocket.send_json({"type": "error", "message": "Streaming chưa sẵn sàng; chuyển sang nhận diện cả câu."})
        except (RuntimeError, WebSocketDisconnect):
            pass
    finally:
        try:
            await websocket.close()
        except (RuntimeError, WebSocketDisconnect):
            pass


@router.post("/transcribe/partial")
async def transcribe_partial(response: Response, audio: UploadFile = File(...),
                             user: dict = Depends(get_current_user)) -> dict:
    """Bounded growing WAV snapshots; drafts never enter conversation state."""
    content = await audio.read(512 * 1024 + 1)
    await audio.close()
    if len(content) > 512 * 1024:
        raise HTTPException(status_code=413, detail="Đoạn nhận diện tạm quá lớn.")
    try:
        with wave.open(io.BytesIO(content), "rb") as wav:
            frames = wav.getnframes()
            if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2) or not 8000 <= frames <= 240000:
                raise ValueError("Invalid preview format")
            if len(wav.readframes(frames)) != frames * 2:
                raise ValueError("Truncated preview")
    except (wave.Error, EOFError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Đoạn tạm cần WAV mono 16 kHz, dài 0,5–15 giây.") from exc
    from app.voice.transcription import speech_to_text_partial, SpeechBusy, partial_interval_ms
    try:
        started = time.monotonic()
        text = await run_in_threadpool(speech_to_text_partial, content, user_id=str(user["user_id"]))
        response.headers["Cache-Control"] = "no-store"
        return {"text": text, "is_final": False, "next_partial_ms": partial_interval_ms(), "engine": "Faster-Whisper", "beam_size": 1,
                "elapsed_ms": round((time.monotonic() - started) * 1000)}
    except SpeechBusy as exc:
        raise HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": str(exc.retry_after)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Nhận diện tạm chưa được bật cho cấu hình này.") from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Nhận diện tạm chưa sẵn sàng.") from exc


@router.post("/transcribe")
async def transcribe(audio: UploadFile = File(...), user: dict = Depends(get_current_user)) -> dict[str, str | int]:
    content = await audio.read(MAX_AUDIO_BYTES + 1)
    await audio.close()
    if not content:
        raise HTTPException(status_code=400, detail="Tệp âm thanh rỗng.")
    if len(content) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Tệp âm thanh vượt giới hạn 15 MB.")

    from app.voice.transcription import SpeechBusy, speech_to_text, decoder_beam_size
    from app.voice.audio import InvalidAudio

    try:
        started = time.monotonic()
        text = await run_in_threadpool(speech_to_text, content, user_id=str(user["user_id"]))
        if os.getenv("STT_PROVIDER", "faster_whisper") == "deepgram":
            from app.voice.deepgram import metadata
            return {"text": text, **metadata(), "elapsed_ms": round((time.monotonic() - started) * 1000)}
        return {
            "text": text,
            "engine": "Faster-Whisper",
            "model": os.getenv("WHISPER_MODEL", "base"),
            "compute_type": os.getenv("WHISPER_COMPUTE_TYPE", "int8"),
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "beam_size": decoder_beam_size(),
        }
    except SpeechBusy as exc:
        raise HTTPException(status_code=429, detail=str(exc), headers={"Retry-After": str(exc.retry_after)}) from exc
    except InvalidAudio as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Nhận diện giọng nói chưa sẵn sàng hoặc quá thời gian xử lý. Vui lòng thử lại.") from exc


@router.post("/speak")
def speak(request: SpeakRequest, user: dict = Depends(get_current_user), voice: str | None = None) -> Response:
    return _speak_text(request.text, voice)


@router.get("/greeting")
def speak_greeting(user: dict = Depends(get_current_user), voice: str | None = None) -> Response:
    return _speak_text("Alo?", voice)


@router.get("/caller-voices")
def caller_voices(user: dict = Depends(get_current_user)) -> list[str]:
    from app.voice.synthesis import available_caller_voices

    return available_caller_voices()


@router.get("/scenarios/{scenario_key}/opening")
def speak_scenario_opening(scenario_key: str, user: dict = Depends(get_current_user)) -> Response:
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT l.line_text
               FROM scenarios s
               JOIN dialogue_nodes n ON n.scenario_version_id = s.active_version_id AND n.is_start
               JOIN dialogue_lines l ON l.node_id = n.node_id
               WHERE s.scenario_name = %s AND s.status = 'published'
                 AND l.source = 'fixed' AND l.enabled AND NOT l.is_reprompt
               ORDER BY l.line_id
               LIMIT 1""",
            (scenario_key,),
        )
        line = cursor.fetchone()
    if line is None:
        raise HTTPException(status_code=404, detail="Tình huống chưa có lời mở đầu.")
    return _speak_text(line["line_text"])


def _speak_text(text: str, voice: str | None = None) -> Response:
    from app.voice.synthesis import available_caller_voices, text_to_speech

    if voice is not None and voice not in available_caller_voices():
        raise HTTPException(status_code=404, detail="Giọng đọc này chưa được cài đặt.")

    try:
        started = time.monotonic()
        audio = text_to_speech(text, voice or "default")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Tạo giọng đọc thất bại. Kiểm tra model Piper.") from exc
    duration_ms = (time.monotonic() - started) * 1000
    return Response(content=audio, media_type="audio/wav", headers={
        "Server-Timing": f"tts;dur={duration_ms:.1f}",
        "Cache-Control": "no-store",
    })
