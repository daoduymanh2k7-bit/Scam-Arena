# Intent detection — Step 2 design

This document defines how v1 classifies one player's utterance during a Scam Arena scenario. The rule-based detector is implemented in `backend/app/arena/intent_detector.py` and connected to the branching scenario flow. The global keyword scorer remains legacy until step 4.

## What the detector receives and returns

The detector receives:

- `text`: the recognized or typed user response.
- `stage_id`: the current scenario stage.
- `requested_action`: what the caller is asking for in this stage, such as `share_sensitive`, `transfer_money`, `install_app`, or `keep_secret`.

It returns one primary intent and an evidence phrase for debugging/admin preview:

```json
{
  "intent": "verify",
  "matched_rule": "verify_official_channel",
  "evidence": "tôi sẽ tự gọi tổng đài chính thức"
}
```

The branching engine uses this same detected `intent` to choose a database transition and to look up that transition's score and feedback. Each persisted turn records the intent, detection method, and score result. There is no second keyword scorer in the active call flow.

## Proposed intent set

| Intent | Meaning | Example utterances |
| --- | --- | --- |
| `share_sensitive` | The player affirmatively gives, has given, or clearly agrees to disclose OTP, password, recovery code, card/security data, or identity details. | “Mã OTP là 123456.” / “Tôi sẽ đọc mã cho anh.” |
| `transfer_money` | The player clearly agrees to, attempts, or says they completed a transfer/payment requested by the caller. | “Tôi chuyển khoản ngay.” / “Tôi đã chuyển rồi.” |
| `hang_up` | The player clearly ends or blocks the call. | “Tôi cúp máy đây.” / “Tôi sẽ chặn số này.” |
| `verify` | The player chooses an independent official channel to confirm the claim, rather than using the caller's link/number. | “Tôi cúp máy rồi tự gọi hotline trên thẻ.” |
| `refuse` | The player clearly rejects the requested action without indicating that it was already done. | “Tôi không cung cấp OTP.” / “Tôi không cài ứng dụng đó.” |
| `comply` | The player agrees to a risky requested action that is not classified more specifically as disclosure or money transfer. | “Vâng, tôi sẽ bấm vào đường link.” / “Tôi sẽ cài ứng dụng theo hướng dẫn.” |
| `doubt` | The player expresses suspicion or asks a question but has not yet clearly refused, verified, complied, disclosed, transferred, or ended the call. | “Sao ngân hàng lại cần mã này?” / “Việc này nghe không ổn.” |
| `unknown` | No intent can be determined from the answer and stage context. | “Ừm…” / unrelated or too unclear speech. |

`transfer_money` is separate from `comply` so the game can distinguish a general risky agreement from a high-impact financial action. `share_sensitive` and `transfer_money` mean a harmful action was stated affirmatively; a keyword mention alone is not enough.

## Decision order

Apply these rules in order and stop at the first confident match:

1. **`share_sensitive`** — affirmative disclosure/commitment. Reject negated, quoted, hypothetical, and warning mentions.
2. **`transfer_money`** — affirmative agreement, attempt, or completed transfer. Reject explicit refusal/negation.
3. **`hang_up`** — clear intention to end/block the call.
4. **`verify`** — independent verification through an official channel.
5. **`refuse`** — clear rejection of the current request.
6. **`comply`** — agreement to the stage's `requested_action`, excluding disclosure or transfer.
7. **`doubt`** — suspicion/question without a clearer action above.
8. **`unknown`** — none of the above has enough evidence.

For mixed answers, harmful action already taken takes priority over a later safe statement: “Tôi đã đọc OTP rồi, giờ tôi sẽ gọi ngân hàng” is `share_sensitive`. Among safe actions, `hang_up` precedes `verify`, which precedes `refuse`; all are safe outcomes but can lead to distinct feedback.

## Rule-based method for v1

1. The built-in high-confidence rules normalize Unicode and punctuation while preserving Vietnamese accents. Editable database `contains` phrases additionally use a normalized accentless form; database `regex` rules use lowercased NFC text with accents preserved.
2. Match phrase patterns and action verbs, not isolated words. For example, `OTP` by itself may occur in a warning and must not count as disclosure.
3. Evaluate negation in the same clause before harmful matches. Examples: “không đọc OTP”, “đừng chuyển tiền”, and “tôi từ chối cài ứng dụng” are not compliance or harmful actions.
4. Use the stage's `requested_action` to resolve short affirmations. “Vâng” in a `share_sensitive` stage maps to `share_sensitive`; in a `transfer_money` stage it maps to `transfer_money`; in an `install_app` stage it maps to `comply`. If the stage is `none`/`other` and the answer is only “vâng”, return `unknown`.
5. If the transcript is partial or contradictory and no rule has sufficient evidence, return `unknown`; do not guess.

The detector is connected to the engine. It tries built-in safety/action rules first, then enabled database phrases (shared rules plus rules scoped to the active numeric scenario ID). Database phrase priority sorts higher values first. Contradictory matches or a negated database phrase resolve to `unknown`. The current build is deterministic and does not call an LLM; add one only after evaluating a labeled golden set.

## Review examples

| User answer | Stage requested action | Expected intent | Reason |
| --- | --- | --- | --- |
| “Mã OTP của tôi là 123456.” | `share_sensitive` | `share_sensitive` | Affirmative disclosure. |
| “Tôi không đọc OTP cho ai.” | `share_sensitive` | `refuse` | Negation blocks disclosure; explicit refusal matches. |
| “Vâng, tôi đọc mã đây.” | `share_sensitive` | `share_sensitive` | Contextual agreement to reveal a code. |
| “Vâng.” | `transfer_money` | `transfer_money` | Short agreement inherits the stage's requested action. |
| “Tôi không chuyển khoản.” | `transfer_money` | `refuse` | Explicit negation/refusal. |
| “Tôi sẽ gọi số trên thẻ để hỏi ngân hàng.” | `share_sensitive` | `verify` | Independent official-channel verification. |
| “Sao lại phải giữ bí mật?” | `keep_secret` | `doubt` | Suspicion without clear refusal/action. |
| “Tôi cúp máy và chặn số này.” | `other` | `hang_up` | Explicitly ends the call. |
| “Vâng.” | `other` | `unknown` | Not enough context to infer what the player agreed to. |

## Current implementation and review notes

The implementation currently provides:

- The intent names and definitions include the separate `transfer_money` label.
- Phrase examples document positive matches, negation, short context-dependent answers, and ambiguous speech.
- Each scenario stage declares `requested_action` where short confirmations need context.
- One deterministic priority order feeds both routing and scoring; each turn records the selected intent and score result.
- The schema and scenario files use the same eight intent names.
- Voice input is transcribed first; this module classifies the resulting text and does not perform speech recognition itself.
- The current rules still need evaluation against a labeled golden set before making an accuracy claim or deciding whether to add an LLM fallback.

The detector is now wired into the branching engine. Voice input is transcribed first; this module classifies the resulting text and does not perform speech recognition itself. Scoring is stored on scenario transitions in PostgreSQL; an LLM fallback remains deferred until measured rule accuracy justifies it.
