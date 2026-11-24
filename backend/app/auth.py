"""Cookie-backed account authentication for the shared Scam Arena database."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from fastapi import Cookie, Depends, HTTPException, Response, status
from psycopg.errors import UniqueViolation

from app.database import get_connection_pool

COOKIE_NAME = "scam_arena_session"
SESSION_DAYS = 14
PBKDF2_ROUNDS = 310_000


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, rounds, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_session(cursor, user_id: str) -> str:
    token = secrets.token_urlsafe(48)
    cursor.execute(
        "INSERT INTO auth_sessions(token_hash,user_id,expires_at) VALUES(%s,%s,now()+(%s * interval '1 day'))",
        (_token_hash(token), user_id, SESSION_DAYS),
    )
    return token


def set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=os.getenv("AUTH_COOKIE_SECURE", "false").strip().lower() in {"true", "1"},
        samesite="lax",
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")


def register(username: str, password: str) -> tuple[dict, str]:
    username = username.strip().lower()
    try:
        with get_connection_pool().connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO app_users(username,password_hash) VALUES(%s,%s) RETURNING user_id,username,role",
                (username, _hash_password(password)),
            )
            user = cursor.fetchone()
            token = _new_session(cursor, user["user_id"])
        return user, token
    except UniqueViolation as exc:
        raise ValueError("Tên đăng nhập này đã được sử dụng.") from exc


def login(username: str, password: str) -> tuple[dict, str]:
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT user_id,username,password_hash,role,is_locked FROM app_users WHERE username=%s FOR UPDATE",
            (username.strip().lower(),),
        )
        user = cursor.fetchone()
        if not user or not _verify_password(password, user["password_hash"]):
            raise ValueError("Tên đăng nhập hoặc mật khẩu không đúng.")
        if user['is_locked']:
            raise ValueError('Tài khoản đã bị khóa. Vui lòng liên hệ quản trị viên.')
        cursor.execute('UPDATE app_users SET last_login_at=now() WHERE user_id=%s',(user['user_id'],))
        token = _new_session(cursor, user["user_id"])
    return {"user_id": user["user_id"], "username": user["username"], "role": user["role"]}, token


def logout(token: str | None) -> None:
    if not token:
        return
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute("DELETE FROM auth_sessions WHERE token_hash=%s", (_token_hash(token),))


def get_current_user(token: str | None = Cookie(default=None, alias=COOKIE_NAME)) -> dict:
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Vui lòng đăng nhập.")
    with get_connection_pool().connection() as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT u.user_id,u.username,u.role FROM auth_sessions a
               JOIN app_users u USING(user_id)
               WHERE a.token_hash=%s AND a.expires_at>now() AND NOT u.is_locked""",
            (_token_hash(token),),
        )
        user = cursor.fetchone()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Phiên đăng nhập đã hết hạn.")
    return user


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Chức năng dành cho quản trị viên.")
    return user

