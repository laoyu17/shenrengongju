from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_doc_baseline_consistency.py"
SPEC = spec_from_file_location("check_doc_baseline_consistency", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
check_doc_baseline_consistency = module_from_spec(SPEC)
SPEC.loader.exec_module(check_doc_baseline_consistency)


def _snapshot(sha: str = "a" * 40) -> dict:
    return {
        "git_sha": sha,
        "pytest": {"passed": 249},
        "coverage": {"line_rate": 87.99806420390385},
    }


def _write_docs(docs_root: Path, snapshot: dict) -> None:
    docs_root.mkdir(parents=True, exist_ok=True)
    sha = snapshot["git_sha"]
    passed = snapshot["pytest"]["passed"]
    line_rate = snapshot["coverage"]["line_rate"]
    coverage_percent = f"{line_rate:.2f}%"
    quality_path = "artifacts/quality/quality-snapshot.json"

    (docs_root / "10-详细设计说明书.md").write_text(
        f"实现快照：git_sha={sha}\n复核：{quality_path}\n",
        encoding="utf-8",
    )
    (docs_root / "11-实施现状问题与Sprint规划.md").write_text(
        f"实现快照：git_sha={sha}\n测试：{passed} passed\n覆盖率：{coverage_percent}\n来源：{quality_path}\n",
        encoding="utf-8",
    )
    (docs_root / "14-docx需求追踪矩阵.md").write_text(
        f"实现快照：git_sha={sha}\n来源：{quality_path}\n",
        encoding="utf-8",
    )
    (docs_root / "15-研究闭环验收基线.md").write_text(
        f"实现快照：git_sha={sha}\n质量快照：pytest={passed} passed，coverage={coverage_percent}\n来源：{quality_path}\n",
        encoding="utf-8",
    )
    (docs_root / "18-综合审查报告-2026-02-24.md").write_text(
        (
            f"审查基线：git_sha={sha}\n"
            f"自动化测试：{passed} passed\n"
            f"line_rate={line_rate}\n"
            f"总覆盖率：{coverage_percent}\n"
            f"来源：{quality_path}\n"
        ),
        encoding="utf-8",
    )
    (docs_root / "19-用户使用说明书.md").write_text(
        f"实现快照：git_sha={sha}\n质量快照：pytest={passed} passed，coverage={coverage_percent}\n来源：{quality_path}\n",
        encoding="utf-8",
    )
    (docs_root / "20-审查问题台账.csv").write_text(
        (
            "id,severity,confidence,module,description,evidence_path,evidence_line,impact,repro_steps,suggested_fix,status\n"
            f"REV-TEST,P2,Verified,docs,基线校验记录 git_sha={sha},{quality_path},1,impact,repro,fix,resolved\n"
        ),
        encoding="utf-8",
    )
    (docs_root / "21-全量基线一致性校验记录-2026-02-24.md").write_text(
        (
            f"代码快照：git_sha={sha}\n"
            f"质量快照：pytest={passed} passed，coverage={coverage_percent}\n"
            f"命令：python scripts/quality_snapshot.py --output {quality_path}\n"
        ),
        encoding="utf-8",
    )
    (docs_root / "22-分阶段验收报告.md").write_text(
        (
            f"代码快照：git_sha={sha}\n"
            f"质量快照：pytest={passed} passed，coverage={coverage_percent}\n"
            f"line_rate={line_rate}\n"
            f"事实源：{quality_path}\n"
        ),
        encoding="utf-8",
    )
    (docs_root.parent / "README.md").write_text(
        (
            "- 研究闭环验收基线：docs/15-研究闭环验收基线.md\n"
            "- 审查问题台账：docs/20-审查问题台账.csv\n"
            f"python scripts/check_doc_baseline_consistency.py --snapshot {quality_path} --docs-root docs\n"
        ),
        encoding="utf-8",
    )


def test_run_consistency_check_pass(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot_path = tmp_path / "quality-snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    docs_root = tmp_path / "docs"
    _write_docs(docs_root, snapshot)

    errors = check_doc_baseline_consistency.run_consistency_check(
        snapshot_path=snapshot_path,
        docs_root=docs_root,
        enforce_head_match=False,
    )
    assert errors == []


def test_run_consistency_check_detects_git_sha_drift(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot_path = tmp_path / "quality-snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    docs_root = tmp_path / "docs"
    _write_docs(docs_root, snapshot)

    stale_sha = "b" * 40
    drift_doc = docs_root / "14-docx需求追踪矩阵.md"
    drift_doc.write_text(
        drift_doc.read_text(encoding="utf-8").replace(snapshot["git_sha"], stale_sha),
        encoding="utf-8",
    )

    errors = check_doc_baseline_consistency.run_consistency_check(
        snapshot_path=snapshot_path,
        docs_root=docs_root,
        enforce_head_match=False,
    )
    assert any("14-docx需求追踪矩阵.md" in item for item in errors)


def test_run_consistency_check_detects_missing_required_token(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot_path = tmp_path / "quality-snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    docs_root = tmp_path / "docs"
    _write_docs(docs_root, snapshot)

    report_doc = docs_root / "18-综合审查报告-2026-02-24.md"
    report_doc.write_text(
        report_doc.read_text(encoding="utf-8").replace(
            "artifacts/quality/quality-snapshot.json",
            "artifacts/quality/missing.json",
        ),
        encoding="utf-8",
    )

    errors = check_doc_baseline_consistency.run_consistency_check(
        snapshot_path=snapshot_path,
        docs_root=docs_root,
        enforce_head_match=False,
    )
    assert any("missing required token" in item for item in errors)


def test_run_consistency_check_detects_snapshot_head_mismatch(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot_path = tmp_path / "quality-snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    docs_root = tmp_path / "docs"
    _write_docs(docs_root, snapshot)

    errors = check_doc_baseline_consistency.run_consistency_check(
        snapshot_path=snapshot_path,
        docs_root=docs_root,
        expected_head_sha="b" * 40,
    )
    assert any("snapshot git_sha mismatch with git HEAD" in item for item in errors)


def test_run_consistency_check_accepts_matching_snapshot_head(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot_path = tmp_path / "quality-snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    docs_root = tmp_path / "docs"
    _write_docs(docs_root, snapshot)

    errors = check_doc_baseline_consistency.run_consistency_check(
        snapshot_path=snapshot_path,
        docs_root=docs_root,
        expected_head_sha=snapshot["git_sha"],
    )
    assert errors == []


def test_main_returns_non_zero_when_docs_missing(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot_path = tmp_path / "quality-snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    code = check_doc_baseline_consistency.main(
        [
            "--snapshot",
            str(snapshot_path),
            "--docs-root",
            str(tmp_path / "missing-docs"),
        ]
    )

    assert code == 1
