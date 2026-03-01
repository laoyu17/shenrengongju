"""Validate documentation baseline fields against the quality snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

QUALITY_SNAPSHOT_PATH = "artifacts/quality/quality-snapshot.json"
GIT_SHA_PATTERN = re.compile(r"git_sha=([0-9a-f]{40})")


class DocCheck(tuple[str, tuple[str, ...], tuple[str, ...]]):
    __slots__ = ()

    def __new__(
        cls,
        relative_path: str,
        required_substrings: tuple[str, ...],
        forbidden_substrings: tuple[str, ...] = (),
    ) -> "DocCheck":
        return tuple.__new__(cls, (relative_path, required_substrings, forbidden_substrings))

    @property
    def relative_path(self) -> str:
        return self[0]

    @property
    def required_substrings(self) -> tuple[str, ...]:
        return self[1]

    @property
    def forbidden_substrings(self) -> tuple[str, ...]:
        return self[2]


def _load_snapshot(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"snapshot payload must be JSON object: {path}")

    git_sha = str(payload.get("git_sha") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", git_sha):
        raise ValueError(f"snapshot git_sha invalid: {git_sha!r}")

    pytest_block = payload.get("pytest")
    coverage_block = payload.get("coverage")
    if not isinstance(pytest_block, dict) or not isinstance(coverage_block, dict):
        raise ValueError("snapshot missing pytest/coverage sections")

    passed = pytest_block.get("passed")
    line_rate = coverage_block.get("line_rate")
    if not isinstance(passed, int):
        raise ValueError("snapshot pytest.passed must be integer")
    if not isinstance(line_rate, (int, float)):
        raise ValueError("snapshot coverage.line_rate must be number")

    return payload


def _coverage_percent(snapshot: dict[str, Any]) -> str:
    return f"{float(snapshot['coverage']['line_rate']):.2f}%"


def build_doc_checks(snapshot: dict[str, Any]) -> list[DocCheck]:
    sha = str(snapshot["git_sha"])
    passed = int(snapshot["pytest"]["passed"])
    line_rate = float(snapshot["coverage"]["line_rate"])
    coverage_percent = _coverage_percent(snapshot)

    return [
        DocCheck(
            relative_path="10-详细设计说明书.md",
            required_substrings=(
                f"git_sha={sha}",
                QUALITY_SNAPSHOT_PATH,
            ),
        ),
        DocCheck(
            relative_path="11-实施现状问题与Sprint规划.md",
            required_substrings=(
                f"git_sha={sha}",
                f"{passed} passed",
                coverage_percent,
                QUALITY_SNAPSHOT_PATH,
            ),
        ),
        DocCheck(
            relative_path="14-docx需求追踪矩阵.md",
            required_substrings=(
                f"git_sha={sha}",
                QUALITY_SNAPSHOT_PATH,
            ),
        ),
        DocCheck(
            relative_path="15-研究闭环验收基线.md",
            required_substrings=(
                f"git_sha={sha}",
                f"pytest={passed} passed",
                f"coverage={coverage_percent}",
                QUALITY_SNAPSHOT_PATH,
            ),
        ),
        DocCheck(
            relative_path="18-综合审查报告-2026-02-24.md",
            required_substrings=(
                f"git_sha={sha}",
                f"{passed} passed",
                f"line_rate={line_rate}",
                coverage_percent,
                QUALITY_SNAPSHOT_PATH,
            ),
        ),
        DocCheck(
            relative_path="19-用户使用说明书.md",
            required_substrings=(
                f"git_sha={sha}",
                f"pytest={passed} passed",
                f"coverage={coverage_percent}",
                QUALITY_SNAPSHOT_PATH,
            ),
        ),
        DocCheck(
            relative_path="20-审查问题台账.csv",
            required_substrings=(
                "id,severity,confidence,module,description,evidence_path,evidence_line,impact,repro_steps,suggested_fix,status",
                f"git_sha={sha}",
                QUALITY_SNAPSHOT_PATH,
            ),
        ),
        DocCheck(
            relative_path="21-全量基线一致性校验记录-2026-02-24.md",
            required_substrings=(
                f"git_sha={sha}",
                f"pytest={passed} passed",
                f"coverage={coverage_percent}",
                QUALITY_SNAPSHOT_PATH,
            ),
        ),
        DocCheck(
            relative_path="../README.md",
            required_substrings=(
                "docs/15-研究闭环验收基线.md",
                "docs/20-审查问题台账.csv",
                "python scripts/check_doc_baseline_consistency.py",
                QUALITY_SNAPSHOT_PATH,
            ),
        ),
    ]


def _validate_doc(path: Path, check: DocCheck, expected_sha: str) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        return [f"{path}: file not found"]

    text = path.read_text(encoding="utf-8")
    for token in check.required_substrings:
        if token not in text:
            errors.append(f"{path}: missing required token: {token}")

    for token in check.forbidden_substrings:
        if token in text:
            errors.append(f"{path}: found forbidden token: {token}")

    sha_values = set(GIT_SHA_PATTERN.findall(text))
    for found in sorted(sha_values):
        if found != expected_sha:
            errors.append(f"{path}: git_sha mismatch: expected {expected_sha}, found {found}")

    return errors


def run_consistency_check(snapshot_path: Path, docs_root: Path) -> list[str]:
    snapshot = _load_snapshot(snapshot_path)
    checks = build_doc_checks(snapshot)
    expected_sha = str(snapshot["git_sha"])

    errors: list[str] = []
    for check in checks:
        errors.extend(_validate_doc(docs_root / check.relative_path, check, expected_sha))
    return errors


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check docs baseline fields against quality snapshot")
    parser.add_argument(
        "--snapshot",
        default=QUALITY_SNAPSHOT_PATH,
        help="quality snapshot json path",
    )
    parser.add_argument(
        "--docs-root",
        default="docs",
        help="docs directory root",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    snapshot_path = Path(args.snapshot)
    docs_root = Path(args.docs_root)

    try:
        errors = run_consistency_check(snapshot_path=snapshot_path, docs_root=docs_root)
    except Exception as exc:  # pragma: no cover - CLI safeguard
        print(f"[FAIL] {exc}")
        return 2

    if errors:
        print("[FAIL] docs baseline consistency check failed")
        for error in errors:
            print(f" - {error}")
        return 1

    print(f"[OK] docs baseline consistency check passed ({snapshot_path})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
