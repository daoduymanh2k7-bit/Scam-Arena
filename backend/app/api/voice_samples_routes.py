"""Opt-in, owner-only ASR dataset collection; no model training is performed."""
import io
import wave
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app.auth import get_current_user
from app.database import get_connection_pool

router = APIRouter(prefix="/api/voice/samples", tags=["voice samples"])
FIELDS = "sample_id,kind,prompt_text,machine_text,transcript,status,revision,duration_ms,created_at,updated_at"
MAX_SAMPLES = 200
PROMPTS = [
    "Tôi chưa đồng ý chuyển tiền.", "Tôi không cung cấp mã xác nhận cho người lạ.",
    "Để tôi tự gọi tổng đài chính thức kiểm tra lại.", "Tôi có nhận được tin nhắn, nhưng chưa mở ra.",
    "Dạ, tôi đang nghe. Anh chị nói lại giúp tôi được không?",
    "Lúc nãy tôi đồng ý, nhưng bây giờ tôi muốn dừng lại.",
    "Tôi chưa hiểu vì sao mình phải làm việc này.", "Tôi sẽ hỏi người nhà trước khi quyết định.",
    "Tôi không thực hiện giao dịch mà anh chị vừa nói.", "Cảm ơn, tôi muốn kết thúc cuộc gọi ở đây.",
]


def validate_wav(audio: bytes) -> int:
    try:
        with wave.open(io.BytesIO(audio), "rb") as wav:
            frames = wav.getnframes()
            if ((wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) != (16000, 1, 2)
                    or not 16000 <= frames <= 240000 or len(wav.readframes(frames)) != frames * 2):
                raise ValueError()
            return round(frames / 16)
    except (wave.Error, EOFError, ValueError) as exc:
        raise HTTPException(400, "Mẫu cần âm thanh rõ, dài từ 1 đến 15 giây.") from exc


def owned(cursor, sample_id, user_id, *, audio=False):
    cursor.execute(f"SELECT {FIELDS}{',audio' if audio else ''} FROM voice_samples WHERE sample_id=%s AND user_id=%s",
                   (sample_id, user_id))
    row = cursor.fetchone()
    if not row:
        raise HTTPException(404, "Không tìm thấy mẫu giọng.")
    return row


@router.get("")
def list_samples(response: Response, user=Depends(get_current_user)):
    response.headers["Cache-Control"] = "no-store"
    with get_connection_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {FIELDS} FROM voice_samples WHERE user_id=%s ORDER BY created_at DESC LIMIT %s",
                    (user["user_id"], MAX_SAMPLES))
        rows = cur.fetchall()
    return {"items": rows, "max_samples": MAX_SAMPLES, "prompts": PROMPTS,
            "model_status": "shared", "training_enabled": False}


def store_sample(content, kind, prompt_text, user_id):
    from app.voice.whisper_cpp import normalize_audio, InvalidAudio
    try:
        audio = normalize_audio(content)
    except InvalidAudio as exc:
        raise HTTPException(400, str(exc)) from exc
    duration = validate_wav(audio)
    if len(audio) > 480044:
        raise HTTPException(413, "Mẫu quá lớn.")
    with get_connection_pool().connection() as conn, conn.cursor() as cur:
        # Serialize quota checks across simultaneous uploads from one account.
        cur.execute("SELECT user_id FROM app_users WHERE user_id=%s FOR UPDATE", (user_id,))
        if not cur.fetchone():
            raise HTTPException(401, "Tài khoản không còn tồn tại.")
        cur.execute("SELECT count(*) AS count FROM voice_samples WHERE user_id=%s", (user_id,))
        if cur.fetchone()["count"] >= MAX_SAMPLES:
            raise HTTPException(409, "Đã đủ 200 mẫu. Hãy xóa mẫu không dùng trước khi lưu thêm.")
        cur.execute(f"""INSERT INTO voice_samples(user_id,audio,duration_ms,kind,prompt_text)
                        VALUES(%s,%s,%s,%s,%s) RETURNING {FIELDS}""",
                    (user_id, audio, duration, kind, prompt_text))
        return cur.fetchone()


