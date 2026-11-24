# Mixed calls — implemented local scope

## Player flow

The call picker offers all-topic random practice or delivery, appointments and
customer support separately. There are 18 curated variants: three families, two
truth classes, three difficulty levels. Higher levels add role/context question
branches, not just different vocabulary. Ordinary and fraudulent variants share
initial context and opening, so job title or voice is not the answer.

Players choose fixed/adaptive difficulty and training/assessment before answering.
The server freezes a scenario version, seed and case variables before the greeting.
Context appears next to the phone. Evidence inspection, simulated notifications,
independent-channel checks, and gated simulated risky actions are available. No
external link is opened and no real credential is requested by these controls.
Only new local simulation events are logged; microphone/STT/TTS are unchanged.

After server-confirmed hangup, players classify the call and optionally give a
reason. The first judgement and its evaluation are immutable through the player
API. Responses and reasons mask long digit strings/emails using the existing
masker. Rubric practice-v1 separates judgement (40 points correct, 20 uncertain),
evidence (30 independent verification, otherwise 15 inspection), and avoiding
simulated risky actions (30). Dialogue compliance is reported as a signal, not
proof of performing an external action. There is no reaction-speed penalty.
Unknown/uncertain is distinct from a false alarm or a missed fraud.

Assessment hides diagnostic subtitles and regeneration controls. The server also
rejects regeneration for assessment sessions. Ground truth/summary is withheld
until judgement. History and transcript titles remain neutral for mixed families.
This is educational software, not a proctored or cheat-proof examination.

## Selection and replay

The selector first chooses fraud with 75% probability or benign with 25%, then
finds the nearest requested difficulty in that class. It selects only the least
encountered scenarios in that pool, using the account's full persisted history.
Unseen scenarios therefore precede repeats; each class rotates independently.
This preserves the 75/25 probability even when the catalog contains equal counts
of benign and fraudulent scenarios. A fraud scenario may repeat before every
benign scenario has been seen. Strict non-repetition across both classes would
instead force the long-term ratio to match the catalog's composition.

Selection weights and the last 12 calls break ties among equally encountered
scenarios. New scenarios are prioritized as unseen; changing difficulty or topic
restricts the eligible pool. Direct scenario selection bypasses random selection.
An account-scoped transaction lock prevents concurrent starts from choosing
without observing each other's sessions. There is no fixed true/false sequence.
After at least five judgements,
adaptive difficulty uses the last ten correct classifications without risky
simulation events: >=80% advanced, >=50% intermediate, otherwise beginner.

The case stores seed, candidate/weight snapshot, recent scenario IDs, lifetime
encounter counts, selected level, class probability and policy version
(`mixed-v2-class-cycles`). Selection can be replayed from that snapshot; legacy
`mixed-v1` snapshots retain their original equal-class algorithm. Case
variables include simulated reference, time window and location. The variables,
scenario graph, fixed lines, transition scores and rubric metadata are versioned
or pinned. Speech timing and stochastic LLM wording are not deterministic replay.

## Administration

`/practice-admin.html` is linked in the existing admin toolbar. Every backing
endpoint enforces admin authentication, including catalog reads, weighting,
activation, statistics, proposals and approval/rejection. The page supports:

- Edit a validated JSON document copied from the active catalog.
- Preview the complete proposal before approving or rejecting it.
- Publish immutable versions atomically, without changing in-progress calls.
- Pause/re-enable scenarios and change selection weight for future calls.
- Inspect correct/uncertain, false-alarm and missed-fraud counts by family/class,
  plus recorded simulation events and denominators.

Proposals are pending until explicitly approved. The authoring schema rejects
benign cases that request sensitive actions or punish normal consent. IDs use
`practice-` and supported families. `case_blueprint` holds versioned evidence and
official-channel facts alongside the document's player context.

## Data and rollout

`scenario_versions` freezes published graph definitions. Existing node/session IDs
and transcripts are retained; pre-migration historical edits cannot be recreated.
`call_sessions` pins a version and stores case parameters/world state/selection
trace. `practice_events`, `practice_judgements`, `practice_reviews` and
`practice_bundle_versions` track evidence, frozen evaluation, reviewed publication
and reviewed built-in bundle installation. SQL guards protect fixed graphs;
LLM cache/preferences and opener counts remain mutable.

Startup does not overwrite published graphs from authoring JSON. The reviewed
built-in bundle is installed under an explicit bundle revision; approved admin
versions are preserved. New content changes require a new reviewed bundle
revision or admin publication. Two older delivery prototypes remain for backward
compatibility but are excluded from the random practice selector.

Before migration a custom-format local database dump was saved in the Windows
temporary directory (`scam-arena-step1-before-20261124.dump`). VPS deployment has
its own backup step. Downgrading to code predating version support requires a
matching database restore, not just switching the old image back.

## Verification and limits

Python/JS checks cover schema, permissions, balanced selection, recency penalties,
seed replay, and microphone lifecycle. `backend/tools/check_scenario_versions.py`
creates and drops a disposable PostgreSQL database; it verifies migrations,
restart idempotency, old/new version scoring isolation, every family, adaptive
selection, evidence/event gating, owner privacy, frozen judgement, admin approval,
configuration and bounded conversation length. CI uses a dedicated PostgreSQL
service. Headless browser checks exercise assessment, phone messages, debrief,
admin catalog and review rejection, without recording a person's microphone.

The library is six core case designs expressed at three levels, not 18 unrelated
stories. Automated checks verify functionality and consistency, not measured
human training effectiveness. Human playtesting can refine wording and rubrics;
the functional mixed-call scope is available without another setup step.
