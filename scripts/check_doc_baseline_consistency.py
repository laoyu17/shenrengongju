"""Validate documentation baseline fields against the quality snapshot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
from typing import Any

QUALITY_SNAPSHOT_PATH = "artifacts/quality/quality-snapshot.json"
EVIDENCE_GIT_SHA_PATTERN = re.compile(r"evidence_git_sha=([0-9a-f]{40})")
WORKSPACE_GIT_SHA_PATTERN = re.compile(r"workspace_git_sha=([0-9a-f]{40})")
LEGACY_GIT_SHA_PATTERN = re.compile(r"(?<![A-Za-z_])git_sha=([0-9a-f]{40})")
PASSED_PATTERN = re.compile(r"(?<!\d)(\d+)\s+passed")
PASSED_ASSIGNMENT_PATTERN = re.compile(r"(?:pytest\.)?passed\s*[:=]\s*(\d+)", re.IGNORECASE)
ALL_GREEN_CASES_PATTERN = re.compile(r"(?<!\d)(\d+)\s*用例全绿")
COVERAGE_PERCENT_PATTERN = re.compile(r"(?:coverage|覆盖率)[^\n%]{0,32}?([0-9]+(?:\.[0-9]+)?)%", re.IGNORECASE)
COVERAGE_LINE_RATE_PATTERN = re.compile(
    r"(?:coverage\.)?line_rate\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)",
    re.IGNORECASE,
)
BASELINE_PASSED_LINE_MARKERS: tuple[str, ...] = (
    "质量快照",
    "当前基线",
    "结果：",
    "结果:",
    "口径",
    "pytest=",
    "pytest.passed",
    "quality_snapshot",
    "自动化测试",
    "全量测试",
)
BASELINE_CASE_COUNT_LINE_MARKERS: tuple[str, ...] = (
    "质量快照",
    "当前基线",
    "结果：",
    "结果:",
    "口径",
    "结论：",
    "结论:",
)
BASELINE_COVERAGE_LINE_MARKERS: tuple[str, ...] = (
    "coverage=",
    "quality_snapshot",
    "line_rate=",
    "coverage.line_rate",
    "总覆盖率",
    "当前覆盖率",
    "质量快照",
    "当前基线",
    "结果：",
    "结果:",
)
DATE_DOC_PATTERNS: dict[str, str] = {
    "comprehensive_report": "18-综合审查报告-*.md",
    "baseline_consistency": "21-全量基线一致性校验记录-*.md",
}

METRIC_SCAN_RELATIVE_PATHS: tuple[str, ...] = (
    "11-实施现状问题与Sprint规划.md",
    "15-研究闭环验收基线.md",
    "16-研究口径Issue拆解与排期.md",
    "{comprehensive_report}",
    "19-用户使用说明书.md",
    "{baseline_consistency}",
    "22-分阶段验收报告.md",
    "26-测试报告.md",
    "../review/02-审查总报告.md",
    "../review/06-收口执行记录.md",
)


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


def _validate_sha(raw: Any, *, field_name: str) -> str:
    value = str(raw or "")
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ValueError(f"{field_name} invalid: {value!r}")
    return value


def _load_snapshot(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"snapshot payload must be JSON object: {path}")

    legacy_git_sha = payload.get("git_sha")
    evidence_git_sha = payload.get("evidence_git_sha", legacy_git_sha)
    evidence_git_sha = _validate_sha(evidence_git_sha, field_name="snapshot evidence_git_sha")
    if legacy_git_sha not in (None, ""):
        legacy_git_sha = _validate_sha(legacy_git_sha, field_name="snapshot git_sha")
        if legacy_git_sha != evidence_git_sha:
            raise ValueError(
                f"snapshot git_sha must equal evidence_git_sha: {legacy_git_sha} != {evidence_git_sha}"
            )

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

    normalized = dict(payload)
    normalized["evidence_git_sha"] = evidence_git_sha
    normalized["git_sha"] = evidence_git_sha
    return normalized


def _coverage_percent(snapshot: dict[str, Any]) -> str:
    return f"{float(snapshot['coverage']['line_rate']):.2f}%"


def _resolve_git_sha() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        return None
    return value


def build_doc_checks(
    snapshot: dict[str, Any],
    *,
    workspace_git_sha: str,
    comprehensive_report_path: str | None,
    baseline_consistency_path: str | None,
) -> list[DocCheck]:
    evidence_git_sha = str(snapshot["evidence_git_sha"])
    passed = int(snapshot["pytest"]["passed"])
    line_rate = float(snapshot["coverage"]["line_rate"])
    coverage_percent = _coverage_percent(snapshot)

    checks: list[DocCheck] = [
        DocCheck(
            relative_path="10-详细设计说明书.md",
            required_substrings=(
                f"evidence_git_sha={evidence_git_sha}",
                f"workspace_git_sha={workspace_git_sha}",
                QUALITY_SNAPSHOT_PATH,
            ),
        ),
        DocCheck(
            relative_path="11-实施现状问题与Sprint规划.md",
            required_substrings=(
                f"evidence_git_sha={evidence_git_sha}",
                f"workspace_git_sha={workspace_git_sha}",
                f"{passed} passed",
                coverage_percent,
                QUALITY_SNAPSHOT_PATH,
            ),
        ),
        DocCheck(
            relative_path="14-docx需求追踪矩阵.md",
            required_substrings=(
                f"evidence_git_sha={evidence_git_sha}",
                f"workspace_git_sha={workspace_git_sha}",
                QUALITY_SNAPSHOT_PATH,
            ),
        ),
        DocCheck(
            relative_path="15-研究闭环验收基线.md",
            required_substrings=(
                f"evidence_git_sha={evidence_git_sha}",
                f"workspace_git_sha={workspace_git_sha}",
                f"pytest={passed} passed",
                f"coverage={coverage_percent}",
                QUALITY_SNAPSHOT_PATH,
            ),
        ),
        DocCheck(
            relative_path="16-研究口径Issue拆解与排期.md",
            required_substrings=(
                f"evidence_git_sha={evidence_git_sha}",
                f"workspace_git_sha={workspace_git_sha}",
                f"{passed} passed",
                coverage_percent,
                QUALITY_SNAPSHOT_PATH,
            ),
        ),
        DocCheck(
            relative_path="19-用户使用说明书.md",
            required_substrings=(
                f"evidence_git_sha={evidence_git_sha}",
                f"workspace_git_sha={workspace_git_sha}",
                f"pytest={passed} passed",
                f"coverage={coverage_percent}",
                QUALITY_SNAPSHOT_PATH,
            ),
        ),
        DocCheck(
            relative_path="22-分阶段验收报告.md",
            required_substrings=(
                f"evidence_git_sha={evidence_git_sha}",
                f"workspace_git_sha={workspace_git_sha}",
                f"pytest={passed} passed",
                f"line_rate={line_rate}",
                f"coverage={coverage_percent}",
                QUALITY_SNAPSHOT_PATH,
            ),
        ),
        DocCheck(
            relative_path="26-测试报告.md",
            required_substrings=(
                f"evidence_git_sha={evidence_git_sha}",
                f"workspace_git_sha={workspace_git_sha}",
                f"{passed} passed",
                coverage_percent,
                QUALITY_SNAPSHOT_PATH,
            ),
        ),
        DocCheck(
            relative_path="../review/02-审查总报告.md",
            required_substrings=(
                f"evidence_git_sha={evidence_git_sha}",
                f"workspace_git_sha={workspace_git_sha}",
                f"pytest={passed} passed",
                f"coverage={coverage_percent}",
                QUALITY_SNAPSHOT_PATH,
            ),
        ),
        DocCheck(
            relative_path="../review/06-收口执行记录.md",
            required_substrings=(
                f"evidence_git_sha={evidence_git_sha}",
                f"workspace_git_sha={workspace_git_sha}",
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

    if comprehensive_report_path:
        checks.append(
            DocCheck(
                relative_path=comprehensive_report_path,
                required_substrings=(
                    f"evidence_git_sha={evidence_git_sha}",
                    f"workspace_git_sha={workspace_git_sha}",
                    f"{passed} passed",
                    f"line_rate={line_rate}",
                    coverage_percent,
                    QUALITY_SNAPSHOT_PATH,
                ),
            )
        )
    if baseline_consistency_path:
        checks.append(
            DocCheck(
                relative_path=baseline_consistency_path,
                required_substrings=(
                    f"evidence_git_sha={evidence_git_sha}",
                    f"workspace_git_sha={workspace_git_sha}",
                    f"pytest={passed} passed",
                    f"coverage={coverage_percent}",
                    QUALITY_SNAPSHOT_PATH,
                ),
            )
        )
    return checks


def _validate_doc(
    path: Path,
    check: DocCheck,
    *,
    expected_evidence_sha: str,
    expected_workspace_sha: str,
) -> list[str]:
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

    for found in sorted(set(LEGACY_GIT_SHA_PATTERN.findall(text))):
        errors.append(
            f"{path}: found legacy git_sha field: {found}; use evidence_git_sha/workspace_git_sha"
        )

    for found in sorted(set(EVIDENCE_GIT_SHA_PATTERN.findall(text))):
        if found != expected_evidence_sha:
            errors.append(
                f"{path}: evidence_git_sha mismatch: expected {expected_evidence_sha}, found {found}"
            )

    for found in sorted(set(WORKSPACE_GIT_SHA_PATTERN.findall(text))):
        if found != expected_workspace_sha:
            errors.append(
                f"{path}: workspace_git_sha mismatch: expected {expected_workspace_sha}, found {found}"
            )

    return errors


def _resolve_single_doc(docs_root: Path, pattern: str) -> str:
    matches = sorted(path.name for path in docs_root.glob(pattern) if path.is_file())
    if len(matches) != 1:
        details = ", ".join(matches) if matches else "<none>"
        raise ValueError(
            f"{docs_root}: pattern {pattern!r} expected exactly 1 match, "
            f"found {len(matches)} ({details})"
        )
    return matches[0]


def _line_has_marker(line: str, markers: tuple[str, ...]) -> bool:
    lowered = line.lower()
    return any(marker.lower() in lowered for marker in markers)


def _iter_metric_scan_paths(
    docs_root: Path,
    *,
    comprehensive_report_path: str | None,
    baseline_consistency_path: str | None,
) -> list[Path]:
    substitutions = {
        "comprehensive_report": comprehensive_report_path or "",
        "baseline_consistency": baseline_consistency_path or "",
    }
    ordered_relative_paths: list[str] = [
        relative_path.format(**substitutions)
        for relative_path in METRIC_SCAN_RELATIVE_PATHS
        if relative_path.format(**substitutions)
    ]
    ordered_relative_paths.extend(path.name for path in sorted(docs_root.glob("26-*.md")))

    deduplicated: list[str] = []
    seen: set[str] = set()
    for relative_path in ordered_relative_paths:
        if relative_path in seen:
            continue
        seen.add(relative_path)
        deduplicated.append(relative_path)
    return [docs_root / relative_path for relative_path in deduplicated]


def _validate_metric_value_consistency(
    docs_root: Path,
    *,
    expected_passed: int,
    expected_coverage_percent: str,
    comprehensive_report_path: str | None,
    baseline_consistency_path: str | None,
) -> list[str]:
    errors: list[str] = []
    expected_coverage = float(expected_coverage_percent.rstrip("%"))

    for path in _iter_metric_scan_paths(
        docs_root,
        comprehensive_report_path=comprehensive_report_path,
        baseline_consistency_path=baseline_consistency_path,
    ):
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for line_no, line in enumerate(lines, start=1):
            lowered = line.lower()
            skip_collect_only = "collect-only" in lowered

            if not skip_collect_only and _line_has_marker(line, BASELINE_PASSED_LINE_MARKERS):
                for match in PASSED_PATTERN.finditer(line):
                    found = int(match.group(1))
                    if found != expected_passed:
                        errors.append(
                            f"{path}:{line_no}: pytest passed mismatch: expected "
                            f"{expected_passed}, found {found}"
                        )
                for match in PASSED_ASSIGNMENT_PATTERN.finditer(line):
                    found = int(match.group(1))
                    if found != expected_passed:
                        errors.append(
                            f"{path}:{line_no}: pytest passed mismatch: expected "
                            f"{expected_passed}, found {found}"
                        )

            if not skip_collect_only and _line_has_marker(line, BASELINE_CASE_COUNT_LINE_MARKERS):
                for match in ALL_GREEN_CASES_PATTERN.finditer(line):
                    found = int(match.group(1))
                    if found != expected_passed:
                        errors.append(
                            f"{path}:{line_no}: pytest case-count mismatch: expected "
                            f"{expected_passed}, found {found}"
                        )

            if _line_has_marker(line, BASELINE_COVERAGE_LINE_MARKERS):
                for match in COVERAGE_PERCENT_PATTERN.finditer(line):
                    found = float(match.group(1))
                    if abs(found - expected_coverage) > 0.01:
                        errors.append(
                            f"{path}:{line_no}: coverage mismatch: expected "
                            f"{expected_coverage_percent}, found {found:.2f}%"
                        )
                for match in COVERAGE_LINE_RATE_PATTERN.finditer(line):
                    found = float(match.group(1))
                    if abs(found - expected_coverage) > 0.01:
                        errors.append(
                            f"{path}:{line_no}: coverage mismatch: expected "
                            f"{expected_coverage_percent}, found {found:.2f}%"
                        )

    return errors


def run_consistency_check(
    snapshot_path: Path,
    docs_root: Path,
    *,
    require_evidence_equals_head: bool = False,
    expected_head_sha: str | None = None,
) -> list[str]:
    snapshot = _load_snapshot(snapshot_path)
    expected_evidence_sha = str(snapshot["evidence_git_sha"])
    expected_passed = int(snapshot["pytest"]["passed"])
    expected_coverage_percent = _coverage_percent(snapshot)

    errors: list[str] = []
    head_sha = expected_head_sha or _resolve_git_sha()
    if head_sha is None:
        return [f"{snapshot_path}: unable to resolve git HEAD"]

    comprehensive_report_path: str | None = None
    baseline_consistency_path: str | None = None
    for key, pattern in DATE_DOC_PATTERNS.items():
        try:
            resolved = _resolve_single_doc(docs_root, pattern)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if key == "comprehensive_report":
            comprehensive_report_path = resolved
        elif key == "baseline_consistency":
            baseline_consistency_path = resolved

    if require_evidence_equals_head and head_sha != expected_evidence_sha:
        errors.append(
            f"{snapshot_path}: snapshot evidence_git_sha mismatch with git HEAD: "
            f"expected {head_sha}, found {expected_evidence_sha}"
        )

    checks = build_doc_checks(
        snapshot,
        workspace_git_sha=head_sha,
        comprehensive_report_path=comprehensive_report_path,
        baseline_consistency_path=baseline_consistency_path,
    )
    for check in checks:
        errors.extend(
            _validate_doc(
                docs_root / check.relative_path,
                check,
                expected_evidence_sha=expected_evidence_sha,
                expected_workspace_sha=head_sha,
            )
        )
    errors.extend(
        _validate_metric_value_consistency(
            docs_root,
            expected_passed=expected_passed,
            expected_coverage_percent=expected_coverage_percent,
            comprehensive_report_path=comprehensive_report_path,
            baseline_consistency_path=baseline_consistency_path,
        )
    )
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
    parser.add_argument(
        "--allow-stale-snapshot",
        action="store_true",
        help="legacy no-op flag; default already allows evidence_git_sha to differ from git HEAD",
    )
    parser.add_argument(
        "--require-evidence-equals-head",
        action="store_true",
        help="require snapshot evidence_git_sha to match current git HEAD",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    snapshot_path = Path(args.snapshot)
    docs_root = Path(args.docs_root)

    try:
        errors = run_consistency_check(
            snapshot_path=snapshot_path,
            docs_root=docs_root,
            require_evidence_equals_head=args.require_evidence_equals_head,
        )
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
