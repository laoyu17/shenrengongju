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
DOC_BASELINE_SNAPSHOT_PATH="${DOC_BASELINE_SNAPSHOT_PATH:-artifacts/quality/quality-snapshot.json}"
rm -f "$RESULT_TSV"
printf 'id\tlabel\trc\tlog\n' > "$RESULT_TSV"

declare -a PYTHON_CMD=()

python_cmd_supports_stdin() {
  local output
  if ! output="$("$@" - <<'PY' 2>/dev/null
import sys
sys.stdout.write("PYTHON_STDIN_OK")
PY
)"; then
    return 1
  fi
  [[ "$output" == "PYTHON_STDIN_OK" ]]
}

resolve_python_cmd() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    if python_cmd_supports_stdin "$PYTHON_BIN"; then
      PYTHON_CMD=("$PYTHON_BIN")
      return 0
    fi
    echo "[ERROR] PYTHON_BIN is not executable: ${PYTHON_BIN}" >&2
    exit 127
  fi

  if [[ -n "${pythonLocation:-}" ]]; then
    local candidate="${pythonLocation}/python"
    if [[ -f "${candidate}.exe" ]]; then
      candidate="${candidate}.exe"
    fi
    if [[ -f "$candidate" ]] && python_cmd_supports_stdin "$candidate"; then
      PYTHON_CMD=("$candidate")
      return 0
    fi
  fi

  if command -v python3 >/dev/null 2>&1 && python_cmd_supports_stdin python3; then
    PYTHON_CMD=(python3)
    return 0
  fi

  if command -v py >/dev/null 2>&1 && python_cmd_supports_stdin py -3; then
    PYTHON_CMD=(py -3)
    return 0
  fi

  if command -v python >/dev/null 2>&1 && python_cmd_supports_stdin python; then
    PYTHON_CMD=(python)
    return 0
  fi

  if command -v py >/dev/null 2>&1 && python_cmd_supports_stdin py; then
    PYTHON_CMD=(py)
    return 0
  fi

  echo "[ERROR] no usable Python interpreter found; set PYTHON_BIN explicitly" >&2
  exit 127
}

resolve_python_cmd

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

run_step 01 pytest_full "${PYTHON_CMD[@]}" -m pytest -q
run_step 02 quality_snapshot "${PYTHON_CMD[@]}" scripts/quality_snapshot.py \
  --output "$QUALITY_SNAPSHOT_PATH" \
  --coverage-json "$COVERAGE_JSON_PATH"
run_step 03 doc_baseline_consistency "${PYTHON_CMD[@]}" scripts/check_doc_baseline_consistency.py \
  --snapshot "$DOC_BASELINE_SNAPSHOT_PATH" \
  --docs-root docs
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
