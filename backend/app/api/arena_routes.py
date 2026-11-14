from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.arena import call_service
from app.schemas import (
    CallSummaryResponse,
    CallTurnRequest,
    CallTurnResponse,
    StartCallRequest,
    StartCallResponse,
    CallHistoryItem,
    CallTranscriptResponse,
    IntentCandidate,
    ApproveIntentCandidateRequest,
    IntentCandidateActionResponse,
    FlagTurnResponse,
)
from app.arena.llm_review import analyze_session_candidates

router = APIRouter(prefix="/api/arena", tags=["arena"])


@router.get("/scenarios")
def scenarios() -> list[dict[str, str]]:
    return call_service.list_scenarios()


@router.get("/scenarios/random")
def random_scenario() -> dict[str, str]:
    try:
        return call_service.random_scenario()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/calls", response_model=StartCallResponse)
def start_call(request: StartCallRequest) -> StartCallResponse:
    try:
        return call_service.start_call(request.scenario_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy kịch bản đã xuất bản.") from exc


@router.post("/calls/{session_id}/turn", response_model=CallTurnResponse)
def submit_turn(session_id: UUID, request: CallTurnRequest) -> CallTurnResponse:
    try:
        return call_service.submit_turn(session_id, request.user_text, request.elapsed_seconds)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên gọi.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/calls/{session_id}/finish", status_code=204)
def finish_call(session_id: UUID, background_tasks: BackgroundTasks) -> None:
    try:
        call_service.finish_call(session_id)
        background_tasks.add_task(analyze_session_candidates, session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên gọi.") from exc


@router.get("/calls/{session_id}/summary", response_model=CallSummaryResponse)
def call_summary(session_id: UUID) -> CallSummaryResponse:
    try:
        return call_service.get_call_summary(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên gọi.") from exc


@router.get("/history", response_model=list[CallHistoryItem])
def call_history(limit: int = 30) -> list[CallHistoryItem]:
    return call_service.list_call_history(max(1, min(limit, 100)))


@router.get("/calls/{session_id}/transcript", response_model=CallTranscriptResponse)
def call_transcript(session_id: UUID) -> CallTranscriptResponse:
    try:
        return call_service.get_call_transcript(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên gọi.") from exc


@router.post("/calls/{session_id}/turns/{turn_no}/flag", response_model=FlagTurnResponse)
def flag_turn(
    session_id: UUID, turn_no: int, background_tasks: BackgroundTasks,
) -> FlagTurnResponse:
    try:
        response = call_service.flag_turn_for_review(session_id, turn_no)
        background_tasks.add_task(analyze_session_candidates, session_id)
        return response
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy lượt chơi.") from exc


@router.get("/admin/intent-candidates", response_model=list[IntentCandidate])
def intent_candidates(status: str = "pending") -> list[IntentCandidate]:
    if status not in {"pending", "approved", "rejected"}:
        raise HTTPException(status_code=422, detail="Trạng thái không hợp lệ.")
    return call_service.list_intent_candidates(status)


@router.post("/admin/intent-candidates/{candidate_id}/approve", response_model=IntentCandidateActionResponse)
def approve_intent_candidate(
    candidate_id: int, request: ApproveIntentCandidateRequest,
) -> IntentCandidateActionResponse:
    try:
        return call_service.approve_intent_candidate(candidate_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Đề xuất không còn chờ duyệt.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/admin/intent-candidates/{candidate_id}/reject", response_model=IntentCandidateActionResponse)
def reject_intent_candidate(candidate_id: int) -> IntentCandidateActionResponse:
    try:
        return call_service.reject_intent_candidate(candidate_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Đề xuất không còn chờ duyệt.") from exc


@router.get("/tip")
def tip(mistake: str) -> dict[str, str]:
    return {"mistake": mistake, "tip": call_service.tip(mistake)}
