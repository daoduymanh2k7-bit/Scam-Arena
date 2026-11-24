# Deepgram setup

Create a key in <https://console.deepgram.com/>: select the project, Settings,
API Keys, Create a New API Key. Use a recognizable name such as `scam-arena-stt`.
The key needs transcription permission (`usage:write`; the Member project role
includes it). Keep the secret in server `.env`, never in JavaScript or git.

This feature must first be present in the deployed source. Setting a variable in
an older VPS image does not install the adapter. Once deployed, edit
`/opt/scam-arena/.env` on the VPS (or the repository `.env` for localhost):

```dotenv
STT_PROVIDER=deepgram
DEEPGRAM_API_KEY=YOUR_PRIVATE_KEY
DEEPGRAM_MODEL=nova-3
DEEPGRAM_LANGUAGE=vi
DEEPGRAM_TIMEOUT_SECONDS=15
DEEPGRAM_STREAMING_ENABLED=true
STT_PARTIAL_ENABLED=false
```

Change an existing variable instead of adding duplicate `STT_PROVIDER` lines.
Preserve database and all other provider keys. Do not copy `.env.example` over an
existing `.env`. Recreate with `docker compose up -d --build scam-arena` from the
repository/VPS application directory. A plain restart does not reload Compose
environment changes. Deployment validates key presence but makes no paid probe.

While signed in, open `/api/voice/stt-status`: provider should be `deepgram`,
`key_configured` true, and model `nova-3`. This checks configuration presence,
**not** whether the key is valid or funded. Speak one short sentence and check
the call subtitle's information panel: it should report Deepgram. The request
uses the account's Deepgram credit. Check actual usage/errors in Deepgram Console.
Provider failures do not silently switch to another paid model or expose keys.

Real short Vietnamese synthetic-voice checks returned empty text or missed an
initial sentence without context. The adapter therefore prepends one second and
appends 350 ms of silence after PCM normalization, preserving all original speech.
This improved those specific checks; it is not an accuracy guarantee for human
speech. Each request sends 1.35 seconds of additional audio; allow for this in
usage estimates, especially with very short sentence clips. Stored recordings and
their offsets are unchanged because padding is only added to the API request.

Calls now stream PCM16 mono 16 kHz through an authenticated same-origin WebSocket
at `/api/voice/transcribe/stream`. The API key stays on the backend. Silero emits
new audio about every 128ms, including pre-roll once. A socket opens at speech
onset, closes on misfire/mute/hangup, and is never fed audio during caller TTS.
The legacy capture path (if Silero fails) uses REST.

Deepgram interim text updates the subtitle only. Silero's 400ms trailing-silence
decision closes the turn; provider endpointing is disabled to avoid competing
turn boundaries. `CloseStream` flushes all final segments and Metadata confirms
completion. Only the concatenated final text enters Rasa/LLM; partial text does
not alter conversation state. The 14-second local capture cap remains.

The relay preserves the REST onset/trailing padding (1.35 seconds sent per
utterance, potentially billable), without sleeping for that duration. Limits:
25-second relay lifetime, 30 seconds PCM, 6 seconds finalization wait, 5 seconds
upstream connect timeout, one active request/account, four total. No upstream
errors, audio, or text are logged by the relay. Socket errors or empty final text
retry the full locally buffered utterance through REST and mark `REST dự phòng`
in the subtitle. Such retries can bill the same audio again. A failed stream
disables streaming for the remainder of that call. Refresh/start another call
to retry. No automatic retry of the conversation turn occurs.

Set `DEEPGRAM_STREAMING_ENABLED=false` and recreate the container to compare
REST versus streaming. Subtitle latency measures the wait AFTER local VAD ends;
upstream streaming processing already overlaps speech, so it must not be
interpreted as total provider processing time. Benchmark on the same sentences,
count transcription errors as well as median/p95 end-of-speech-to-playback.
No specific latency reduction or human accuracy is guaranteed.

Local smoke check on 2026-11-24: three Piper-generated Vietnamese clips were
sent in 128ms PCM chunks at real-time cadence, followed by a serial REST request
with the same audio. Both paths preserved the words in all three samples
(punctuation differed). Post-VAD wait, excluding the shared 400ms silence window:

| Synthetic sentence | Streaming | REST |
| --- | ---: | ---: |
| Tôi chưa đồng ý chuyển tiền. | 626ms | 2089ms |
| Không, tôi không đọc mã cho anh đâu. | 497ms | 3226ms |
| Tôi sẽ tự gọi tổng đài để kiểm tra lại. | 580ms | 2308ms |

These are three single-user smoke checks, not a controlled human-microphone
benchmark. Socket readiness preceded audio in this check; in the UI the socket
handshake overlaps the beginning of speech. LLM/TTS latency is excluded.

Messages and REST fallback still use `POST https://api.deepgram.com/v1/listen`
with bounded normalized WAV clips. Growing REST snapshots remain disabled to
avoid repeatedly billing the same prefixes. Cloudflare Tunnel supports the
same-origin WebSocket path without a separate public port.

At most four cloud requests run concurrently, with at most one per account.
Cloud calls use these slots without a CPU model lock. No local ASR model is warmed up while
Deepgram is selected. To return to local ASR, set `STT_PROVIDER=faster_whisper`,
restore `STT_PARTIAL_ENABLED=true` if desired, and recreate the container.

## Retired features

Personal-voice collection pages, routes, background caption helpers and their
frontend storage code have been removed. Existing `voice_samples` and
`voice_recordings` database tables are left untouched; no stored recordings are
deleted. Browser-local unsynced recordings, if any, are also not cleared by this
change. There is no user-visible training step before using Deepgram. The C++
sidecar and its build configuration are removed. Faster-Whisper and its cache stay
available as a manually selected local fallback; no silent provider switch occurs.
