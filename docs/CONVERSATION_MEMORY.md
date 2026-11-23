# LLM conversation memory

The trusted prompts live in `backend/app/arena/prompts.py`. All four dialogue
providers receive the same prompt, including fallback providers. Dialogue prompt
version defaults to `v3` to separate older cached replies; an explicit
`LINE_PROMPT_VERSION` environment override still takes precedence.

The prompts distinguish unverified caller claims from facts and a player's
confirmed actions from intentions, quotations and hypothetical examples. New
explicit statements take precedence over a conflicting older summary. Unclear
speech should elicit a short clarification rather than assumed agreement.
Intent classification retains `unknown` for ambiguous acknowledgements and
does not assign the two sensitive-action labels reserved for deterministic rules.
These are instructions to a fallible model, not semantic guarantees.

Each session can have an incremental LLM-written summary, capped by
`CONVERSATION_SUMMARY_MAX_WORDS` (default **150**, supported range 20–500).
Words are whitespace-separated units: Vietnamese syllables separated by spaces
count individually. This is not a token count or a linguistic word segmentation.

The summary worker runs after every four committed scenario turns by default,
and at session end. It merges the previous summary with new stored turn pairs
and the scenario opening. It uses the existing provider configuration in order:
Gemini, Groq, OpenRouter, then the mode-specific X-APIKEY fallback. Both
`LINE_LLM_ENABLED` and `CONVERSATION_SUMMARY_ENABLED` must be enabled. No new key
is required, but summarization adds provider calls and token usage.

The trusted prompt preserves refusals, negations, changed decisions, verification
attempts and unresolved questions. It distinguishes a caller's demand from an
action the player actually confirmed. Dialogue and prior summaries are untrusted
data. LLM text is still fallible; the summary does not choose nodes or calculate
scores. Those remain in the existing deterministic game flow.

## Limits and reply latency

The LLM is told the exact word limit. Application code independently validates
it. Overlong output is shortened only at a complete sentence boundary; if no
complete leading sentence fits, the new summary is rejected and the old one is
kept. Rejected output never advances coverage. The entire provider fallback chain
has a default six-second budget. Provider failures preserve the old summary.

A single dedicated worker executes at most four pending sessions, with one job
per session. A finish/regenerate event can coalesce one catch-up pass. The main
reply path never waits for the summary provider. Connections are released before
the external LLM call, and the save uses a short lock timeout. Shutdown drains
the running worker before closing the database pool.

The reply prompt combines the summary, its covered-turn marker, the latest four
turn pairs and the current player text. Unknown-intent reclassification also
receives memory alongside its latest three turns. If summary generation lags,
up to twelve older unsummarized turns bridge the gap. Very long sessions beyond
that bound can temporarily have incomplete context; summaries are lossy, not a
perfect replay of every word. No ASR draft is summarized: only committed scenario
turns participate. The preliminary phone greeting/courtesy UI is not a stored
scenario turn.

When memory or a raw older-turn gap is present, dialogue generation bypasses
shared exact/pool caches. Memory-specific replies stay in that session's
`call_turns`, not the shared `dialogue_lines` pool. Their `line_id` can be null,
including regeneration; existing UI only offers shared-line likes for a real ID.
If contextual generation fails, the chosen node's fixed line is used rather than
an unrelated pooled contextual reply.

## Persistence and privacy

Startup adds an idempotent `conversation_memories` table keyed by session UUID,
with summary, word count/limit, covered turn, provider and update time. It does
not replace or delete transcripts. Session deletion cascades to its summary.
Email addresses and long digit sequences are masked before summarization and
again before storage. This follows the current masking policy; it is not a
guarantee that every possible identifying detail is removed.

Save operations compare both coverage and the observed timestamp. Regeneration
invalidates the summary using a timestamped placeholder, then schedules a
rebuild, so an older in-flight result cannot restore obsolete facts. Historical
regeneration only accepts summaries preceding the requested turn; it never
includes a future summary.

An authenticated owner can inspect the current result at
`GET /api/arena/calls/{session_id}/memory`: `summary`, `word_count`, `max_words`,
`covered_turn`, `latest_turn`, `updated_at` and `enabled`. Other accounts receive
404. This is separate from `/summary`, the existing scoring/lesson endpoint.
An empty summary means it has not been produced yet or no valid output is ready.

## Configuration

```dotenv
CONVERSATION_SUMMARY_ENABLED=true
CONVERSATION_SUMMARY_MAX_WORDS=150
CONVERSATION_SUMMARY_EVERY_TURNS=4
CONVERSATION_SUMMARY_TIMEOUT_SECONDS=6
```

Changing `.env` requires recreating the app container. A changed word limit is
applied immediately when reading memory; the next update rebuilds memory using
the new limit. Example keys for existing providers remain in `.env.example`.

## Verification

Tests cover the hard word cap, negation-preserving sentence boundaries, masking,
free-before-paid fallback, the shared deadline, async queue bounds, historical
context, authenticated ownership, cache bypass and session-only reply storage.
A local PostgreSQL smoke check verified persistence, owner isolation, stale-save
rejection after regeneration and rebuild without future-turn leakage. Temporary
test rows were removed. One real Gemini request on synthetic dialogue returned
a 26-word summary that preserved “chưa chuyển tiền” and “không đọc mã”; this is a
smoke check, not an accuracy benchmark of conversation summaries.
