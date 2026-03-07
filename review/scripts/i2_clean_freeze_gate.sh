#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

OUT_DIR="${1:-artifacts/quality/clean_freeze_gate}"
FREEZE_OUT_DIR="${2:-review/runtime/i2/clean_freeze}"
mkdir -p "$OUT_DIR/logs" "$OUT_DIR/quality"

RESULT_TSV="$OUT_DIR/results.tsv"
QUALITY_SNAPSHOT_PATH="$OUT_DIR/quality/quality-snapshot.json"
COVERAGE_JSON_PATH="$OUT_DIR/quality/coverage.json"
rm -f "$RESULT_TSV"
printf 'id\tlabel\trc\tlog\n' > "$RESULT_TSV"

FAIL_COUNT=0
FINAL_RC=0

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
    if [[ $FINAL_RC -eq 0 || $rc -gt $FINAL_RC ]]; then
      FINAL_RC=$rc
    fi
  else
    echo "[OK] step=${label}" >&2
  fi
}

run_step 01 pytest_full python -m pytest -q
run_step 02 quality_snapshot python scripts/quality_snapshot.py \
  --output "$QUALITY_SNAPSHOT_PATH" \
  --coverage-json "$COVERAGE_JSON_PATH"
run_step 03 doc_baseline_consistency python scripts/check_doc_baseline_consistency.py \
  --snapshot "$QUALITY_SNAPSHOT_PATH" \
  --docs-root docs \
  --require-evidence-equals-head
run_step 04 clean_workspace bash -lc "set -euo pipefail; cd '$ROOT_DIR'; if [[ -n \"\$(git status --short)\" ]]; then git status --short >&2; exit 2; fi"
run_step 05 freeze_clean env QUALITY_SNAPSHOT_SOURCE="$QUALITY_SNAPSHOT_PATH" \
  bash "$ROOT_DIR/review/scripts/i2_freeze_delivery_baseline.sh" "$FREEZE_OUT_DIR"

if [[ $FAIL_COUNT -ne 0 ]]; then
  echo "[ERROR] clean freeze gate failed, fail_count=${FAIL_COUNT}" >&2
  echo "[ERROR] details: ${RESULT_TSV}" >&2
  exit "$FINAL_RC"
fi

echo "[OK] clean freeze gate passed"
echo "[OK] results=${RESULT_TSV}"
echo "[OK] freeze_out=${FREEZE_OUT_DIR}"
