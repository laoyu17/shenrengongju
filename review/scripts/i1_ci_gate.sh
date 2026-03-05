#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

OUT_DIR="${1:-review/runtime/i1/ci_gate}"
mkdir -p "$OUT_DIR/logs" "$OUT_DIR/artifacts"
RESULT_TSV="$OUT_DIR/results.tsv"
# Recreate the TSV file to avoid sparse/NUL-prefixed leftovers on shared filesystems.
rm -f "$RESULT_TSV"
printf 'id\tlabel\trc\tlog\n' > "$RESULT_TSV"

FAIL_COUNT=0

run_step() {
  local id="$1"
  local label="$2"
  shift 2
  local log="$OUT_DIR/logs/${id}_${label}.log"
  set +e
  "$@" >"$log" 2>&1
  local rc=$?
  set -e
  printf '%s\t%s\t%s\t%s\n' "$id" "$label" "$rc" "$log" >> "$RESULT_TSV"
  if [[ $rc -ne 0 ]]; then
    echo "[FAIL] step=${label}, rc=${rc}, log=${log}" >&2
    FAIL_COUNT=$((FAIL_COUNT + 1))
  else
    echo "[OK] step=${label}" >&2
  fi
}

run_step 01 pytest python -m pytest -q
run_step 02 validate_at01 python -m rtos_sim.cli.main validate -c examples/at01_single_dag_single_core.yaml
run_step 03 run_at01 python -m rtos_sim.cli.main run -c examples/at01_single_dag_single_core.yaml \
  --events-out "$OUT_DIR/artifacts/at01_events.jsonl" \
  --events-csv-out "$OUT_DIR/artifacts/at01_events.csv" \
  --metrics-out "$OUT_DIR/artifacts/at01_metrics.json"
run_step 04 inspect_at01_strict python -m rtos_sim.cli.main inspect-model -c examples/at01_single_dag_single_core.yaml --strict-on-fail \
  --out-json "$OUT_DIR/artifacts/at01_relations.json" \
  --out-csv "$OUT_DIR/artifacts/at01_relations.csv"

run_step 05 inspect_at01_at10_strict bash -lc "set -euo pipefail; cd '$ROOT_DIR'; for f in examples/at0{1..9}_*.yaml examples/at10_*.yaml; do python -m rtos_sim.cli.main inspect-model -c \"\$f\" --strict-on-fail >/dev/null; done"

run_step 06 plan_at06 python -m rtos_sim.cli.main plan-static -c examples/at06_time_deterministic.yaml \
  --planner np_edf \
  --out-json "$OUT_DIR/artifacts/at06_plan.json" \
  --out-csv "$OUT_DIR/artifacts/at06_plan.csv"
run_step 07 wcrt_at06_strict python -m rtos_sim.cli.main analyze-wcrt -c examples/at06_time_deterministic.yaml \
  --plan-json "$OUT_DIR/artifacts/at06_plan.json" \
  --strict-plan-match \
  --out-json "$OUT_DIR/artifacts/at06_wcrt.json" \
  --out-csv "$OUT_DIR/artifacts/at06_wcrt.csv"
run_step 08 export_os_at06_strict python -m rtos_sim.cli.main export-os-config -c examples/at06_time_deterministic.yaml \
  --plan-json "$OUT_DIR/artifacts/at06_plan.json" \
  --strict-plan-match \
  --out-json "$OUT_DIR/artifacts/at06_os.json" \
  --out-csv "$OUT_DIR/artifacts/at06_os.csv"

run_step 09 frozen_sched_rate_gate bash "$ROOT_DIR/review/scripts/i1_freeze_sched_rate_gate.sh" "$OUT_DIR/artifacts/sched_rate_gate"

if [[ $FAIL_COUNT -ne 0 ]]; then
  echo "[ERROR] I1-2 CI gate failed, fail_count=$FAIL_COUNT" >&2
  echo "[ERROR] details: $RESULT_TSV" >&2
  exit 1
fi

echo "[OK] I1-2 CI gate passed"
echo "[OK] results: $RESULT_TSV"
