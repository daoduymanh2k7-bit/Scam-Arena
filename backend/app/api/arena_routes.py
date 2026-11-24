from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.arena import call_service
from app.arena.conversation_memory import schedule_summary, read_memory, interval as summary_interval
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
    LinePreferenceResponse,
    RegeneratedLineResponse,
)
from app.arena.llm_review import analyze_session_candidates
from app.auth import get_current_user, require_admin

router = APIRouter(prefix="/api/arena", tags=["arena"])
logger = logging.getLogger(__name__)


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
def start_call(request: StartCallRequest, user: dict = Depends(get_current_user)) -> StartCallResponse:
    try:
        return call_service.start_call(request.scenario_key, user["user_id"], request.interaction_mode,request.practice_difficulty,request.exercise_mode)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy kịch bản đã xuất bản.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/calls/{session_id}/turn", response_model=CallTurnResponse)
def submit_turn(session_id: UUID, request: CallTurnRequest, user: dict = Depends(get_current_user)) -> CallTurnResponse:
    try:
        result = call_service.submit_turn(session_id, request.user_text, request.elapsed_seconds, user["user_id"])
        if result.ended or result.turn_no % summary_interval() == 0:
            schedule_summary(session_id, user["user_id"], force=result.ended)
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên gọi.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/calls/{session_id}/turns/{turn_no}/regenerate", response_model=RegeneratedLineResponse)
def regenerate_turn_line(session_id: UUID, turn_no: int, line_id: int | None = None,
                         user: dict = Depends(get_current_user)) -> RegeneratedLineResponse:
    try:
        result = call_service.regenerate_turn_line(session_id,turn_no,line_id,user["user_id"])
        schedule_summary(session_id, user["user_id"], force=True)
        return result
    except KeyError as exc:
        raise HTTPException(status_code=404,detail="Không tìm thấy lượt hoặc câu thoại.") from exc
    except LookupError as exc:
        raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409,detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503,detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to regenerate dialogue line for session=%s turn=%s",session_id,turn_no)
        raise HTTPException(status_code=502,detail="Không tạo được câu mới. Hãy kiểm tra cấu hình provider và thử lại.") from exc


@router.post("/calls/{session_id}/turns/{turn_no}/lines/{line_id}/like", response_model=LinePreferenceResponse)
def like_generated_line(session_id: UUID, turn_no: int, line_id: int,
                        user: dict = Depends(get_current_user)) -> LinePreferenceResponse:
    try:
        return call_service.rate_generated_line(session_id,turn_no,line_id,user["user_id"])
    except KeyError as exc:
        raise HTTPException(status_code=404,detail="Không tìm thấy câu thoại trong lượt này.") from exc


@router.post("/calls/{session_id}/finish", status_code=204)
def finish_call(session_id: UUID, background_tasks: BackgroundTasks,
                user: dict = Depends(get_current_user)) -> None:
    try:
        call_service.finish_call(session_id,user["user_id"])
        schedule_summary(session_id, user["user_id"], force=True)
        background_tasks.add_task(analyze_session_candidates, session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên gọi.") from exc


@router.get("/calls/{session_id}/summary", response_model=CallSummaryResponse)
def call_summary(session_id: UUID, user: dict = Depends(get_current_user)) -> CallSummaryResponse:
    try:
        return call_service.get_call_summary(session_id,user["user_id"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên gọi.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/calls/{session_id}/memory")
def conversation_memory(session_id: UUID, user: dict = Depends(get_current_user)):
    try:
        return read_memory(session_id, user["user_id"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên gọi.") from exc


@router.get("/history", response_model=list[CallHistoryItem])
def call_history(limit: int = 30, user: dict = Depends(get_current_user)) -> list[CallHistoryItem]:
    return call_service.list_call_history(max(1, min(limit, 100)),user["user_id"])


@router.get("/calls/{session_id}/transcript", response_model=CallTranscriptResponse)
def call_transcript(session_id: UUID, user: dict = Depends(get_current_user)) -> CallTranscriptResponse:
    try:
        return call_service.get_call_transcript(session_id,user["user_id"])
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiên gọi.") from exc


@router.post("/calls/{session_id}/turns/{turn_no}/flag", response_model=FlagTurnResponse)
def flag_turn(
    session_id: UUID, turn_no: int, background_tasks: BackgroundTasks,
    user: dict = Depends(get_current_user),
) -> FlagTurnResponse:
    try:
        response = call_service.flag_turn_for_review(session_id, turn_no, user["user_id"])
        background_tasks.add_task(analyze_session_candidates, session_id)
        return response
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Không tìm thấy lượt chơi.") from exc


@router.get("/admin/intent-candidates", response_model=list[IntentCandidate], dependencies=[Depends(require_admin)])
def intent_candidates(status: str = "pending") -> list[IntentCandidate]:
    if status not in {"pending", "approved", "rejected"}:
        raise HTTPException(status_code=422, detail="Trạng thái không hợp lệ.")
    return call_service.list_intent_candidates(status)


@router.get("/admin/scenarios/graphs", dependencies=[Depends(require_admin)])
def admin_scenario_graphs() -> list[dict]:
    """All stored scripts and their actual transition graphs; admin role only."""
    return call_service.list_admin_scenario_graphs()


@router.post("/admin/intent-candidates/{candidate_id}/approve", response_model=IntentCandidateActionResponse, dependencies=[Depends(require_admin)])
def approve_intent_candidate(
    candidate_id: int, request: ApproveIntentCandidateRequest,
) -> IntentCandidateActionResponse:
    try:
        return call_service.approve_intent_candidate(candidate_id, request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Đề xuất không còn chờ duyệt.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/admin/intent-candidates/{candidate_id}/reject", response_model=IntentCandidateActionResponse, dependencies=[Depends(require_admin)])
def reject_intent_candidate(candidate_id: int) -> IntentCandidateActionResponse:
    try:
        return call_service.reject_intent_candidate(candidate_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Đề xuất không còn chờ duyệt.") from exc


@router.get("/tip")
def tip(mistake: str) -> dict[str, str]:
    return {"mistake": mistake, "tip": call_service.tip(mistake)}
