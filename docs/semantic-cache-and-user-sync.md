# Semantic reuse and account list freshness

The dialogue engine already reused normalized exact inputs and an intent-level pool. It now uses conservative paraphrase similarity rather than treating every input with the same intent as interchangeable.

## Pretrained CPU model

- Runtime: [Qdrant FastEmbed](https://github.com/qdrant/fastembed), using ONNX on one CPU thread.
- Model: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, a pretrained multilingual sentence encoder. No per-user training or external embedding API is required.
- The first server startup downloads the model into `/models/huggingface/semantic`, persisted in the existing model-cache volume. Startup health does not wait for this download. Before the model is ready, the app continues with exact lookup and normal LLM generation.
- `SEMANTIC_CACHE_ENABLED=true` and `SEMANTIC_CACHE_THRESHOLD=0.93` are Compose defaults. Disable the feature to avoid loading the additional CPU model. Model initialization failure also leaves normal conversation available.
- At most 128 stored candidates are retrieved, and 1024 sentence vectors are held in a process-local LRU. A busy embedding worker skips the match instead of queuing conversation requests. The first comparison for a phrase costs more than subsequent cached-vector comparisons.

## Conditions for reuse

The candidate must be enabled, have nonnegative preference, and match the same target node, intent, reprompt flag, prompt version and context fingerprint. That fingerprint includes interaction mode, case facts and recent conversation; it excludes only the current player wording and internal provider metadata. Every returned reply is validated against the current requested action.

Similarity is considered only for clear refusal, compliance, doubt and hang-up intents. Short acknowledgements, questions, conditions, numbers, redacted inputs, sensitive-code references and conflicting negations do not use semantic reuse. A cosine threshold is a filter, not a probability or correctness guarantee. Some valid paraphrases intentionally miss the cache and go to the LLM. The matching layer does not change intent classification, scoring or scenario transitions.

A stored summary, older unsummarized history or available simulated messages forces contextual generation. Legacy rows without a context fingerprint remain stored but are excluded from automatic reuse; new eligible generations gradually populate the safer cache. Reused lines carry `cache_semantic` provenance. Negative feedback and regeneration continue to reduce preference so those lines are not selected.

No Qdrant service, vector database, training table or new account table is added. Two nullable columns on `dialogue_lines` retain the eligible player sample and context hash; the existing `call_turns.line_source` constraint also accepts semantic reuse.

## Account list

The admin list refreshes when opened, every 30 seconds while visible, when the tab becomes visible again, and when the window regains focus. It stops polling outside the users view. Manual refresh and filters still work. The detail panel receives refreshed counts without scrolling or erasing an unfinished lock/unlock reason. Updates show the last retrieval time and current website origin.

Successful registration already commits both the account and login session. Registration now records `last_login_at` too. This timestamp means login, not online presence. The API list sends `Cache-Control: no-store`.

Localhost and the public VPS use different databases. Reloading does not synchronize those databases. An account registered on one server is not expected in the other server's admin list. Check the origin printed above the table before investigating missing users.

## Verification

```bash
python -m pytest backend/tests/test_semantic_cache.py backend/tests/test_line_generator.py backend/tests/test_service_status.py -q
docker exec scam-arena python backend/tools/check_user_management.py
docker exec scam-arena python backend/tools/check_semantic_cache.py
```

Both integration tools create and remove disposable databases. The semantic check uses the real local model, mocks only LLM generation and confirms that negation, changed facts, memory and downvoted lines cannot reuse an earlier reply.

For production account investigation, this command is read-only and does not print keys, password hashes or conversation contents:

```bash
docker exec scam-arena python backend/tools/check_user_store.py --username USERNAME
```

No account deletion, database merging or reset is required for these changes.
