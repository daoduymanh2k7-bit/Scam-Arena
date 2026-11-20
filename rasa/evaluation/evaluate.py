"""Compare Rasa NLU models on the same held-out Vietnamese utterances."""

import argparse
import asyncio
import csv
import hashlib
import json
import logging
import re
import unicodedata
from collections import Counter
from pathlib import Path

import structlog
from rasa.core.agent import Agent
from rasa.shared.nlu.training_data.loading import load_data


ROOT = Path(__file__).resolve().parent
LABELS = ("verify", "refuse", "doubt", "comply", "share_sensitive", "transfer_money", "hang_up", "unknown")
RISK_LABELS = {"share_sensitive", "transfer_money"}


def normalize(text):
    folded = unicodedata.normalize("NFKD", text.casefold().replace("đ", "d"))
    plain = "".join(character for character in folded if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9]+", plain))


def training_text_keys(additional_training=None):
    sources = [ROOT.parent / "data", ROOT / "training"]
    if additional_training is not None:
        sources.append(additional_training)
    return {normalize(message.get("text"))
            for source in sources for message in load_data(str(source)).intent_examples}


def validate_rows(rows, allowed_styles, additional_training=None):
    if not rows:
        raise SystemExit("Evaluation set is empty.")
    training_keys = training_text_keys(additional_training)
    seen = set()
    for index, row in enumerate(rows, 1):
        key = normalize(row["text"])
        if row["intent"] not in LABELS or not key or row["style"] not in allowed_styles:
            raise SystemExit(f"Invalid evaluation row {index}.")
        if key in seen or key in training_keys:
            raise SystemExit(f"Evaluation row {index} duplicates another example.")
        seen.add(key)


def evaluation_rows():
    with (ROOT / "heldout.tsv").open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file, delimiter="\t"))
    validate_rows(rows, {"conversation", "asr_like"})
    if set(row["intent"] for row in rows) != set(LABELS):
        raise SystemExit("The evaluation must include all eight intents.")
    return rows


def speaker_holdout_rows(path, additional_training=None):
    dataset = json.loads(path.read_text(encoding="utf-8-sig"))
    training_speakers = set(dataset["training_speakers"])
    rows = dataset["rows"]
    validate_rows(rows, {"whisper", "message"}, additional_training)
    speakers = {row["speaker"] for row in rows}
    if "" in speakers or not training_speakers or speakers & training_speakers:
        raise SystemExit("Training and holdout must declare disjoint speaker groups.")
    print(f"Speaker holdout: {len(rows)} rows from {len(speakers)} speaker groups.")
    return rows


async def predict(path, rows):
    if path.is_dir():
        models = sorted(path.glob("*.tar.gz"), key=lambda model: model.stat().st_mtime)
        if not models:
            raise SystemExit(f"No Rasa model in {path}")
        path = models[-1]
    print(f"Model: {path.name}", flush=True)
    agent = Agent.load(str(path))
    predictions = []
    for row in rows:
        result = await agent.parse_message(row["text"])
        intent = result["intent"]
        name = intent.get("name")
        # Rasa's fallback label and low-confidence output both defer to the next stage.
        if name not in LABELS or intent.get("confidence", 0) < 0.65:
            name = "unknown"
        predictions.append(name)
    return predictions


def report(rows, predictions, *, class_metrics=True):
    total = len(rows)
    pairs = Counter((row["intent"], prediction) for row, prediction in zip(rows, predictions))
    correct = sum(pairs[label, label] for label in LABELS)
    false_certain = sum(pairs["unknown", label] for label in LABELS if label != "unknown")
    false_risk = sum(pairs[expected, predicted] for expected in LABELS if expected not in RISK_LABELS
                     for predicted in RISK_LABELS)
    print(f"Accuracy: {correct}/{total} ({correct / total:.1%})")
    print(f"Unknown misclassified as a known intent: {false_certain}/{sum(row['intent'] == 'unknown' for row in rows)}")
    print(f"Non-risk answers misclassified as high risk: {false_risk}/{sum(row['intent'] not in RISK_LABELS for row in rows)}")
    if not class_metrics:
        print("Scored label coverage:", ", ".join(sorted({row["intent"] for row in rows})))
    else:
        f1_scores = []
        for label in LABELS:
            matches = pairs[label, label]
            actual = sum(pairs[label, item] for item in LABELS)
            predicted = sum(pairs[item, label] for item in LABELS)
            f1 = 2 * matches / (actual + predicted)
            f1_scores.append(f1)
            print(f"  {label}: recall {matches}/{actual}, F1 {f1:.1%}")
        print(f"Macro F1: {sum(f1_scores) / len(LABELS):.1%}")
    for style in sorted({row["style"] for row in rows}):
        subset = [(row, pred) for row, pred in zip(rows, predictions) if row["style"] == style]
        print(f"  {style}: {sum(row['intent'] == pred for row, pred in subset)}/{len(subset)}")
    mistakes = sorted(((count, expected, predicted) for (expected, predicted), count in pairs.items()
                       if expected != predicted), reverse=True)
    print("Most common errors:", ", ".join(f"{a} -> {b}: {count}" for count, a, b in mistakes[:5]))


async def compare(args, rows, speaker_rows):
    all_rows = rows + speaker_rows
    print("\nBaseline")
    baseline = await predict(args.baseline, all_rows)
    report(rows, baseline[:len(rows)])
    if speaker_rows:
        print("Speaker holdout:")
        report(speaker_rows, baseline[len(rows):], class_metrics=False)
    if args.candidate:
        print("\nCandidate")
        candidate = await predict(args.candidate, all_rows)
        report(rows, candidate[:len(rows)])
        comparisons = Counter((left == row["intent"], right == row["intent"])
                              for row, left, right in zip(rows, baseline, candidate))
        print(f"Paired comparison: {comparisons[False, True]} improved, {comparisons[True, False]} regressed")
        if speaker_rows:
            print("Speaker holdout:")
            report(speaker_rows, candidate[len(rows):], class_metrics=False)


async def main():
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--speaker-holdout", type=Path)
    parser.add_argument("--candidate-training", type=Path, help="Check additional NLU examples for evaluation overlap.")
    args = parser.parse_args()
    rows = evaluation_rows()
    if args.candidate_training:
        validate_rows(rows, {"conversation", "asr_like"}, args.candidate_training)
    digest = hashlib.sha256((ROOT / "heldout.tsv").read_bytes()).hexdigest()
    print(f"Held-out rows: {len(rows)}; SHA-256 {digest}")
    speaker_rows = speaker_holdout_rows(args.speaker_holdout, args.candidate_training) if args.speaker_holdout else []
    await compare(args, rows, speaker_rows)


if __name__ == "__main__":
    asyncio.run(main())
