"""Validate doc reference anchors: path exists and line numbers are in range."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re


DEFAULT_TARGETS: tuple[str, ...] = (
    "docs/25-设计方案报告全量追踪矩阵.md",
    "review/00-Docx条款主索引.md",
    "review/01-Docx条款追踪矩阵.md",
)

# Matches references like: path/file.py:123, path/file.md:12~34, path/file.md:12`~`34
REFERENCE_PATTERN = re.compile(
    r"(?P<path>[^\s`'\"()<>]+?\.[A-Za-z0-9_\-*]+):(?P<start>\d+)"
    r"(?:\s*`?[~～-]`?\s*`?(?P<end>\d+)`?)?"
)


@dataclass(slots=True)
class ParsedReference:
    source_file: Path
    source_line: int
    raw_path: str
    start_line: int
    end_line: int | None


@dataclass(slots=True)
class ValidationErrorItem:
    source_file: Path
    source_line: int
    message: str

    def format(self) -> str:
        return f"{self.source_file}:{self.source_line}: {self.message}"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check doc references (path exists + line anchor valid)")
    parser.add_argument("--repo-root", default=".", help="repository root path")
    parser.add_argument(
        "--targets",
        nargs="*",
        default=list(DEFAULT_TARGETS),
        help="target markdown files to validate (default: docs/25 + review/00/01)",
    )
    return parser


def _iter_references(path: Path) -> list[ParsedReference]:
    refs: list[ParsedReference] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for line_no, line in enumerate(lines, start=1):
        for match in REFERENCE_PATTERN.finditer(line):
            raw_path = match.group("path")
            if raw_path.startswith(("http://", "https://")):
                continue
            start_line = int(match.group("start"))
            end_raw = match.group("end")
            end_line = int(end_raw) if end_raw else None
            refs.append(
                ParsedReference(
                    source_file=path,
                    source_line=line_no,
                    raw_path=raw_path,
                    start_line=start_line,
                    end_line=end_line,
                )
            )
    return refs


def _resolve_reference_path(repo_root: Path, source_file: Path, raw_path: str) -> Path | None:
    candidate = Path(raw_path)
    probes: list[Path] = []
    if candidate.is_absolute():
        probes.append(candidate)
    else:
        probes.append((source_file.parent / candidate).resolve())
        probes.append((repo_root / candidate).resolve())

    for probe in probes:
        if probe.exists():
            return probe
    return None


def _validate_reference(repo_root: Path, ref: ParsedReference) -> list[ValidationErrorItem]:
    errors: list[ValidationErrorItem] = []

    if ref.start_line <= 0:
        errors.append(
            ValidationErrorItem(
                source_file=ref.source_file,
                source_line=ref.source_line,
                message=f"invalid line number <= 0: {ref.raw_path}:{ref.start_line}",
            )
        )
        return errors

    resolved = _resolve_reference_path(repo_root, ref.source_file, ref.raw_path)
    if resolved is None:
        errors.append(
            ValidationErrorItem(
                source_file=ref.source_file,
                source_line=ref.source_line,
                message=f"referenced path not found: {ref.raw_path}",
            )
        )
        return errors

    if ref.end_line is not None and ref.end_line < ref.start_line:
        errors.append(
            ValidationErrorItem(
                source_file=ref.source_file,
                source_line=ref.source_line,
                message=(
                    f"invalid range: {ref.raw_path}:{ref.start_line}~{ref.end_line} "
                    f"(end < start)"
                ),
            )
        )
        return errors

    if not resolved.is_file():
        errors.append(
            ValidationErrorItem(
                source_file=ref.source_file,
                source_line=ref.source_line,
                message=f"referenced path is not a file: {ref.raw_path}",
            )
        )
        return errors

    max_line = sum(1 for _ in resolved.open("r", encoding="utf-8"))
    if ref.start_line > max_line:
        errors.append(
            ValidationErrorItem(
                source_file=ref.source_file,
                source_line=ref.source_line,
                message=(
                    f"line anchor out of range: {ref.raw_path}:{ref.start_line} "
                    f"(max={max_line})"
                ),
            )
        )

    if ref.end_line is not None and ref.end_line > max_line:
        errors.append(
            ValidationErrorItem(
                source_file=ref.source_file,
                source_line=ref.source_line,
                message=(
                    f"range anchor out of range: {ref.raw_path}:{ref.start_line}~{ref.end_line} "
                    f"(max={max_line})"
                ),
            )
        )

    return errors


def check_reference_integrity(*, repo_root: Path, target_files: list[Path]) -> list[ValidationErrorItem]:
    errors: list[ValidationErrorItem] = []

    for target in target_files:
        if not target.exists():
            errors.append(
                ValidationErrorItem(
                    source_file=target,
                    source_line=1,
                    message="target file not found",
                )
            )
            continue
        refs = _iter_references(target)
        for ref in refs:
            errors.extend(_validate_reference(repo_root, ref))

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    target_files = [(repo_root / item).resolve() for item in args.targets]

    errors = check_reference_integrity(repo_root=repo_root, target_files=target_files)
    if errors:
        print("[FAIL] doc reference integrity check failed")
        for item in errors:
            print(f" - {item.format()}")
        return 1

    print("[OK] doc reference integrity check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
