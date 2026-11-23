# Speech latency comparison — 2026-11-23

Selected default: Faster-Whisper multilingual base, CPU INT8, two threads,
**beam size 3**. This builds on the existing open-source Faster-Whisper and
Silero/vad-web integrations. A streaming service was not required for this change.

## Paired local measurement

12 distinct Vietnamese phrases, rotating three Piper presets; exactly the same
audio bytes used for all decoders. Two passes per phrase, rotated beam order,
one warmup per beam, model loading and TTS excluded. Each timed decode includes
the same production normalization and temporary WAV handling. All options except
beam size stay unchanged, including the library's temperature fallback behavior.
Run on local Docker, not the 2-core VPS. No other benchmarking job ran concurrently.

| Beam | Runs | Median decode | Maximum | Token edits / reference tokens |
| --- | ---: | ---: | ---: | ---: |
| 5 (previous) | 24 | 826 ms | 963 ms | 48 / 206 (23.3%) |
| 3 (selected) | 24 | 786 ms | 951 ms | 46 / 206 (22.3%) |
| 1 | 24 | 753 ms | 858 ms | 46 / 206 (22.3%) |

Beam 3 saves about 40 ms (4.9%) at the median on this small sample. Beam 1
was another 33 ms faster but misheard “hướng dẫn” in a sentence beam 3 got right;
its lower error count elsewhere cancels that regression in the aggregate.
Beam 3 is the conservative compromise, not a claim of universal superiority.
The audio dataset already exposes substantial errors, including “chưa” becoming
“chơi”, across all three beams. Faster decoding does not solve those errors.

Raw references, predictions and each timing are in
[evaluation/speech-beams-2026-11-23.json](evaluation/speech-beams-2026-11-23.json).
The repeated runs are not independent speakers. Synthetic voices, few phrases
and local hardware cannot establish real-user accuracy or production latency.
Do not use this dataset for training or claim it is an objective held-out test.

The browser endpoint threshold changes from 550 to 400 ms, saving 150 ms of
configured trailing silence. V5 uses 32 ms frames and confidence thresholds, so
actual observed waits need not equal 400 ms. Hesitations longer than this may
split a thought. Pre-roll stays 300 ms to preserve the start of short replies.
Neither the decoder saving nor the endpoint saving is a guarantee of the total
time until the caller's audio starts.

## Reproduce / use consented real recordings

Run away from live traffic:

```bash
docker compose exec -T scam-arena python -m tools.compare_speech_beams --output /tmp/beams.json
docker cp scam-arena:/tmp/beams.json ./beams.json
```

For a real recording set, create a JSON array containing `audio` (path relative
to manifest), `text` (reviewed reference) and `speaker` (pseudonymous ID). Mount
the manifest/audio read-only into a test container and supply `--manifest`.
Report results separately for each speaker and important negations; do not tune
on the final test set. Real transcript output can be personal data: keep those
reports private unless publication was explicitly consented to.

## Validation

Backend tests check decoder selection and TTS timing headers. Node tests check
turn gating, mute/hangup races, current-turn VAD timing, and that total latency
stops at playback start rather than the end of the reply. A headless Edge check
uses actual self-hosted Silero inference with synthetic Web Audio input and
stubbed conversation/STT/TTS APIs to verify the subtitle timing pipeline without
creating user accounts or uploading a user's real microphone audio.

See [CALL_VAD.md](CALL_VAD.md) for the meaning and limits of each displayed time.
Upstream references: [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper),
[VAD endpoint algorithm](https://docs.vad.ricky0123.com/user-guide/algorithm/).
