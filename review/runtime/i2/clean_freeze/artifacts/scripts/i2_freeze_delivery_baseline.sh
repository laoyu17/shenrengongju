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

normalize_bash_path() {
  local path_value="$1"
  if [[ -z "$path_value" ]]; then
    return 1
  fi
  if command -v cygpath >/dev/null 2>&1 && [[ "$path_value" =~ ^[A-Za-z]:[\\/].* ]]; then
    cygpath -u "$path_value"
    return 0
  fi
  printf '%s\n' "$path_value"
}

is_windows_bash() {
  case "${OSTYPE:-}" in
    msys*|cygwin*|win32*)
      return 0
      ;;
  esac

  if [[ -n "${MSYSTEM:-}" ]]; then
    return 0
  fi

  if command -v cygpath >/dev/null 2>&1; then
    return 0
  fi

  case "$(uname -s 2>/dev/null || true)" in
    MSYS*|MINGW*|CYGWIN*)
      return 0
      ;;
  esac

  return 1
}

resolve_python_repro_cmd() {
  local candidate=""
  local base_dir=""

  if [[ -n "${PYTHON_BIN:-}" ]]; then
    if candidate="$(normalize_bash_path "$PYTHON_BIN" 2>/dev/null)"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  fi

  if [[ -n "${pythonLocation:-}" ]]; then
    if base_dir="$(normalize_bash_path "$pythonLocation" 2>/dev/null)"; then
      candidate="${base_dir%/}/python"
      if [[ -f "${candidate}.exe" ]]; then
        candidate="${candidate}.exe"
      fi
      printf '%s\n' "$candidate"
      return 0
    fi
  fi

  if is_windows_bash && command -v py >/dev/null 2>&1; then
    printf 'py -3\n'
    return 0
  fi

  if command -v python3 >/dev/null 2>&1; then
    printf 'python3\n'
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    printf 'python\n'
    return 0
  fi
  if command -v py >/dev/null 2>&1; then
    printf 'py -3\n'
    return 0
  fi

  printf 'python\n'
}

json_escape() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

compute_sha256() {
  local target_file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$target_file" | awk '{print $1}'
    return 0
  fi
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$target_file" | awk '{print $1}'
    return 0
  fi
  if command -v openssl >/dev/null 2>&1; then
    openssl dgst -sha256 "$target_file" | awk '{print $2}'
    return 0
  fi
  echo "[ERROR] no SHA-256 tool found for manifest generation" >&2
  exit 127
}

file_size_bytes() {
  wc -c < "$1" | tr -d ' '
}

write_snapshot_meta() {
  local formal_freeze_json="false"
  local dirty_workspace_json="false"
  local allow_dirty_json="false"

  if [[ "$FREEZE_KIND" == "clean_formal" ]]; then
    formal_freeze_json="true"
  fi
  if [[ "$DIRTY_WORKSPACE" == true ]]; then
    dirty_workspace_json="true"
  fi
  if [[ "$ALLOW_DIRTY_FREEZE" == "1" ]]; then
    allow_dirty_json="true"
  fi

  cat > "${OUT_DIR}/snapshot_meta.json" <<EOF_JSON
{
  "snapshot_id": "$(json_escape "$SNAPSHOT_ID")",
  "generated_at_utc": "$(json_escape "$TIMESTAMP_UTC")",
  "head_commit": "$(json_escape "$HEAD_COMMIT")",
  "tag_name": "$(json_escape "$TAG_NAME")",
  "tag_status": "$(json_escape "$TAG_STATUS")",
  "freeze_kind": "$(json_escape "$FREEZE_KIND")",
  "formal_freeze": ${formal_freeze_json},
  "allow_dirty_freeze": ${allow_dirty_json},
  "changed_file_count": ${CHANGED_COUNT},
  "dirty_workspace": ${dirty_workspace_json},
  "paths": {
    "change_list": "$(json_escape "${OUT_DIR}/change_list")",
    "artifacts": "$(json_escape "${OUT_DIR}/artifacts")",
    "reproduce_commands": "$(json_escape "${OUT_DIR}/reproduce_commands.txt")"
  }
}
EOF_JSON
}

write_manifest() {
  local manifest_tmp="${OUT_DIR}/manifest.tsv.tmp"
  local file_path=""
  local digest=""
  local size=""
  local rel_path=""

  printf 'sha256\tsize\tpath\n' > "$manifest_tmp"
  while IFS= read -r file_path; do
    digest="$(compute_sha256 "$file_path")"
    size="$(file_size_bytes "$file_path")"
    rel_path="${file_path#${OUT_DIR}/}"
    printf '%s\t%s\t%s\n' "$digest" "$size" "$rel_path" >> "$manifest_tmp"
  done < <(find "$OUT_DIR" -type f ! -name 'manifest.tsv' ! -name 'manifest.tsv.tmp' | LC_ALL=C sort)

  mv "$manifest_tmp" "${OUT_DIR}/manifest.tsv"
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

PYTHON_REPRO_CMD="$(resolve_python_repro_cmd)"

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

cat > "${OUT_DIR}/reproduce_commands.txt" <<EOF_REPRO
${PYTHON_REPRO_CMD} -m pytest -q
bash review/scripts/i1_freeze_sched_rate_gate.sh
bash review/scripts/i1_ci_gate.sh
QUALITY_SNAPSHOT_SOURCE=${QUALITY_SNAPSHOT_SOURCE} bash review/scripts/i2_freeze_delivery_baseline.sh ${OUT_DIR}
EOF_REPRO

cat > "${OUT_DIR}/tag.txt" <<EOF_TAG
freeze_kind=${FREEZE_KIND}
tag_name=${TAG_NAME}
tag_status=${TAG_STATUS}
head_commit=${HEAD_COMMIT}
snapshot_id=${SNAPSHOT_ID}
EOF_TAG

write_snapshot_meta
write_manifest

echo "[OK] baseline freeze snapshot generated"
echo "[OK] out_dir=${OUT_DIR}"
echo "[OK] freeze_kind=${FREEZE_KIND}"
echo "[OK] tag=${TAG_NAME} (${TAG_STATUS})"
echo "[OK] changed_file_count=${CHANGED_COUNT}"
