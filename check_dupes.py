"""Loại câu trùng giữa nlu_extra.yml và nlu.yml hiện có.
Chạy trong thư mục dự án:
    python check_dupes.py rasa/data/nlu.yml rasa/data/nlu_extra.yml
Ghi đè nlu_extra.yml đã bỏ câu trùng (có tạo bản sao .bak) và in thống kê.
"""
import re, sys, shutil, unicodedata
from collections import Counter

def norm(s):
    s = unicodedata.normalize("NFD", s.lower().replace("đ", "d"))
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def read_examples(path):
    intent, rows = None, []
    for line in open(path, encoding="utf-8"):
        m = re.match(r"\s*-\s*intent:\s*(\S+)", line)
        if m:
            intent = m.group(1); continue
        m = re.match(r"\s{2,}-\s+(.*\S)\s*$", line)
        if m and intent:
            rows.append((intent, m.group(1)))
    return rows

base_path, extra_path = sys.argv[1], sys.argv[2]
base = {norm(t) for _, t in read_examples(base_path)}
shutil.copy(extra_path, extra_path + ".bak")

kept, removed, seen = [], Counter(), set()
for intent, text in read_examples(extra_path):
    k = norm(text)
    if k in base or k in seen:
        removed[intent] += 1
        continue
    seen.add(k); kept.append((intent, text))

out, cur = ['version: "3.1"', "", "nlu:"], None
for intent, text in kept:
    if intent != cur:
        if cur: out.append("")
        out += [f"- intent: {intent}", "  examples: |"]
        cur = intent
    out.append(f"    - {text}")
open(extra_path, "w", encoding="utf-8").write("\n".join(out) + "\n")

print("Còn lại:", dict(Counter(i for i, _ in kept)))
print("Đã loại do trùng:", dict(removed) or "không có")
