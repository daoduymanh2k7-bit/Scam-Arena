# Alternative caller replies

During a phone call, the latest persisted, nonterminal caller reply has a
`Tạo câu trả lời khác` button. Greetings and the initial scenario opening do not
represent a player turn, so they have no regeneration button. Older reply buttons
are disabled after another player turn, during processing/playback, and after
hangup. Streaming recognition is unchanged.

Clicking suspends microphone capture, cancels any draft stream, and calls the
existing authenticated regeneration endpoint. The same player text, intent and
target node are used. The new text replaces the current caller subtitle and is
spoken with the selected caller voice. Failure keeps the old text and allows
another attempt. It does not submit another player turn or recalculate scoring.

After successful generation, a transaction locks and rechecks session/turn state.
Only the original currently selected catalogued LLM line loses one preference
point. Fixed lines and uncatalogued context-specific text have no decrement.
The preference is shared catalog data, not a player score. Concurrent/stale
requests are rejected without applying another decrement. Generated text may
remain in the catalog if a concurrent update invalidates the request; it is not
selected and does not cause a preference decrement. Summary memory is invalidated
only after a replacement commits. No database schema change is required.

Phone scenario openings omit greetings/courtesy already exchanged by the UI;
message-mode openings and stored source lines remain intact. Dialogue generation
and regeneration receive `caller_line` in addition to recent turns and memory.
An `unknown` label is not treated as proof of unintelligible audio. Explicit
listening acknowledgements and transaction questions get relevant intro fallback
text if generation is unavailable, rather than another listening check. This
does not change intent labels, scoring, graph transitions, or ASR settings.

Validation: Python tests cover failed generation, stale/duplicate replacement,
fixed/uncatalogued text, and explicit clarification cues. A local PostgreSQL
check verifies a single -1 adjustment and identical session state. A headless
browser check verifies microphone gating, one regeneration on a double click,
in-place subtitle replacement and no extra player turn.
