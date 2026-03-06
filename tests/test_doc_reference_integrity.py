from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_doc_reference_integrity.py"
SPEC = spec_from_file_location("check_doc_reference_integrity", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
check_doc_reference_integrity = module_from_spec(SPEC)
sys.modules[SPEC.name] = check_doc_reference_integrity
SPEC.loader.exec_module(check_doc_reference_integrity)


def test_check_reference_integrity_pass(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    docs = repo / "docs"
    review = repo / "review"
    scripts = repo / "scripts"
    docs.mkdir(parents=True)
    review.mkdir(parents=True)
    scripts.mkdir(parents=True)

    (scripts / "tool.py").write_text("a\nb\nc\nd\n", encoding="utf-8")
    (review / "evidence.md").write_text("line1\nline2\nline3\n", encoding="utf-8")

    target = docs / "target.md"
    target.write_text(
        "ref1: `scripts/tool.py:3`\n"
        "ref2: `review/evidence.md:1~3`\n",
        encoding="utf-8",
    )

    errors = check_doc_reference_integrity.check_reference_integrity(
        repo_root=repo,
        target_files=[target],
    )

    assert errors == []


def test_check_reference_integrity_detects_missing_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    docs = repo / "docs"
    docs.mkdir(parents=True)

    target = docs / "target.md"
    target.write_text("`missing/file.py:1`\n", encoding="utf-8")

    errors = check_doc_reference_integrity.check_reference_integrity(
        repo_root=repo,
        target_files=[target],
    )

    assert any("referenced path not found" in item.message for item in errors)


def test_check_reference_integrity_detects_line_overflow(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    docs = repo / "docs"
    review = repo / "review"
    docs.mkdir(parents=True)
    review.mkdir(parents=True)

    (review / "evidence.md").write_text("line1\nline2\n", encoding="utf-8")
    target = docs / "target.md"
    target.write_text("`review/evidence.md:5`\n", encoding="utf-8")

    errors = check_doc_reference_integrity.check_reference_integrity(
        repo_root=repo,
        target_files=[target],
    )

    assert any("line anchor out of range" in item.message for item in errors)
