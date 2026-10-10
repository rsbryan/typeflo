#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p artifacts
uv run --no-sync dictate --download-models
say -v Samantha -r 165 -o artifacts/bench.wav \
  --file-format=WAVE --data-format=LEI16@16000 \
  'Um, please schedule the meeting at two, actually three PM tomorrow. We need to review the budget, discuss the timeline, and send the notes to Sarah.'
uv run --no-sync dictate --bench artifacts/bench.wav --runs 3 2>&1 | tee artifacts/benchmark.log
