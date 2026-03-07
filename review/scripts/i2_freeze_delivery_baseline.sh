#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

OUT_DIR="${1:-review/runtime/i2/baseline_freeze}"
TIMESTAMP_UTC="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
STAMP="$(date -u +"%Y%m%d-%H%M%S")"
TAG_NAME="${BASELINE_TAG:-delivery-baseline-${STAMP}}"
ALLOW_DIRTY_FREEZE="${ALLOW_DIRTY_FREEZE:-0}"
QUALITY_SNAPSHOT_SOURCE="${QUALITY_SNAPSHOT_SOURCE:-artifacts/quality/quality-snapshot.json}"

declare -a PYTHON_CMD=()
PYTHON_REPRO_CMD="python"

resolve_python_cmd() {
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    if "$PYTHON_BIN" -c "import sys" >/dev/null 2>&1; then
      PYTHON_CMD=("$PYTHON_BIN")
      PYTHON_REPRO_CMD="$PYTHON_BIN"
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
    if [[ -f "$candidate" ]] && "$candidate" -c "import sys" >/dev/null 2>&1; then
      PYTHON_CMD=("$candidate")
      PYTHON_REPRO_CMD="$candidate"
      return 0
    fi
  fi

  if command -v python3 >/dev/null 2>&1 && python3 -c "import sys" >/dev/null 2>&1; then
    PYTHON_CMD=(python3)
    PYTHON_REPRO_CMD="python3"
    return 0
  fi

  if command -v py >/dev/null 2>&1 && py -3 -c "import sys" >/dev/null 2>&1; then
    PYTHON_CMD=(py -3)
    PYTHON_REPRO_CMD="py -3"
    return 0
  fi

  if command -v python >/dev/null 2>&1 && python -c "import sys" >/dev/null 2>&1; then
    PYTHON_CMD=(python)
    PYTHON_REPRO_CMD="python"
    return 0
  fi

  if command -v py >/dev/null 2>&1 && py -c "import sys" >/dev/null 2>&1; then
    PYTHON_CMD=(py)
    PYTHON_REPRO_CMD="py"
    return 0
  fi

  echo "[ERROR] no usable Python interpreter found; set PYTHON_BIN explicitly" >&2
  exit 127
}

CHANGE_DIR="${OUT_DIR}/change_list"
ARTIFACT_DIR="${OUT_DIR}/artifacts"

HEAD_COMMIT="$(git rev-parse HEAD)"
GIT_STATUS_SHORT="$(git status --short)"
GIT_DIFF_STAT="$(git diff --stat)"
GIT_DIFF_NAME_STATUS="$(git diff --name-status)"
CHANGED_COUNT="$(printf '%s\n' "$GIT_STATUS_SHORT" | sed '/^$/d' | wc -l | tr -d ' ')"
DIRTY_WORKSPACE=false
FREEZE_KIND="clean_formal"
SNAPSHOT_ID="baseline-freeze-${STAMP}"

if [[ "$CHANGED_COUNT" != "0" ]]; then
  DIRTY_WORKSPACE=true
  if [[ "$ALLOW_DIRTY_FREEZE" != "1" ]]; then
    echo "[ERROR] baseline freeze requires clean workspace, changed_file_count=${CHANGED_COUNT}" >&2
    echo "[ERROR] use ALLOW_DIRTY_FREEZE=1 only for historical dirty evidence snapshots" >&2
    exit 2
  fi
  FREEZE_KIND="dirty_evidence"
  SNAPSHOT_ID="baseline-dirty-evidence-${STAMP}"
fi

resolve_python_cmd

mkdir -p "$CHANGE_DIR" "$ARTIFACT_DIR"
printf '%s\n' "$GIT_STATUS_SHORT" > "${CHANGE_DIR}/git_status_short.txt"
printf '%s\n' "$GIT_DIFF_STAT" > "${CHANGE_DIR}/git_diff_stat.txt"
printf '%s\n' "$GIT_DIFF_NAME_STATUS" > "${CHANGE_DIR}/git_diff_name_status.txt"

TAG_STATUS="not_created"
if [[ "$DIRTY_WORKSPACE" == true ]]; then
  TAG_STATUS="skipped_dirty_evidence"
else
  if git rev-parse -q --verify "refs/tags/${TAG_NAME}" >/dev/null; then
    TAG_STATUS="exists"
  else
    if git tag "${TAG_NAME}" "${HEAD_COMMIT}" >/dev/null 2>&1; then
      TAG_STATUS="created"
    else
      TAG_STATUS="failed"
    fi
  fi
fi

