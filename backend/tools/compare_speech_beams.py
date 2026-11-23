"""Paired beam comparison. Synthetic by default; --manifest accepts consented recordings.

Manifest: JSON array of {"audio": "relative.wav", "text": "reference", "speaker": "id"}.
Run outside live traffic; this tool consumes the same CPU as speech requests.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import time

from app.voice import transcription
from tools.compare_speech_engines import tokens, edit_distance

SAMPLES = [
    "Alo, tôi đang nghe đây.",
    "Tôi không cung cấp mã xác thực cho người lạ.",
    "Tôi sẽ tự gọi tổng đài để kiểm tra thông tin.",
    "Bạn có thể cho tôi biết tên đơn vị được không?",
    "Tôi chưa chuyển tiền và cũng không bấm vào đường link.",
    "Để tôi xem lại, tôi chưa đồng ý làm theo.",
    "Tôi sẽ làm theo hướng dẫn.",
    "Không, tôi sẽ không làm theo hướng dẫn.",
    "Tôi chưa nhận được mã xác thực.",
    "Tôi muốn kết thúc cuộc gọi này.",
    "Để tôi hỏi người nhà trước đã.",
    "Tôi nghi ngờ đây là một cuộc gọi lừa đảo.",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repeats", type=int, default=2)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be positive")
    if args.manifest:
        samples = json.loads(args.manifest.read_text(encoding="utf-8"))
        clips = [(row["text"], (args.manifest.parent / row["audio"]).read_bytes(), row["speaker"]) for row in samples]
        dataset = "provided-recordings"
    else:
        from app.voice.synthesis import text_to_speech
        voices = ["ngoc-lan", "minh-anh", "quang-huy"]
        clips = [(text, text_to_speech(text, voices[i % 3]), voices[i % 3]) for i, text in enumerate(SAMPLES)]
        dataset = "synthetic-piper-12-phrases-3-voices"
    if not clips:
        parser.error("empty dataset")
    for beam in (5, 3, 1):
        transcription._faster_whisper(clips[0][1], beam_size=beam)
    rows = []
    for repeat in range(args.repeats):
        for i, (expected, audio, speaker) in enumerate(clips):
            order = [5, 3, 1]
            shift = (repeat + i) % 3
            for beam in order[shift:] + order[:shift]:
                started = time.perf_counter()
                actual = transcription._faster_whisper(audio, beam_size=beam)
                rows.append(dict(beam=beam, repeat=repeat, sample=i, speaker=speaker,
                                 expected=expected, actual=actual,
                                 elapsed_s=round(time.perf_counter() - started, 4),
                                 edits=edit_distance(tokens(expected), tokens(actual)), words=len(tokens(expected))))
    summary = []
    for beam in (5, 3, 1):
        selected = [row for row in rows if row["beam"] == beam]
        times = sorted(row["elapsed_s"] for row in selected)
        summary.append(dict(beam=beam, runs=len(selected), median_s=statistics.median(times),
                            max_s=max(times), edits=sum(row["edits"] for row in selected),
                            words=sum(row["words"] for row in selected)))
    report = dict(dataset=dataset, model=os.getenv("WHISPER_MODEL", "base"),
                  compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8"), cpu_threads=2,
                  repeats=args.repeats, distinct_clips=len(clips), summary=summary, rows=rows)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"dataset": dataset, "summary": summary}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
