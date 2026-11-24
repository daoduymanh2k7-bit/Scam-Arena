"""Bounded, authenticated PCM relay. Drafts never enter conversation state."""
import asyncio
import json
import os
import time
from urllib.parse import urlencode

from websockets.asyncio.client import connect

from app.voice.deepgram import metadata, slot


def enabled():
    return (os.getenv("STT_PROVIDER", "faster_whisper") == "deepgram"
            and os.getenv("DEEPGRAM_STREAMING_ENABLED", "true").lower() in {"true", "1"}
            and bool(os.getenv("DEEPGRAM_API_KEY", "").strip()))


class Transcript:
    def __init__(self):
        self.parts = {}

    def update(self, event):
        text = event["channel"]["alternatives"][0]["transcript"]
        if not isinstance(text, str) or len(text) > 10000:
            raise ValueError("Invalid transcript")
        if event.get("is_final") and text.strip():
            self.parts[float(event["start"])] = text.strip()
        complete = " ".join(self.parts[k] for k in sorted(self.parts))
        return complete if event.get("is_final") else " ".join(filter(None, [complete, text.strip()]))

    def final(self):
        return " ".join(self.parts[k] for k in sorted(self.parts))


async def relay(browser, user_id):
    query = urlencode({"model": metadata()["model"], "language": os.getenv("DEEPGRAM_LANGUAGE", "vi"),
                       "encoding": "linear16", "sample_rate": 16000, "channels": 1,
                       "interim_results": "true", "endpointing": "false", "punctuate": "true",
                       "smart_format": "false"})
    transcript = Transcript()
    finished = asyncio.Event()
    closed = asyncio.Event()
    finish_at = None
    total_bytes = 0
    with slot(user_id):
        async with connect("wss://api.deepgram.com/v1/listen?" + query,
                           additional_headers={"Authorization": "Token " + os.environ["DEEPGRAM_API_KEY"].strip()},
                           open_timeout=5, close_timeout=1, max_size=256 * 1024,
                           compression=None) as upstream:
            # Preserve onset context that proved useful with the REST decoder.
            await upstream.send(b"\0" * 32000)
            await browser.send_json({"type": "ready"})

            async def upload():
                nonlocal finish_at, total_bytes
                while True:
                    message = await browser.receive()
                    if message["type"] == "websocket.disconnect":
                        raise ConnectionError("Client disconnected")
                    chunk = message.get("bytes")
                    if chunk is not None:
                        total_bytes += len(chunk)
                        if not chunk or len(chunk) > 32000 or len(chunk) % 2 or total_bytes > 30 * 32000:
                            raise ValueError("Invalid PCM bounds")
                        await upstream.send(chunk)
                    elif message.get("text") == '{"type":"finish"}':
                        if not total_bytes:
                            raise ValueError("Empty stream")
                        finish_at = time.monotonic()
                        finished.set()
                        await upstream.send(b"\0" * 11200)
                        # CloseStream flushes ALL remaining results, then sends Metadata.
                        # Unlike Finalize, completion does not depend on an optional flag.
                        await upstream.send(json.dumps({"type": "CloseStream"}))
                        await closed.wait()
                        return
                    else:
                        raise ValueError("Invalid stream control")

            async def receive():
                async for raw in upstream:
                    event = json.loads(raw)
                    if event.get("type") == "Results":
                        draft = transcript.update(event)
                        await browser.send_json({"type": "draft", "text": draft})
                    elif event.get("type") == "Error":
                        raise RuntimeError("Upstream speech error")
                    elif event.get("type") == "Metadata" and finished.is_set():
                        await browser.send_json({"type": "final", "text": transcript.final(), **metadata(),
                                                 "transport": "websocket",
                                                 "elapsed_ms": round((time.monotonic() - finish_at) * 1000)})
                        closed.set()
                        return
                raise ConnectionError("Stream closed without completion")

            async def deadline():
                await finished.wait()
                await asyncio.sleep(6)
                raise TimeoutError("Stream finalization timeout")

            tasks = [asyncio.create_task(fn()) for fn in (upload, receive, deadline)]
            try:
                done, _ = await asyncio.wait(tasks, timeout=25, return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    raise TimeoutError("Stream duration exceeded")
                for task in done:
                    task.result()
                if not closed.is_set():
                    raise ConnectionError("Incomplete stream")
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
