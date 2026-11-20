"""Admin access to the local Rasa review workspace shared with the dataset CLI."""

import os
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from app.arena.intent_detector import Intent
from app.auth import require_admin
from rasa.evaluation.dataset_workflow import WorkspaceBusy, allowed_text, collect, read_json, workspace_lock, write_json


router = APIRouter(
    prefix="/api/arena/admin/rasa-review",
    dependencies=[Depends(require_admin)],
)
Split = Literal["train", "holdout"]
ReviewIntent = Intent | Literal["skip"]
DEFAULT_WORKSPACE = Path(__file__).resolve().parents[3] / "rasa/evaluation/.local/review-workflow"


class SpeakerUpdate(BaseModel):
    split: Split | None
    expected_split: Split | None


class SampleUpdate(BaseModel):
    intent: ReviewIntent | None
    expected_intent: ReviewIntent | None


def _workspace():
    return Path(os.environ.get("RASA_REVIEW_DIR", DEFAULT_WORKSPACE))


def _read_review(workspace):
    return read_json(workspace / "review.json", {"speakers": {}, "rows": []})


@contextmanager
def _edit_workspace():
    workspace = _workspace()
    try:
        with workspace_lock(workspace):
            yield workspace
    except WorkspaceBusy as exc:
        raise HTTPException(409, "Đang có thao tác khác trên tập dữ liệu. Hãy thử lại.") from exc


@router.get("")
def review_queue(
    response: Response,
    status: Literal["pending", "reviewed", "all"] = "pending",
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
):
    response.headers["Cache-Control"] = "no-store"
    workspace = _workspace()
    review = _read_review(workspace)
    locked = read_json(workspace / "split_lock.json", {})
    rows = []
    for row in review["rows"]:
        text = allowed_text(row["text"])
        if text is not None:
            rows.append({
                "sample": row["sample"], "speaker": row["speaker"], "style": row["style"],
                "text": text, "intent": row["intent"],
            })
    counts = Counter(row["speaker"] for row in rows)
    pending = sum(row["intent"] is None for row in rows)
    matching = rows if status == "all" else [
        row for row in rows if (row["intent"] is None) == (status == "pending")
    ]
    return {
        "pending": pending,
        "reviewed": len(rows) - pending,
        "total": len(matching),
        "samples": matching[offset:offset + limit],
        "speakers": [
            {"speaker": speaker, "split": split, "locked": speaker in locked, "count": counts[speaker]}
            for speaker, split in review["speakers"].items() if counts[speaker]
        ],
    }


@router.post("/collect")
def collect_samples():
    with _edit_workspace() as workspace:
        return collect(workspace)


@router.patch("/speakers/{speaker}")
def update_speaker(speaker: str, update: SpeakerUpdate):
    with _edit_workspace() as workspace:
        review = _read_review(workspace)
        if speaker not in review["speakers"]:
            raise HTTPException(404, "Không tìm thấy nhóm tài khoản.")
        locked = read_json(workspace / "split_lock.json", {})
        if speaker in locked and update.split != locked[speaker]:
            raise HTTPException(409, "Nhóm này đã được dùng trong một đợt xuất dữ liệu.")
        if review["speakers"][speaker] != update.expected_split:
            raise HTTPException(409, "Nhóm đã thay đổi. Hãy tải lại danh sách.")
        if update.split is None and any(
            row["speaker"] == speaker and row["intent"] not in (None, "skip") for row in review["rows"]
        ):
            raise HTTPException(409, "Cần giữ nhóm cho các câu đã duyệt của tài khoản này.")
        review["speakers"][speaker] = update.split
        write_json(workspace / "review.json", review)
    return {"speaker": speaker, "split": update.split}


@router.patch("/samples/{sample}")
def update_sample(sample: str, update: SampleUpdate):
    with _edit_workspace() as workspace:
        review = _read_review(workspace)
        row = next((item for item in review["rows"] if item["sample"] == sample), None)
        if row is None or not allowed_text(row["text"]):
            raise HTTPException(404, "Không tìm thấy mẫu có thể duyệt.")
        if row["intent"] != update.expected_intent:
            raise HTTPException(409, "Nhãn đã thay đổi. Hãy tải lại danh sách.")
        if update.intent not in (None, "skip") and review["speakers"].get(row["speaker"]) is None:
            raise HTTPException(422, "Chọn nhóm huấn luyện hoặc kiểm thử cho tài khoản trước.")
        row["intent"] = update.intent
        write_json(workspace / "review.json", review)
    return {"sample": sample, "intent": update.intent}
