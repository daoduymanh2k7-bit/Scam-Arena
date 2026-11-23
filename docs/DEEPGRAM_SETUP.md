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

This initial adapter uses `POST https://api.deepgram.com/v1/listen` for bounded
WAV clips, not a continuous WebSocket stream. It supports completed turns in ordinary voice calls. Growing call snapshots are
disabled, even if `STT_PARTIAL_ENABLED=true`, to avoid repeated transcription and
billing of the same audio. Real WebSocket interim captions require a separate
streaming integration. The final endpoint validates/resamples audio first.

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
