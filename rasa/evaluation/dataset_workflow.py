"""Collect, review and export local Scam Arena samples for Rasa DIET."""

import argparse
import hashlib
import hmac
import json
import re
import secrets
import unicodedata
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory


LABELS = {"verify", "refuse", "doubt", "comply", "share_sensitive", "transfer_money", "hang_up", "unknown"}
SPLITS = {"train", "holdout"}
PRIVATE_TEXT = re.compile(
    r"\d|@|\*{2,}|\[(?:email|redacted|phone)\]|(?:https?|ftp)\s*:|www\.|"
    r"\b[\w-]+\.(?:vn|com|net|org|io)\b",
    re.I,
)


def read_json(path, default):
    return json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else default


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


@contextmanager
def workspace_lock(workspace):
    workspace.mkdir(parents=True, exist_ok=True)
    lock = workspace / ".workflow-lock"
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise WorkspaceBusy from exc
    try:
        yield
    finally:
        lock.rmdir()


class WorkspaceBusy(ValueError):
    def __init__(self):
        super().__init__("Another dataset command holds the workspace lock.")


def fingerprint(salt, kind, value):
    return hmac.new(salt, f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()[:24]


def allowed_text(raw):
    text = " ".join(unicodedata.normalize("NFKC", raw).split())
    if not text or PRIVATE_TEXT.search(text) or any(unicodedata.category(char) == "Cf" for char in text):
        return None
    return text


def collect_rows(workspace, turns):
    workspace.mkdir(parents=True, exist_ok=True)
    key_path = workspace / "pseudonym.key"
    path = workspace / "review.json"
    if not key_path.exists():
        if path.exists() or (workspace / "split_lock.json").exists():
            raise ValueError("Existing review workspace is missing its pseudonym key.")
        with key_path.open("xb") as key_file:
            key_file.write(secrets.token_bytes(32))
    salt = key_path.read_bytes()
    review = read_json(path, {"speakers": {}, "rows": []})
    known = {row["sample"] for row in review["rows"]}
    added = skipped = 0
    for turn_id, user_id, mode, raw in turns:
        sample = fingerprint(salt, "turn", turn_id)
        if sample in known:
            continue
        text = allowed_text(raw)
        if text is None or not user_id:
            skipped += 1
            continue
        speaker = fingerprint(salt, "speaker", user_id)
        review["speakers"].setdefault(speaker, None)
        review["rows"].append({
            "sample": sample, "speaker": speaker, "style": "whisper" if mode == "call" else "message",
            "text": text, "intent": None,
        })
        known.add(sample)
        added += 1
    write_json(path, review)
    print(f"Added {added} samples. Filtered {skipped}. Review queue: {len(review['rows'])}.")
    return {"added": added, "filtered": skipped, "total": len(review["rows"])}


def collect(workspace):
    import psycopg
    from app.database import DATABASE_URL

    with psycopg.connect(DATABASE_URL) as connection, connection.cursor(name="rasa_review") as cursor:
        connection.read_only = True
        cursor.execute("""
            SELECT t.turn_id, s.user_id, s.interaction_mode, t.user_text_masked
            FROM call_turns AS t JOIN call_sessions AS s USING (session_id)
            WHERE s.user_id IS NOT NULL AND t.user_text_masked IS NOT NULL
            ORDER BY t.turn_id
        """)
        return collect_rows(workspace, cursor)


def prepare(review, locked, excluded_keys, normalize):
    speakers = review["speakers"]
    if any(split not in SPLITS | {None} for split in speakers.values()):
        raise ValueError("Speaker split must be train, holdout or null.")
    if any(speakers.get(speaker) != split for speaker, split in locked.items()):
        raise ValueError("A speaker already used in a batch cannot change split.")

    by_text = defaultdict(list)
    for row in review["rows"]:
        label = row["intent"]
        if label is None or label == "skip":
            continue
        text = allowed_text(row["text"])
        if label not in LABELS or row["style"] not in {"message", "whisper"} or not text:
            raise ValueError(f"Invalid approval for sample {row['sample']}.")
        if speakers.get(row["speaker"]) not in SPLITS:
            raise ValueError(f"Assign an approved sample's speaker before building: {row['sample']}.")
        key = normalize(text)
        if not key:
            raise ValueError(f"Empty normalized text for sample {row['sample']}.")
        by_text[key].append({**row, "text": text})

    groups = {"train": [], "holdout": []}
    dropped = Counter()
    for key, rows in by_text.items():
        splits = {speakers[row["speaker"]] for row in rows}
        if key in excluded_keys or len(splits) != 1 or len({row["intent"] for row in rows}) != 1:
            dropped["overlap or conflicting label"] += len(rows)
            continue
        groups[speakers[rows[0]["speaker"]]].append(rows[0])
        dropped["duplicate"] += len(rows) - 1
    if not groups["train"] or not groups["holdout"]:
        raise ValueError("Need reviewed, unique samples in both splits after filtering.")
    return groups, dropped


def build(workspace, batch):
    from evaluate import evaluation_rows, normalize, training_text_keys
    from rasa.shared.nlu.training_data.formats.rasa_yaml import RasaYAMLWriter
    from rasa.shared.nlu.training_data.message import Message
    from rasa.shared.nlu.training_data.training_data import TrainingData

    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]*", batch):
        raise ValueError("Batch name may contain ASCII letters, digits, hyphens and underscores.")
    path = workspace / batch
    if path.exists():
        raise FileExistsError(f"Batch already exists: {batch}.")
    review = read_json(workspace / "review.json", {"speakers": {}, "rows": []})
    locked_path = workspace / "split_lock.json"
    locked = read_json(locked_path, {})
    excluded = training_text_keys() | {normalize(row["text"]) for row in evaluation_rows()}
    groups, dropped = prepare(review, locked, excluded, normalize)
    training = TrainingData([Message.build(row["text"], intent=row["intent"]) for row in groups["train"]])
    locked.update({row["speaker"]: split for split, rows in groups.items() for row in rows})
    with TemporaryDirectory(dir=workspace) as temporary:
        staging = Path(temporary) / batch
        staging.mkdir()
        RasaYAMLWriter().dump(staging / "reviewed_nlu.yml", training)
        write_json(staging / "speaker_holdout.json", {
            "training_speakers": sorted({row["speaker"] for row in groups["train"]}),
            "rows": [{field: row[field] for field in ("speaker", "style", "text", "intent")} for row in groups["holdout"]],
        })
        write_json(locked_path, locked)
        staging.rename(path)
    print(f"Batch {batch}: {len(groups['train'])} train, {len(groups['holdout'])} holdout, {sum(dropped.values())} filtered.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("collect")
    export = commands.add_parser("build")
    export.add_argument("batch")
    args = parser.parse_args()
    try:
        with workspace_lock(args.workspace):
            if args.command == "collect":
                collect(args.workspace)
            else:
                build(args.workspace, args.batch)
    except (ValueError, FileExistsError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
