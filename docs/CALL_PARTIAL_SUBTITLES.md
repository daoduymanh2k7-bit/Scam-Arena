# Incremental call subtitles

Calls now show a single dashed **Chữ tạm** subtitle while the player is talking.
The draft is replaceable in full: these words are not committed, labeled as an
intent, sent to the conversation engine or used for scoring. At the end of the
utterance the same row shows **Đang chốt câu…**, then the final transcription
replaces it and the existing conversation flow runs exactly once.

## Implementation and limits

Uses the existing open-source Silero/vad-web and Faster-Whisper CPU INT8 model.
This is incremental HTTP transcription of growing utterance snapshots, not a
native streaming Whisper model or WebSocket transport. It deliberately reuses
the cookie-authenticated API and the same CPU decoder rather than introducing
a second resident model/server on the 2-core / 4 GB VPS.

- Silero supplies 16 kHz float frames, with up to 300 ms of pre-roll. The first
  snapshot needs approximately 1.2 seconds of accumulated audio including
  pre-roll; later snapshots need about 1.05 seconds of new audio. Short replies
  may finish before any preview appears. Network and inference add to the wait.
- At most one preview request per browser controller is in flight, with no
  browser backlog. The client follows the server's next_partial_ms recommendation
  (1–5 seconds measured from request start), not another full delay after receiving
  the response. HTTP 429 Retry-After is respected. At most 468 V5 frames are retained
  (<15 seconds). The existing 14-second utterance cap is unchanged.
- POST /api/voice/transcribe/partial requires the existing login. It accepts only
  mono 16 kHz PCM16 WAV, 0.5–15 seconds and at most 512 KiB; it returns is_final=false
  and uses beam 1, best-of 1, temperature 0, no previous-text conditioning.
  It never writes audio/text to the database or training datasets.
- One decoder is shared by all accounts. Authenticated user IDs, not browser-supplied
  IDs, partition the scheduler. Each account has at most one waiting draft and one
  final. At most four of each kind wait. Drafts run FIFO with a repeat-user rotation;
  final transcripts take precedence, and a final cancels its own queued draft.
  Four near-simultaneous finals wait their turn rather than being rejected just
  because another final is running. Drafts wait at most 6 seconds, finals at most
  12 seconds. Duplicates/full queues/expired tickets return 429.
- Server pacing uses an EWMA of actual preview service time times current demand
  with 25% headroom for other work,
  clamped to 1–5 seconds. It is a load hint, not a guarantee of 1-second subtitles.
  There is no longer a fixed global 2-second gate. Run the existing single Uvicorn
  worker on this VPS; these in-process queues are not a distributed scheduler.
- Abort on mute, finalization and hangup stops browser work and discards late
  results using generation counters. Browser abort cannot interrupt a decoder
  already running in a Python thread. It will finish and release the lock;
  its stale text cannot update the UI.
- Final recognition still uses beam 3 and the complete utterance, including
  the existing fallback decoder behavior. Draft words are never substituted
  for a failed final transcription.
- HTTP 429 skips just that update. An unavailable/disabled preview endpoint
  or network failure disables drafts for the rest of that microphone capture
  and displays a notice; complete-utterance recognition stays available.
- Volume-detector fallback does not emit frames for incremental drafts;
  complete-utterance recognition continues as before.

Set `STT_PARTIAL_ENABLED=false` in the private `.env`, then recreate the app to
disable server drafts. Default is true. The Deepgram provider uses
complete-utterance recognition, with an explicit unavailable draft response.
Local drafts require no SQL migration or extra container. Deepgram requires its own API key.

## Tradeoffs

Whisper is repeatedly decoding a growing prefix. Partial words can be wrong,
rewritten, or hallucinated on short/noisy input. Waiting for a final transcript
is important for negations such as “không” or “chưa”. This does not improve the
acoustic model's underlying accuracy and does not allow interrupting the caller.

Drafts require more CPU and upload bandwidth. HTTP snapshots resend earlier
audio and do not reuse encoder state. A final that arrives while a preview is
running can wait longer than final-only recognition. Under concurrency some
players may receive few or no previews. The benefit is earlier visible feedback,
not a guarantee of lower latency before the caller's response. Monitor the
existing per-turn information panel on the actual VPS before increasing the
update frequency or number of workers.

Audio is sent to the same server during speech, rather than only after silence;
recordings and transient drafts are not persisted by this implementation.

## Validation

Backend tests cover authentication, format/size/duration bounds, priority over
previews, throttling, decoder failure recovery, greedy options and the off switch.
Node tests cover growing pre-roll snapshots, mute, no request backlog, stale
response races across turns and fallback after service failure.

A headless Edge integration check with actual self-hosted Silero and synthetic
Web Audio input verified draft text appears before final upload, final text
replaces the same row, and mute prevents later submission. STT/TTS responses in
that UI check were stubbed. A separate local test used actual Faster-Whisper and
the API router with an in-process authenticated test identity: a 4.02-second
Piper utterance produced drafts from its 2-second and 4-second prefixes in
786 / 922 ms, and the final in 762 ms. Those are local synthetic smoke timings,
not real-user accuracy or production load measurements.

Run `node --test frontend/tests/*.test.cjs` and the backend pytest suite.
Rebuild using `docker compose up -d --build scam-arena`.

References: [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper),
[vad-web](https://github.com/ricky0123/vad). The
[WhisperStreaming approach](https://github.com/ufal/whisper_streaming) was reviewed
for context; its server and local-agreement code are not dependencies here.


## Optional VPS measurement

The deployment workflow accepts speech_load_test=true on a manual run. A push
commit message containing [speech-load-test] also opts in for that run only.
It runs the same synthetic WAV before and after deploying, through the resident
HTTP service with four disposable authenticated accounts. The test has 1- and
4-account phases, two utterances per account, and records draft distribution,
final success rates, elapsed times and app cgroup CPU/memory. It does not exercise
Rasa, LLM generation, Piper responses during the measured phase or internet audio
transport. Normal players can affect the measurements, and vice versa.

Reports are retained as a GitHub Actions artifact for 14 days. No cookie, password,
real audio, transcript or player identity is included. Only the exact randomly
named accounts created by that invocation are removed in finally; their auth
sessions cascade-delete. No real account is selected for the test. The setup
uses the deployed Piper voice to create one synthetic clip; the exact WAV bytes
are copied across deployments and reports include a SHA-256 to verify pairing.


Actual VPS results and limitations are recorded in
[evaluation/speech-load-vps-2026-11-23/README.md](evaluation/speech-load-vps-2026-11-23/README.md).
The selected tuning produced one visible draft for each of four concurrent
accounts per 7.66-second utterance, with 8/8 final requests successful. It does
not provide one-second visible subtitles for all four accounts on this CPU.
