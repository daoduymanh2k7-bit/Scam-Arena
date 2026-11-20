import re

import pytest

from dataset_workflow import collect_rows, prepare, read_json, write_json


def test_collect_filters_and_preserves_review(tmp_path):
    turns = [
        (1, "account-a", "call", "  Tôi muốn tự kiểm tra.  "),
        (2, "account-a", "message", "Mã là １２３４"),
        (3, "account-b", "message", "Email [email]"),
        (4, "account-b", "call", "Mật khẩu ****"),
        (5, "account-b", "message", "Xem https://example.com"),
        (6, None, "call", "Tôi cúp máy."),
    ]
    collect_rows(tmp_path, turns)
    path = tmp_path / "review.json"
    review = read_json(path, None)
    (row,) = review["rows"]
    assert row["text"] == "Tôi muốn tự kiểm tra."
    assert row["intent"] is None
    assert row["style"] == "whisper"
    assert "account-a" not in path.read_text(encoding="utf-8")
    row["intent"] = "verify"
    write_json(path, review)
    collect_rows(tmp_path, turns)
    assert read_json(path, None) == review


def test_prepare_removes_overlap_and_keeps_speakers_disjoint():
    examples = [
        ("train", "Mình sẽ từ chối.", "refuse"),
        ("holdout", "Tôi tự gọi qua quầy.", "verify"),
        ("train", "Chờ đã!", "unknown"),
        ("holdout", "chờ đã", "unknown"),
        ("train", "Câu đã có", "doubt"),
        ("holdout", "Mẫu chưa duyệt", None),
    ]
    review = {
        "speakers": {split: split for split in ("train", "holdout")},
        "rows": [{"sample": str(i), "speaker": split, "text": text, "intent": label, "style": "message"}
                 for i, (split, text, label) in enumerate(examples)],
    }

    def normalize(text):
        return re.sub(r"[^\w ]", "", text.lower())

    groups, dropped = prepare(review, {}, {"câu đã có"}, normalize)
    assert {group: [row["sample"] for row in rows] for group, rows in groups.items()} == {
        "train": ["0"], "holdout": ["1"],
    }
    assert sum(dropped.values()) == 3
    with pytest.raises(ValueError, match="cannot change split"):
        prepare(review, {"train": "holdout"}, set(), normalize)
