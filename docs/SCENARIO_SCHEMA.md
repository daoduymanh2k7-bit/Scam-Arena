# Scam Arena scenario schema — v1 design

This document defines the authoring format for branching Scam Arena scenarios. Files in `data/scenarios/` seed PostgreSQL on first startup; PostgreSQL is the runtime source. Only scenarios with `status: "published"` appear in the player; draft and archived scenarios remain hidden.

The formal JSON Schema is [`scenario.schema.json`](scenario.schema.json). A complete example is in [`examples/police-call-001.json`](examples/police-call-001.json).

## Goals

- Let an admin author a scenario as data without changing Python code.
- Support deterministic, branching dialogue before any LLM is introduced.
- Use the same detected user intent for conversation routing and scoring.
- Keep scenario documents portable as JSON while storing and serving them from PostgreSQL.
- Keep draft scenarios out of the player-facing scenario list.

## Top-level fields

| Field | Meaning |
| --- | --- |
| `schema_version` | Format version used to validate and migrate the file. Starts at `1`. |
| `id` | Stable slug and filename, for example `police-call-001`. Do not change it after publication. |
| `version` | Content revision number. Increment when editing a published scenario. |
| `status` | `draft`, `published`, or `archived`. The game serves only `published`. |
| `title`, `category`, `difficulty`, `locale` | Metadata used by the picker and filtering. |
| `summary`, `user_context` | Admin/player-facing description and setup. |
| `persona` | Fictional caller details and tone. No real person's identifying details. |
| `start_stage_id`, `stages` | Entry stage and directed dialogue graph. |
| `red_flags` | Teachable warning signs tied to stages. |
| `scoring` | Starting score and intent-based feedback/score changes. |
| `lesson_summary` | Closing lesson shown after the call. |
| `created_at`, `updated_at`, `published_at` | ISO 8601 timestamps managed by the admin service. `published_at` is null until publication. |

## Stages and transitions

Each stage has an `id`, a caller `opening_line`, one or more `fallback_lines`, a `requested_action`, and transitions keyed by supported intents. `requested_action` identifies what the caller is pressuring the player to do at that point. It lets the detector interpret short answers such as “vâng” in context. `default_next_stage_id` handles an intent that has no explicit transition. `max_turns` and `timeout_next_stage_id` bound repeated or unanswered turns.

`next_stage_id`, `default_next_stage_id`, and `timeout_next_stage_id` must name a stage in the same scenario or one of these terminal outcomes:

- `END_SAFE`: the player safely refused, verified independently, or ended the call.
- `END_UNSAFE`: the player disclosed sensitive information or agreed to a risky action.
- `END_NEUTRAL`: the call ended without enough evidence to classify the result.

Supported intents for v1: `verify`, `refuse`, `doubt`, `comply`, `share_sensitive`, `transfer_money`, `hang_up`, and `unknown`. The intent detector is rule-based in v1. It receives the user's text plus the current stage's `requested_action`; it should return `unknown` when it cannot confidently classify an answer, and the engine then uses the stage fallback/default route. Full definitions and example utterances are in [`INTENT_DETECTION.md`](INTENT_DETECTION.md).

The detector returns exactly one intent per user turn. Use this deterministic priority: confirmed `share_sensitive`, confirmed `transfer_money`, `hang_up`, `verify`, `refuse`, contextual `comply`, `doubt`, then `unknown`. Check negation before assigning a harmful intent: “tôi không đọc OTP” is not disclosure and “tôi không chuyển tiền” is not a transfer. The classifier and scorer must consume this same intent result rather than independently matching keywords.

## Scoring semantics

The server starts at `scoring.base_score`, applies at most one matching `points_delta` per user turn, then clamps the final score to 0–100. Positive deltas reward safe choices; negative deltas penalize risky choices. A `critical` rule marks a serious mistake and must be shown clearly in the result. `stage_id` on a rule is optional; when present, that rule applies only in the named stage. If both a stage-specific and global rule match, the stage-specific rule wins. There may be at most one global rule for each intent and at most one rule for each `(stage_id, intent)` pair.

Response time is deliberately not part of this schema's score rules. It can be shown separately as a rough practice metric, not as a measure of emotion or panic.

## Validation beyond JSON Schema

JSON Schema validates field types and basic limits. The loader must also validate graph relationships and publishability:

1. Scenario IDs and stage IDs are unique; IDs match their patterns and do not use the `END_` prefix.
2. `start_stage_id` exists.
3. Each transition intent is unique within its stage.
4. Every stage and scoring/red-flag reference points to an existing stage or valid terminal outcome as appropriate.
5. Every stage has a fallback, a default route, and a timeout route.
6. Every stage is reachable from the start stage, and every reachable path can reach a terminal outcome.
7. A published scenario has at least one red flag, at least one scoring rule, and a non-empty lesson summary.
8. No two scenario files share the same `id`.
9. `status` and `published_at` agree: drafts have a null `published_at`; published scenarios have a timestamp.
10. Scoring rules are unique by `(stage_id, intent)`; the stage-specific-over-global precedence is unambiguous.

Validation errors should identify the JSON path, such as `stages[1].transitions[2].next_stage_id`, so an admin can fix the file without reading server logs.

## JSON source and PostgreSQL runtime

Keep one authoring file per scenario at `data/scenarios/<id>.json`. On startup, the application imports scenario metadata into `scenarios`, each stage's caller line into `dialogue_nodes`, and each stage intent route into `dialogue_transitions`. PostgreSQL is the runtime source after import; edit-through-admin and controlled re-import are later work.

The JSON file remains the reviewable source in Git. It is not rewritten by PostgreSQL, and editing an already seeded file does not overwrite runtime rows automatically. The runtime database stores one current row per scenario; this implementation does not preserve content revisions in PostgreSQL.

## Example authoring rules

- Keep caller lines short and plausible for spoken audio.
- Use fictional identities, phone numbers, organizations, and account details.
- Teach recognition and safe response; do not include operational instructions that would help commit fraud.
- Make the safe exit obvious and available from every stage.
- Keep scenario content in Vietnamese (`locale: "vi-VN"`) unless a future locale is explicitly supported.
