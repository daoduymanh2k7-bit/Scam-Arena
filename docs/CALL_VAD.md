# Call speech detection

Calls use [vad-web](https://github.com/ricky0123/vad) 0.0.31 with Silero VAD v5
and ONNX Runtime Web 1.22.0. Faster-Whisper base/CPU INT8 still transcribes the
result on the server. VAD detects speech boundaries; it does not correct words
or classify intent. No database migration or API key change is needed.

The Docker build downloads explicitly selected npm assets and verifies their
SHA-512 package integrity. JavaScript, model, worklet and WASM are served from
the website's versioned `/vendor/vad/` path, without a runtime CDN dependency.
Notices are under `/vendor-notices/` and the VAD bundle license accompanies the
bundle. Assets are cached by the build; they are not committed as binary files.

On entering call mode, preload warms the browser cache without requesting the
microphone. Answering requests permission and initializes the detector before
playing the opening greeting. Capture only runs during the player's turn.
Mute, upload, caller speech and hangup close the capture gate immediately.
An inference queue and turn counter discard late results. Hangup stops tracks
immediately, then releases the ONNX session and AudioContext. A failed model
initialization falls back to the previous volume detector with a visible
notice. Runtime inference failure offers the existing retry microphone button.
Subtitle information includes the detector alongside the transcription engine.

Current settings: 16 kHz mono; positive/negative probability 0.50/0.35; 300 ms
pre-roll; 400 ms trailing silence (previously 550 ms); minimum 96 ms speech to allow short replies;
14-second continuous speech cap. The cap submits the segment and waits for the
server reply. This is turn-taking, not simultaneous interruption of the caller.
An intentional pause longer than the threshold can end a sentence early.

## Validation

Run lifecycle tests with `node --test frontend/tests/call-microphone.test.cjs`.
CI runs them alongside backend tests. They cover duplicate submission, delayed
inference after mute, enable during initialization, hangup during permission,
explicit fallback and long-speech flushing.

A local headless Edge smoke check used actual ONNX/WASM inference and a Piper
Vietnamese sample fed through Web Audio: two enabled turns produced two 16 kHz
segments, playback while disabled produced none, no fallback/error occurred,
and hangup ended the stream and closed the context. This verifies integration,
not human-speech accuracy. Browser autoplay, permissions, device speed, noise,
accents and short utterances still require real-device testing. First load
downloads the model and WASM; subsequent calls reuse the browser cache.

Rebuild after changes: `docker compose up -d --build scam-arena`.
For deployment, push main and check both jobs in Test and deploy VPS. Refresh
the browser after deployment so the new controller script is loaded.


## Latency inspection (2026-11-23)

Open the information icon on the player's subtitle after the caller starts
replying. One information panel contains detector/decoder details, intent/source
information, and per-turn timings. Measurements remain in the browser tab.

- Endpoint wait: wall time between the last Silero speech-positive frame callback
  and segment submission. This is an estimate, not a measurement of the physical
  end of speech; model decisions and frame scheduling affect it.
- WAV packing; STT HTTP round trip; server STT processing/thread-pool time.
- Remaining HTTP time = STT round trip minus reported server duration, clamped to
  zero. Includes upload, download, HTTP parsing and scheduling, not just network.
- Conversation processing: full call start/turn request; includes intent and
  reply selection/generation. The existing line latency is only a subset.
- TTS round trip including download, plus Piper server duration via Server-Timing.
- Playback buffering until the first `playing` event. Total stops there and
  excludes the duration of the caller's reply. A muted speaker can still play
  media; this is browser playback readiness, not proof of audible output.
- Fallback VAD cannot measure endpoint wait; it explicitly shows unavailable and
  totals only from segment completion. Failed/cancelled audio has no completed
  playback total.

The new default beam is 3. Set WHISPER_BEAM_SIZE=5 in .env and recreate the app
container to restore the previous setting; 1 is available for experiments.
See [the paired decoder comparison](SPEECH_LATENCY_COMPARISON.md). No database
migration, new account or additional paid API is required.
