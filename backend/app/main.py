from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import arena_routes, voice_routes
from app.database import close_database, initialize_database
from app.scenario_visualizer import generate_scenario_map

ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = ROOT / "frontend" / "static"

@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    generate_scenario_map()
    try:
        yield
    finally:
        close_database()


app = FastAPI(title="Scam Arena", version="0.1.0", lifespan=lifespan)
app.include_router(arena_routes.router)
app.include_router(voice_routes.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
