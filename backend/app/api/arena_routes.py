from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.arena import session_service
from app.schemas import ReplyRequest, ScoreRequest, CallSession

router = APIRouter(prefix="/api/arena", tags=["arena"])


@router.get("/scenarios")
def scenarios() -> list[dict[str, str]]:
    return session_service.list_scenarios()


@router.get("/scenarios/random")
def random_scenario() -> dict[str, str]:
    return session_service.random_scenario()


@router.post("/reply")
def scammer_reply(request: ReplyRequest) -> dict[str, str]:
    try:
        return {"reply": session_service.reply(request.scenario_key, request.history, request.user_text)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy kịch bản '{request.scenario_key}'.") from exc


@router.post("/score", response_model=CallSession)
def score_session(request: ScoreRequest) -> CallSession:
    return session_service.score(request.session_id, request.scenario_type, request.transcript)


@router.get("/tip")
def tip(mistake: str) -> dict[str, str]:
    return {"mistake": mistake, "tip": session_service.tip(mistake)}