@router.post("", status_code=201)
async def upload_sample(audio: UploadFile = File(...), consent: bool = Form(...),
                        kind: str = Form(...), prompt_text: str = Form(""), user=Depends(get_current_user)):
    try:
        if not consent:
            raise HTTPException(400, "Cần đồng ý lưu giọng để tạo bộ dữ liệu cá nhân.")
        if kind not in {"read", "natural"} or len(prompt_text) > 1000:
            raise HTTPException(400, "Loại mẫu hoặc câu gợi ý không hợp lệ.")
        content = await audio.read(2 * 1024 * 1024 + 1)
        if not content or len(content) > 2 * 1024 * 1024:
            raise HTTPException(413, "Mỗi tệp cần từ 1 byte đến 2 MB.")
    finally:
        await audio.close()
    return await run_in_threadpool(store_sample, content, kind, prompt_text, user["user_id"])


class SampleEdit(BaseModel):
    transcript: str = Field(max_length=2000)
    status: str = Field(pattern="^(pending|confirmed|rejected)$")
    revision: int = Field(ge=1)


@router.patch("/{sample_id}")
def edit_sample(sample_id: UUID, edit: SampleEdit, user=Depends(get_current_user)):
    text = edit.transcript.strip()
    if edit.status == "confirmed" and not text:
        raise HTTPException(400, "Hãy nghe lại và nhập bản chép đúng trước khi xác nhận.")
    with get_connection_pool().connection() as conn, conn.cursor() as cur:
        owned(cur, sample_id, user["user_id"])
        cur.execute(f"""UPDATE voice_samples SET transcript=%s,status=%s,revision=revision+1,updated_at=now()
                        WHERE sample_id=%s AND user_id=%s AND revision=%s RETURNING {FIELDS}""",
                    (text, edit.status, sample_id, user["user_id"], edit.revision))
        row = cur.fetchone()
        if not row:
            raise HTTPException(409, "Mẫu đã thay đổi. Hãy tải lại danh sách.")
        return row


@router.get("/{sample_id}/audio")
def sample_audio(sample_id: UUID, user=Depends(get_current_user)):
    with get_connection_pool().connection() as conn, conn.cursor() as cur:
        row = owned(cur, sample_id, user["user_id"], audio=True)
    return Response(bytes(row["audio"]), media_type="audio/wav", headers={"Cache-Control": "no-store"})


@router.post("/{sample_id}/transcribe")
def sample_transcribe(sample_id: UUID, user=Depends(get_current_user)):
    from app.voice.transcription import transcribe_sample, SpeechBusy
    with get_connection_pool().connection() as conn, conn.cursor() as cur:
        row = owned(cur, sample_id, user["user_id"], audio=True)
    if row["status"] != "pending":
        raise HTTPException(409, "Chỉ nhận diện thử mẫu đang chờ xác nhận.")
    try:
        text = transcribe_sample(bytes(row["audio"]), user_id=user["user_id"])
    except SpeechBusy as exc:
        raise HTTPException(429, str(exc), headers={"Retry-After": str(exc.retry_after)}) from exc
    except Exception as exc:
        raise HTTPException(503, "Nhận diện mẫu chưa sẵn sàng. Mẫu đã lưu; bạn vẫn có thể tự chép.") from exc
    with get_connection_pool().connection() as conn, conn.cursor() as cur:
        cur.execute(f"""UPDATE voice_samples SET machine_text=%s,revision=revision+1,updated_at=now()
                        WHERE sample_id=%s AND user_id=%s AND revision=%s RETURNING {FIELDS}""",
                    (text[:2000], sample_id, user["user_id"], row["revision"]))
        result = cur.fetchone()
        if not result:
            raise HTTPException(409, "Mẫu đã sửa hoặc xóa trong lúc nhận diện. Hãy tải lại danh sách.")
        return result


@router.delete("/{sample_id}", status_code=204)
def delete_sample(sample_id: UUID, user=Depends(get_current_user)):
    with get_connection_pool().connection() as conn, conn.cursor() as cur:
        owned(cur, sample_id, user["user_id"])
        cur.execute("DELETE FROM voice_samples WHERE sample_id=%s AND user_id=%s", (sample_id, user["user_id"]))