copy_artifact() {
  local src="$1"
  local rel="$2"
  local dst="${ARTIFACT_DIR}/${rel}"
  if [[ -f "$src" ]]; then
    mkdir -p "$(dirname "$dst")"
    cp "$src" "$dst"
    echo "[OK] snapshot include: ${src} -> ${dst}"
  else
    echo "[WARN] snapshot source missing: ${src}" >&2
  fi
}

copy_artifact "review/runtime/runtime_evidence.json" "runtime/runtime_evidence.json"
copy_artifact "review/runtime/command_results.tsv" "runtime/command_results.tsv"
copy_artifact "review/runtime/i1/ci_gate/results.tsv" "runtime/i1/ci_gate/results.tsv"
copy_artifact "review/runtime/i1/sched_rate_gate/summary.txt" "runtime/i1/sched_rate_gate/summary.txt"
copy_artifact "$QUALITY_SNAPSHOT_SOURCE" "quality/quality-snapshot.json"
copy_artifact "review/03-问题台账.csv" "review/03-问题台账.csv"
copy_artifact "review/06-收口执行记录.md" "review/06-收口执行记录.md"
copy_artifact "review/scripts/i1_ci_gate.sh" "scripts/i1_ci_gate.sh"
copy_artifact "review/scripts/i1_freeze_sched_rate_gate.sh" "scripts/i1_freeze_sched_rate_gate.sh"
copy_artifact "review/scripts/i2_freeze_delivery_baseline.sh" "scripts/i2_freeze_delivery_baseline.sh"
copy_artifact "review/scripts/strict_plan_pipeline.sh" "scripts/strict_plan_pipeline.sh"
copy_artifact ".github/workflows/ci.yml" "ci/ci.yml"

cat > "${OUT_DIR}/reproduce_commands.txt" <<EOF2
${PYTHON_REPRO_CMD} -m pytest -q
bash review/scripts/i1_freeze_sched_rate_gate.sh
bash review/scripts/i1_ci_gate.sh
QUALITY_SNAPSHOT_SOURCE=${QUALITY_SNAPSHOT_SOURCE} bash review/scripts/i2_freeze_delivery_baseline.sh ${OUT_DIR}
EOF2

cat > "${OUT_DIR}/tag.txt" <<EOF2
freeze_kind=${FREEZE_KIND}
tag_name=${TAG_NAME}
tag_status=${TAG_STATUS}
head_commit=${HEAD_COMMIT}
snapshot_id=${SNAPSHOT_ID}
EOF2

"${PYTHON_CMD[@]}" - "${OUT_DIR}" "${TIMESTAMP_UTC}" "${SNAPSHOT_ID}" "${HEAD_COMMIT}" "${TAG_NAME}" "${TAG_STATUS}" "${CHANGED_COUNT}" "${FREEZE_KIND}" "${ALLOW_DIRTY_FREEZE}" <<'PY'
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

out_dir = Path(sys.argv[1])
timestamp_utc = sys.argv[2]
snapshot_id = sys.argv[3]
head_commit = sys.argv[4]
tag_name = sys.argv[5]
tag_status = sys.argv[6]
changed_count = int(sys.argv[7])
freeze_kind = sys.argv[8]
allow_dirty_freeze = sys.argv[9] == "1"

meta = {
    "snapshot_id": snapshot_id,
    "generated_at_utc": timestamp_utc,
    "head_commit": head_commit,
    "tag_name": tag_name,
    "tag_status": tag_status,
    "freeze_kind": freeze_kind,
    "formal_freeze": freeze_kind == "clean_formal",
    "allow_dirty_freeze": allow_dirty_freeze,
    "changed_file_count": changed_count,
    "dirty_workspace": changed_count > 0,
    "paths": {
        "change_list": str(out_dir / "change_list"),
        "artifacts": str(out_dir / "artifacts"),
        "reproduce_commands": str(out_dir / "reproduce_commands.txt"),
    },
}
(out_dir / "snapshot_meta.json").write_text(
    json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)

manifest_lines = ["sha256\tsize\tpath"]
for file in sorted(p for p in out_dir.rglob("*") if p.is_file()):
    digest = hashlib.sha256(file.read_bytes()).hexdigest()
    size = file.stat().st_size
    rel = file.relative_to(out_dir).as_posix()
    manifest_lines.append(f"{digest}\t{size}\t{rel}")
(out_dir / "manifest.tsv").write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
PY

echo "[OK] baseline freeze snapshot generated"
echo "[OK] out_dir=${OUT_DIR}"
echo "[OK] freeze_kind=${FREEZE_KIND}"
echo "[OK] tag=${TAG_NAME} (${TAG_STATUS})"
echo "[OK] changed_file_count=${CHANGED_COUNT}"
