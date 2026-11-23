from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import arena_routes, auth_routes, rasa_review_routes, voice_routes, voice_samples_routes
from app.database import close_database, initialize_database
from app.scenario_visualizer import generate_scenario_map

ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = ROOT / "frontend" / "static"


async def _warm_speech() -> None:
    from app.voice.transcription import warmup_speech

    try:
        await asyncio.to_thread(warmup_speech)
    except Exception:
        logging.getLogger(__name__).exception("Speech model preload failed; a later request may retry")


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    generate_scenario_map()
    warmup = asyncio.create_task(_warm_speech())
    try:
        yield
    finally:
        from app.arena.conversation_memory import stop_worker
        await asyncio.to_thread(stop_worker)
        warmup.cancel()
        with suppress(asyncio.CancelledError):
            await warmup
        close_database()


app = FastAPI(title="Scam Arena", version="0.1.0", lifespan=lifespan)
app.include_router(arena_routes.router)
app.include_router(auth_routes.router)
app.include_router(rasa_review_routes.router)
app.include_router(voice_routes.router)
app.include_router(voice_samples_routes.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
