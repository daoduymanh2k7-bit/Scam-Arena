from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.schemas import SpeakRequest
from app.auth import get_current_user
from app.database import get_connection_pool

router = APIRouter(prefix="/api/voice", tags=["voice"])
MAX_AUDIO_BYTES = 15 * 1024 * 1024


@router.post("/transcribe")
async def transcribe(audio: UploadFile = File(...), user: dict = Depends(get_current_user)) -> dict[str, str]:
    content = await audio.read(MAX_AUDIO_BYTES + 1)
    await audio.close()
    if not content:
        raise HTTPException(status_code=400, detail="Tệp âm thanh rỗng.")
    if len(content) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Tệp âm thanh vượt giới hạn 15 MB.")

    from app.voice.transcription import speech_to_text

    try:
        return {"text": speech_to_text(content)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Nhận diện giọng nói thất bại. Kiểm tra model Faster-Whisper.") from exc


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
               JOIN dialogue_nodes n ON n.scenario_id = s.scenario_id AND n.is_start
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
        audio = text_to_speech(text, voice or "default")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Tạo giọng đọc thất bại. Kiểm tra model Piper.") from exc
    return Response(content=audio, media_type="audio/wav")
