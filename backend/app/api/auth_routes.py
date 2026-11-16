from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response

from app.auth import COOKIE_NAME, clear_auth_cookie, get_current_user, login, logout, register, set_auth_cookie
from app.schemas import AuthUserResponse, LoginRequest, RegisterRequest

router = APIRouter(prefix="/api/auth", tags=["authentication"])


@router.post("/register", response_model=AuthUserResponse, status_code=201)
def create_account(request: RegisterRequest, response: Response) -> AuthUserResponse:
    try:
        user, token = register(request.username, request.password)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    set_auth_cookie(response, token)
    return AuthUserResponse(username=user["username"], role=user["role"])


@router.post("/login", response_model=AuthUserResponse)
def sign_in(request: LoginRequest, response: Response) -> AuthUserResponse:
    try:
        user, token = login(request.username, request.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    set_auth_cookie(response, token)
    return AuthUserResponse(username=user["username"], role=user["role"])


@router.post("/logout", status_code=204)
def sign_out(response: Response, token: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> None:
    logout(token)
    clear_auth_cookie(response)


@router.get("/me", response_model=AuthUserResponse)
def me(user: dict = Depends(get_current_user)) -> AuthUserResponse:
    return AuthUserResponse(username=user["username"], role=user["role"])
