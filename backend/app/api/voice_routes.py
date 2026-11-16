from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.schemas import SpeakRequest
from app.auth import get_current_user

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
def speak(request: SpeakRequest, user: dict = Depends(get_current_user)) -> Response:
    from app.voice.synthesis import text_to_speech

    try:
        audio = text_to_speech(request.text)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Tạo giọng đọc thất bại. Kiểm tra model Piper.") from exc
    return Response(content=audio, media_type="audio/wav")
