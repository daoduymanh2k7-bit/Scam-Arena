"""Short, explicit opt-in ASR HTTP load test with disposable synthetic accounts.

Run inside the app container. It measures speech requests, not Rasa/LLM/TTS
conversation response latency. All temporary accounts are deleted in finally.
"""
import argparse
import asyncio
from contextlib import suppress
import hashlib
from http.cookies import SimpleCookie
import io
import json
import math
import os
from pathlib import Path
import secrets
import statistics
import time
import wave
import urllib.error
import urllib.parse
import urllib.request

import psycopg
import av


class Reply:
    def __init__(self, status, content, headers):
        self.status_code, self.content, self.headers = status, content, headers
        cookie = SimpleCookie(); cookie.load(headers.get("Set-Cookie", ""))
        self.cookies = {key: value.value for key, value in cookie.items()}

    def json(self):
        return json.loads(self.content)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"Benchmark setup HTTP status {self.status_code}")


class Client:
    def __init__(self, base_url):
        self.base_url = base_url
        self.headers = {}

    def _request(self, method, path, json_body=None, params=None, files=None):
        headers = dict(self.headers); data = None
        if json_body is not None:
            data = json.dumps(json_body).encode(); headers["Content-Type"] = "application/json"
        if files:
            boundary = "bench-" + secrets.token_hex(12)
            name, content, mime = files["audio"]
            data = (f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="{name}"\r\n'
                    f'Content-Type: {mime}\r\n\r\n').encode() + content + f'\r\n--{boundary}--\r\n'.encode()
            headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
        url = self.base_url + path + ("?" + urllib.parse.urlencode(params) if params else "")
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                return Reply(response.status, response.read(), response.headers)
        except urllib.error.HTTPError as error:
            return Reply(error.code, error.read(), error.headers)

    async def post(self, path, *, json=None, params=None, files=None):
        return await asyncio.to_thread(self._request, "POST", path, json, params, files)

    async def get(self, path):
        return await asyncio.to_thread(self._request, "GET", path)

    async def aclose(self):
        pass


def prefix(pcm, seconds):
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(16000)
        wav.writeframes(pcm[:int(seconds * 16000) * 2])
    return output.getvalue()


def normalize(audio):
    """Independent of app package version so the old deployed image can be measured."""
    pcm = bytearray()
    resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
    with av.open(io.BytesIO(audio)) as source:
        for frame in source.decode(audio=0):
            for converted in resampler.resample(frame):
                pcm.extend(converted.to_ndarray().tobytes())
        for converted in resampler.resample(None):
            pcm.extend(converted.to_ndarray().tobytes())
    return prefix(pcm, len(pcm) / 32000)


def cgroup(name):
    try:
        return Path("/sys/fs/cgroup", name).read_text()
    except OSError:
        return ""


def cpu_usage():
    for line in cgroup("cpu.stat").splitlines():
        if line.startswith("usage_usec "):
            return int(line.split()[1]) / 1e6
    return None


