"""Small synthetic smoke comparison; not a human-speech accuracy benchmark.

Run in the app container after starting the optional whisper-cpp service:
    python backend/tools/compare_speech_engines.py
"""
import json
import re
import statistics
import time
import unicodedata

from app.voice import transcription, whisper_cpp
from app.voice.synthesis import text_to_speech

SENTENCES = [
    "Alo, tôi đang nghe đây.",
    "Tôi không cung cấp mã xác thực cho người lạ.",
    "Tôi sẽ tự gọi tổng đài để kiểm tra thông tin.",
    "Bạn có thể cho tôi biết tên đơn vị được không?",
    "Tôi chưa chuyển tiền và cũng không bấm vào đường link.",
    "Để tôi xem lại, tôi chưa đồng ý làm theo.",
]


def tokens(text):
    return re.sub(r"[^\w\s]", " ", unicodedata.normalize("NFC", text.lower())).split()


def edit_distance(a, b):
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        next_row = [i]
        for j, y in enumerate(b, 1):
            next_row.append(min(next_row[-1] + 1, row[j] + 1, row[j - 1] + (x != y)))
        row = next_row
    return row[-1]


def main():
    clips = [(text, whisper_cpp.normalize_audio(text_to_speech(text, "quang-huy"))) for text in SENTENCES]
    engines = {"faster_whisper_int8": transcription._faster_whisper, "whisper_cpp_q8": whisper_cpp.transcribe}
    for decode in engines.values():
        decode(clips[0][1])  # Exclude model initialization/warm-up from timing.
    rows = []
    for repeat in range(2):
        for i, (expected, audio) in enumerate(clips):
            order = list(engines)
            if (i + repeat) % 2:
                order.reverse()
            for name in order:
                started = time.monotonic()
                actual = engines[name](audio)
                row = dict(engine=name, repeat=repeat, expected=expected, actual=actual,
                           elapsed_s=round(time.monotonic() - started, 3),
                           edits=edit_distance(tokens(expected), tokens(actual)), words=len(tokens(expected)))
                rows.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
    for name in engines:
        selected = [row for row in rows if row["engine"] == name]
        print(json.dumps(dict(summary=name, n=len(selected),
                              median_s=statistics.median(row["elapsed_s"] for row in selected),
                              synthetic_wer=sum(row["edits"] for row in selected) / sum(row["words"] for row in selected))), flush=True)


if __name__ == "__main__":
    main()
