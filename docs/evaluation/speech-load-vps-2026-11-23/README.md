# VPS speech load checks — 2026-11-23

These reports contain synthetic HTTP speech tests, not real users or an ASR
accuracy evaluation. Each phase has two utterances per account and either one
or four concurrent accounts. The same 7.66-second generated WAV is reused;
matching SHA-256 values verify the paired audio. P95 uses nearest rank and is
only the maximum with eight final requests, not a reliable population estimate.

## Initial deployment check

Root-level JSON files come from Actions run 45144781053. The old installation
had no deployment marker and returned HTTP 405 for draft requests. It was not
running the incremental API previously committed to GitHub. Therefore these
before/after measurements compare the actual old installation with the newly
activated implementation; they do not isolate scheduler changes.

| Phase | Old final successes | Activated final successes | Old median / max-like P95 | Activated median / P95 |
| --- | --- | --- | --- | --- |
| One account | 2/2 | 2/2 | 2.283 / 2.294 s | 2.689 / 3.098 s |
| Four accounts | 8/8 | 8/8 | 5.984 / 9.455 s | 6.550 / 10.429 s |

The activated version provided draft subtitles but increased work and did not
reduce final latency on this check. It served 8 drafts for the solo phase;
four-account draft counts were [4, 1, 2, 1] across both rounds, with draft timeout
responses for some accounts. This motivated increasing the bounded draft wait
from 4 to 6 seconds and adding 25% headroom to adaptive pacing. The VPS's actual
preview decode time was about 1.3–1.8 seconds, already longer than a one-second
target before queuing.

An SSH deployment bug was also corrected: docker compose exec could consume the
remaining stdin of the bash -s deployment script. Noninteractive commands now
read from /dev/null, a POSIX regression test feeds them through bash -s, and the
workflow checks the deployed revision marker after deployment. Both image IDs
are recorded. Temporary test accounts and sessions were removed (cleanup_ok=true).

## Interpretation limits

Only speech endpoints are timed. Rasa, LLM and synthesized replies during actual
conversations, WAN upload latency, device microphones and real accents are not
measured. Container CPU/memory include other work in that container, and this
was not an isolated host. Faster visible drafts do not mean faster final
responses. The serialized CPU decoder and VPS capacity remain throughput limits.


## Paired tuning check on the running VPS

The tuned/ directory comes from Actions run 45150267021, comparing verified
revision a88e68c with 28cc03d. Both use Faster-Whisper base INT8, beam 3. Both
clients request adaptive updates with a 1.05-second minimum; the complete WAV
and hardware are the same. The changes are a 6-second draft queue deadline and
25% headroom in server pacing. They improve service distribution, not ASR accuracy.

| Metric | Before tuning | Selected configuration |
| --- | ---: | ---: |
| Solo final successes | 2/2 | 2/2 |
| Solo final median / P95 | 2.887 / 3.592 s | 3.007 / 3.148 s |
| Four-account final successes | 8/8 | 8/8 |
| Four-account final median / P95 | 6.516 / 9.914 s | 5.816 / 9.211 s |
| Visible draft counts per account across two rounds | [2, 3, 2, 1] | [2, 2, 2, 2] |
| Draft HTTP 429 responses | 2 | 0 |

Every account received one visible draft per 7.66-second utterance after tuning.
The first draft appeared 2.69–6.84 seconds after speech start under four-account
load. Solo first drafts appeared at 2.53 / 2.74 seconds; subsequent visible updates
had a median gap of 1.80 seconds. The one-second interval is a best-case request
cadence, not a one-second visible-result guarantee. Actual decoding costs on this
VPS prevent that guarantee, especially when all four accounts speak together.

The ~0.70-second median/P95 final improvement is observed on just eight requests;
it is not a universal speedup. The solo median did not improve. More drafts are
not automatically better: under load, limiting redundant decoding preserves
capacity for final results. Four simultaneous long utterances still cause several
seconds of final wait on this CPU; this change cannot remove that hardware limit.

All reports confirm cleanup_ok=true. Root and tuned report pairs have matching
audio hashes. Revision and image IDs document that the container was actually
updated. The benchmark does not persist real-user speech or create conversation
history. Temporary accounts used only the voice endpoints and were deleted after
each run, with their sessions removed by the database foreign-key cascade.
