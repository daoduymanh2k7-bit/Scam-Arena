from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import arena_routes, voice_routes

ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = ROOT / "frontend" / "static"

app = FastAPI(title="Scam Arena", version="0.1.0")
app.include_router(arena_routes.router)
app.include_router(voice_routes.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
