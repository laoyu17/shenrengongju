#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

OUT_DIR="${1:-review/runtime/i1/sched_rate_gate}"
TARGET_UPLIFT="${TARGET_UPLIFT:-0.30}"
BASELINE="np_edf"
CANDIDATES="np_dm,precautious_dm,lp"
TASK_SCOPE="sync_only"
CONFIG_LIST="review/frozen/sched_rate/config-list.txt"

mkdir -p "$OUT_DIR"
RESULT_JSON="$OUT_DIR/benchmark_frozen.json"
RESULT_CSV="$OUT_DIR/benchmark_frozen.csv"
SUMMARY_TXT="$OUT_DIR/summary.txt"

if [[ ! -f "$CONFIG_LIST" ]]; then
  echo "[ERROR] frozen config-list not found: $CONFIG_LIST" >&2
  exit 1
fi

while IFS= read -r cfg; do
  [[ -z "$cfg" ]] && continue
  if [[ ! -f "$cfg" ]]; then
    echo "[ERROR] config listed but missing: $cfg" >&2
    exit 1
  fi
done < "$CONFIG_LIST"

python -m rtos_sim.cli.main benchmark-sched-rate \
  --config-list "$CONFIG_LIST" \
  --baseline "$BASELINE" \
  --candidates "$CANDIDATES" \
  --task-scope "$TASK_SCOPE" \
  --target-uplift "$TARGET_UPLIFT" \
  --out-json "$RESULT_JSON" \
  --out-csv "$RESULT_CSV"

python - <<'PY' "$RESULT_JSON" "$SUMMARY_TXT" "$TARGET_UPLIFT" "$CONFIG_LIST"
from __future__ import annotations
import json
from pathlib import Path
import sys

result_json = Path(sys.argv[1])
summary_txt = Path(sys.argv[2])
target = float(sys.argv[3])
config_list = Path(sys.argv[4])

payload = json.loads(result_json.read_text(encoding='utf-8'))
required = [
    'candidate_only_uplift',
    'candidate_only_schedulable_rate',
    'baseline_schedulable_rate',
    'total_cases',
]
missing = [k for k in required if k not in payload]
if missing:
    raise SystemExit(f"missing keys in benchmark report: {missing}")

actual = float(payload['candidate_only_uplift'])
rate = float(payload['candidate_only_schedulable_rate'])
baseline_rate = float(payload['baseline_schedulable_rate'])
total_cases = int(payload['total_cases'])
count = len([line for line in config_list.read_text(encoding='utf-8').splitlines() if line.strip()])
if total_cases != count:
    raise SystemExit(
        f"total_cases mismatch: report={total_cases}, config_list={count}"
    )

gate_pass = actual >= target
summary_txt.write_text(
    "\n".join(
        [
            f"config_list={config_list}",
            "gate_metric=candidate_only_uplift",
            f"target={target}",
            f"actual={actual}",
            f"baseline_schedulable_rate={baseline_rate}",
            f"candidate_only_schedulable_rate={rate}",
            f"total_cases={total_cases}",
            f"gate_pass={str(gate_pass).lower()}",
        ]
    ) + "\n",
    encoding='utf-8',
)
if not gate_pass:
    raise SystemExit(
        f"candidate_only_uplift gate failed: target={target}, actual={actual}"
    )
PY

echo "[OK] I1-1 frozen uplift gate passed"
echo "[OK] outputs: json=$RESULT_JSON csv=$RESULT_CSV summary=$SUMMARY_TXT"
