#!/bin/sh
set -eu
export RASA_TELEMETRY_ENABLED=false

batch=${1:?Pass the path to an exported batch}
if [ -e "$batch/results" ]; then
  echo "Results already exist. Export a new batch to run again." >&2
  exit 1
fi
evaluation_dir=$(CDPATH='' cd "$(dirname "$0")" && pwd)
scratch=$(mktemp -d)
trap 'rm -r "$scratch"' EXIT

# Validate both datasets before running either training job.
PYTHONPATH="$evaluation_dir${PYTHONPATH:+:$PYTHONPATH}" python - "$batch" <<'PY'
from pathlib import Path
import sys

from evaluate import evaluation_rows, speaker_holdout_rows, validate_rows

batch = Path(sys.argv[1])
training = batch / "reviewed_nlu.yml"
if not training.is_file():
    raise SystemExit("Missing reviewed NLU data.")
validate_rows(evaluation_rows(), {"conversation", "asr_like"}, training)
speaker_holdout_rows(batch / "speaker_holdout.json", training)
PY

mkdir "$scratch/data"
cp "$evaluation_dir/../data/nlu.yml" "$scratch/data/nlu.yml"
cp "$batch/reviewed_nlu.yml" "$scratch/data/reviewed_nlu.yml"
sed '/epochs: 100/a\    random_seed: 42' "$evaluation_dir/../config.yml" > "$scratch/config.yml"

rasa train nlu --config "$scratch/config.yml" --nlu "$scratch/data/nlu.yml" --out "$scratch/baseline" --fixed-model-name baseline
rasa train nlu --config "$scratch/config.yml" --nlu "$scratch/data" --out "$scratch/candidate" --fixed-model-name candidate
python "$evaluation_dir/evaluate.py" --baseline "$scratch/baseline" --candidate "$scratch/candidate" \
  --speaker-holdout "$batch/speaker_holdout.json" --candidate-training "$batch/reviewed_nlu.yml" > "$scratch/comparison.txt"

mkdir "$batch/results"
cp "$scratch/baseline/baseline.tar.gz" "$scratch/candidate/candidate.tar.gz" "$scratch/comparison.txt" "$batch/results/"
cat "$batch/results/comparison.txt"
