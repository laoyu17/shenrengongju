#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

FREEZE_OUT_DIR="${1:-review/runtime/i2/clean_freeze}"
GATE_OUT_DIR="${2:-artifacts/quality/clean_freeze_gate}"
QUALITY_SNAPSHOT_PATH="${3:-artifacts/quality/quality-snapshot.json}"

cat <<EOF
[INFO] i2_refresh_formal_freeze.sh
- prerequisite: current HEAD must already be the checkpoint commit you want to freeze
- step 1/3: run clean freeze gate and refresh first-class evidence
- step 2/3: verify doc references after evidence refresh
- step 3/3: review docs/review diff and archive evidence in a separate commit if needed
EOF

bash review/scripts/i2_clean_freeze_gate.sh "$GATE_OUT_DIR" "$FREEZE_OUT_DIR"
python scripts/check_doc_reference_integrity.py --repo-root .

cat <<EOF
[OK] formal freeze refresh workflow completed
- freeze_fact_source: ${FREEZE_OUT_DIR}/snapshot_meta.json
- quality_fact_source: ${QUALITY_SNAPSHOT_PATH}
- next_step: review docs/review diff and archive evidence in a dedicated commit before push
- note: review/06 remains a process record; final freeze arbitration uses the two fact sources above
EOF