async def run(args):
    created, clients, rows, phases = [], [], [], []
    cleanup_ok = False
    try:
        for attempt in range(30):
            try:
                health = await Client(args.base_url).get("/health")
                health.raise_for_status()
                break
            except (OSError, urllib.error.URLError, RuntimeError):
                if attempt == 29:
                    raise RuntimeError("Speech service did not become ready") from None
                await asyncio.sleep(1)
        for index in range(4):
            client = Client(args.base_url)
            clients.append(client)
            username = "bench_" + secrets.token_hex(6) + f"_{index}"
            response = await client.post("/api/auth/register", json={"username": username, "password": secrets.token_urlsafe(24)})
            response.raise_for_status()
            created.append(username)
            # The production cookie may be Secure; the test uses loopback HTTP.
            token = response.cookies.get("scam_arena_session")
            if not token:
                raise RuntimeError("Test session unavailable")
            client.headers["Cookie"] = "scam_arena_session=" + token
        if not args.audio.exists():
            voices = (await clients[0].get("/api/voice/caller-voices")).json()
            query = {"voice": "quang-huy"} if "quang-huy" in voices else {}
            response = await clients[0].post("/api/voice/speak", params=query,
                json={"text": "Tôi không đồng ý chuyển tiền vì tôi muốn tự gọi tổng đài để xác minh thông tin trước, bạn hãy cho tôi biết tên đơn vị và số điện thoại liên hệ chính thức để tôi kiểm tra lại."})
            response.raise_for_status()
            args.audio.write_bytes(normalize(response.content))
        audio = args.audio.read_bytes()
        with wave.open(io.BytesIO(audio)) as wav:
            assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (16000, 1, 2)
            pcm = wav.readframes(wav.getnframes())
        duration = len(pcm) / 32000
        if not 2 <= duration <= 12:
            raise RuntimeError("Test clip must be 2–12 seconds")
        # Warm the resident HTTP decoder; no duplicate benchmark model is loaded.
        warm = await clients[0].post("/api/voice/transcribe", files={"audio": ("warm.wav", audio, "audio/wav")})
        warm.raise_for_status()
        decoder = {key: warm.json().get(key) for key in ("engine", "model", "compute_type", "beam_size")}

        async def utterance(index, users, round_no, started):
            client = clients[index]
            async def drafts():
                due = started + 1.2
                while due < started + duration:
                    await asyncio.sleep(max(0, due - time.monotonic()))
                    sent = time.monotonic()
                    if sent >= started + duration:
                        return
                    data = prefix(pcm, min(duration, sent - started))
                    try:
                        response = await client.post("/api/voice/transcribe/partial", files={"audio": ("draft.wav", data, "audio/wav")})
                        elapsed = time.monotonic() - sent
                        rows.append(dict(users=users, round=round_no, user=index, kind="draft", status=response.status_code,
                                         elapsed_s=round(elapsed, 4), appeared_s=round(time.monotonic() - started, 4)))
                        delay = args.cadence
                        if args.adaptive:
                            if response.status_code == 200:
                                delay = max(1, min(5, response.json().get("next_partial_ms", 1000) / 1000))
                            elif response.status_code == 429:
                                due = time.monotonic() + max(1, min(5, float(response.headers.get("Retry-After", 1))))
                                continue
                        due = sent + delay
                    except (OSError, urllib.error.URLError):
                        rows.append(dict(users=users, round=round_no, user=index, kind="draft", status=0))
                        due = time.monotonic() + args.cadence
            pending = asyncio.create_task(drafts())
            await asyncio.sleep(max(0, started + duration + .4 - time.monotonic()))
            pending.cancel()
            with suppress(asyncio.CancelledError):
                await pending
            sent = time.monotonic()
            try:
                response = await client.post("/api/voice/transcribe", files={"audio": ("final.wav", audio, "audio/wav")})
                rows.append(dict(users=users, round=round_no, user=index, kind="final", status=response.status_code,
                                 elapsed_s=round(time.monotonic() - sent, 4)))
            except (OSError, urllib.error.URLError):
                rows.append(dict(users=users, round=round_no, user=index, kind="final", status=0))

        for users in (1, 4):
            started = time.monotonic(); cpu_before = cpu_usage(); memory = []; stop = asyncio.Event()
            async def sample():
                while not stop.is_set():
                    value = cgroup("memory.current").strip()
                    if value.isdigit(): memory.append(int(value))
                    try: await asyncio.wait_for(stop.wait(), timeout=.25)
                    except asyncio.TimeoutError: pass
            sampler = asyncio.create_task(sample())
            try:
                for round_no in range(args.rounds):
                    barrier = time.monotonic() + .1
                    await asyncio.gather(*(utterance(i, users, round_no, barrier) for i in range(users)))
                    await asyncio.sleep(1)
            finally:
                stop.set(); await sampler
            wall = time.monotonic() - started; cpu_after = cpu_usage()
            finals = [row for row in rows if row["users"] == users and row["kind"] == "final"]
            times = sorted(row["elapsed_s"] for row in finals if row["status"] == 200)
            phases.append(dict(users=users, finals_ok=sum(row["status"] == 200 for row in finals), finals_total=len(finals),
                               final_median_s=statistics.median(times) if times else None,
                               final_p95_s=times[max(0, math.ceil(.95 * len(times)) - 1)] if times else None,
                               drafts_per_user=[sum(row["status"] == 200 and row["kind"] == "draft" and row["users"] == users and row["user"] == i for row in rows) for i in range(users)],
                               cpu_cores_used=(cpu_after - cpu_before) / wall if cpu_before is not None and cpu_after is not None else None,
                               peak_app_memory_mb=max(memory) / 1048576 if memory else None))
    finally:
        for client in clients:
            await client.aclose()
        if created:
            # Exact random names created by this invocation; never delete by prefix.
            with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
                result = connection.execute("DELETE FROM app_users WHERE username = ANY(%s)", (created,))
                cleanup_ok = result.rowcount == len(created)
        else:
            cleanup_ok = True
    report = dict(label=args.label, rounds=args.rounds, adaptive=args.adaptive, cadence_s=args.cadence,
                  decoder=decoder,
                  audio_sha256=hashlib.sha256(audio).hexdigest(), audio_duration_s=duration,
                  phases=phases, rows=rows, cleanup_ok=cleanup_ok)
    print(json.dumps(report, ensure_ascii=False), flush=True)
    if not cleanup_ok:
        raise RuntimeError("Test account cleanup incomplete")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--label", required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--cadence", type=float, default=1.05)
    parser.add_argument("--adaptive", action="store_true")
    parser.add_argument("--rounds", type=int, default=2, choices=(1, 2, 3))
    asyncio.run(run(parser.parse_args()))
