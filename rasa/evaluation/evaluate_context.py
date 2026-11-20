"""Evaluate contextual Rasa and the combined classifier on unseen caller prompts."""

import asyncio
import csv
import json
import logging
import re
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import structlog
from rasa.core.agent import Agent

from app.arena.intent_detector import Intent, detect_intent
from contextual_intent import PREFIX, normalize


ROOT = Path(__file__).resolve().parent


def rows_in(path):
    with path.open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file, delimiter="\t"))


async def main():
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
    train = {normalize(row["caller"]) for row in rows_in(ROOT.parent / "caller_acts.tsv")}
    cases = rows_in(ROOT / "context_heldout.tsv")
    seen = set()
    for row in cases:
        clauses = re.split(r"[.!?;\n]+", row["caller"])
        prompt = next(normalize(part) for part in reversed(clauses) if part.strip())
        key = (prompt, row["polarity"])
        if prompt in train or key in seen:
            raise SystemExit(f"Duplicate context case: {key}")
        seen.add(key)

    model = max(Path("/app/models").glob("*.tar.gz"), key=lambda path: path.stat().st_mtime)
    agent = Agent.load(str(model))
    results = Counter()
    for row in cases:
        caller, polarity, expected = row["caller"], row["polarity"], row["intent"]
        reply = {"yes": "Được ạ.", "no": "Không ạ."}[polarity]
        context = PREFIX + json.dumps({"caller_line": caller, "polarity": polarity}, ensure_ascii=False)
        prediction = (await agent.parse_message(context))["intent"]
        if prediction.get("contextual") is not True:
            raise SystemExit("The loaded model did not run contextual classification.")
        raw = prediction["name"]
        with patch("app.arena.rasa_client.classify_context_with_rasa", return_value=(None, 0.0)):
            previous = detect_intent(reply, caller_line=caller).intent.value
        with patch("app.arena.rasa_client.classify_context_with_rasa", return_value=(Intent(raw), prediction["confidence"])):
            result = detect_intent(reply, caller_line=caller)
        current = result.intent.value
        results.update({
            "rules": previous == expected,
            "rasa": raw == expected,
            "combined": current == expected,
            "improved": previous != expected and current == expected,
            "regressed": previous == expected and current != expected,
        })
        if previous != current or current != expected:
            print(f"{polarity} | {caller} | expected={expected} rules={previous} rasa={raw} combined={current}")
    print(f"Cases: {len(cases)}. Results: {dict(results)}")


if __name__ == "__main__":
    asyncio.run(main())
