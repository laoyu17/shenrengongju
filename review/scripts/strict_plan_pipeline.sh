#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ $# -lt 1 ]]; then
  echo "usage: bash review/scripts/strict_plan_pipeline.sh <config.yaml> [out_dir]" >&2
  exit 1
fi

CONFIG_PATH="$1"
OUT_DIR="${2:-review/runtime/i2/strict_plan_pipeline}"
PLANNER="${PLANNER:-np_edf}"

if [[ ! -f "$CONFIG_PATH" ]]; then
  echo "[ERROR] config not found: $CONFIG_PATH" >&2
  exit 1
fi

mkdir -p "$OUT_DIR/logs"
RESULT_TSV="${OUT_DIR}/results.tsv"
# Recreate TSV file to avoid sparse/NUL-prefixed leftovers on shared filesystems.
rm -f "$RESULT_TSV"
printf 'id\tlabel\trc\tlog\n' > "$RESULT_TSV"

PLAN_JSON="${OUT_DIR}/plan.json"
PLAN_CSV="${OUT_DIR}/plan.csv"
WCRT_JSON="${OUT_DIR}/wcrt.json"
WCRT_CSV="${OUT_DIR}/wcrt.csv"
OS_JSON="${OUT_DIR}/os_config.json"
OS_CSV="${OUT_DIR}/os_config.csv"

FAIL_COUNT=0

run_step() {
  local id="$1"
  local label="$2"
  shift 2
  local log="${OUT_DIR}/logs/${id}_${label}.log"
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

run_step 01 plan_static python -m rtos_sim.cli.main plan-static \
  -c "$CONFIG_PATH" \
  --planner "$PLANNER" \
  --out-json "$PLAN_JSON" \
  --out-csv "$PLAN_CSV"

run_step 02 analyze_wcrt_strict python -m rtos_sim.cli.main analyze-wcrt \
  -c "$CONFIG_PATH" \
  --plan-json "$PLAN_JSON" \
  --strict-plan-match \
  --out-json "$WCRT_JSON" \
  --out-csv "$WCRT_CSV"

run_step 03 export_os_strict python -m rtos_sim.cli.main export-os-config \
  -c "$CONFIG_PATH" \
  --plan-json "$PLAN_JSON" \
  --strict-plan-match \
  --out-json "$OS_JSON" \
  --out-csv "$OS_CSV"

if [[ $FAIL_COUNT -ne 0 ]]; then
  echo "[ERROR] strict plan pipeline failed, fail_count=${FAIL_COUNT}" >&2
  echo "[ERROR] details: ${RESULT_TSV}" >&2
  exit 1
fi

echo "[OK] strict plan pipeline passed"
echo "[OK] results=${RESULT_TSV}"
echo "[OK] outputs=${OUT_DIR}"
