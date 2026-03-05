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
    (docs_root / "16-研究口径Issue拆解与排期.md").write_text(
        (
            f"当前基线：{passed} passed\n"
            f"当前覆盖率：{coverage_percent}\n"
            f"事实源：{quality_path}\n"
        ),
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
    (docs_root / "26-测试报告.md").write_text(
        (
            f"来源：{quality_path}\n"
            f"代码快照：git_sha={sha}\n"
            f"结果：{passed} passed，覆盖率 {coverage_percent}\n"
        ),
        encoding="utf-8",
    )

    review_root = docs_root.parent / "review"
    review_root.mkdir(parents=True, exist_ok=True)
    (review_root / "02-审查总报告.md").write_text(
        (
            f"质量事实源：{quality_path}\n"
            f"基线：git_sha={sha}\n"
            f"口径：pytest={passed} passed，coverage={coverage_percent}\n"
        ),
        encoding="utf-8",
    )
    (review_root / "06-收口执行记录.md").write_text(
        (
            f"质量事实源：{quality_path}\n"
            f"基线：git_sha={sha}\n"
            f"口径：pytest={passed} passed，coverage={coverage_percent}\n"
            f"结论：{passed} 用例全绿\n"
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


def test_run_consistency_check_detects_docs26_value_conflict(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot_path = tmp_path / "quality-snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    docs_root = tmp_path / "docs"
    _write_docs(docs_root, snapshot)

    report_doc = docs_root / "26-测试报告.md"
    report_doc.write_text(
        report_doc.read_text(encoding="utf-8").replace(
            f"{snapshot['pytest']['passed']} passed",
            "357 passed",
        ),
        encoding="utf-8",
    )

    errors = check_doc_baseline_consistency.run_consistency_check(
        snapshot_path=snapshot_path,
        docs_root=docs_root,
        enforce_head_match=False,
    )
    assert any("26-测试报告.md" in item for item in errors)


def test_run_consistency_check_detects_review_metric_conflict(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot_path = tmp_path / "quality-snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    docs_root = tmp_path / "docs"
    _write_docs(docs_root, snapshot)

    review_doc = docs_root.parent / "review" / "06-收口执行记录.md"
    review_doc.write_text(
        review_doc.read_text(encoding="utf-8").replace(
            f"{snapshot['pytest']['passed']} 用例全绿",
            "352 用例全绿",
        ),
        encoding="utf-8",
    )

    errors = check_doc_baseline_consistency.run_consistency_check(
        snapshot_path=snapshot_path,
        docs_root=docs_root,
        enforce_head_match=False,
    )
    assert any("06-收口执行记录.md" in item and "case-count mismatch" in item for item in errors)


def test_run_consistency_check_ignores_historical_passed_line(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot_path = tmp_path / "quality-snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    docs_root = tmp_path / "docs"
    _write_docs(docs_root, snapshot)

    baseline_doc = docs_root / "21-全量基线一致性校验记录-2026-02-24.md"
    baseline_doc.write_text(
        baseline_doc.read_text(encoding="utf-8") + "\n历史记录：95 passed（仅用于回顾）\n",
        encoding="utf-8",
    )

    errors = check_doc_baseline_consistency.run_consistency_check(
        snapshot_path=snapshot_path,
        docs_root=docs_root,
        enforce_head_match=False,
    )
    assert errors == []


def test_run_consistency_check_supports_dated_doc_pattern(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot_path = tmp_path / "quality-snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    docs_root = tmp_path / "docs"
    _write_docs(docs_root, snapshot)

    (docs_root / "18-综合审查报告-2026-02-24.md").rename(docs_root / "18-综合审查报告-2026-03-05.md")
    (docs_root / "21-全量基线一致性校验记录-2026-02-24.md").rename(
        docs_root / "21-全量基线一致性校验记录-2026-03-05.md"
    )

    errors = check_doc_baseline_consistency.run_consistency_check(
        snapshot_path=snapshot_path,
        docs_root=docs_root,
        enforce_head_match=False,
    )
    assert errors == []


def test_run_consistency_check_reports_ambiguous_dated_doc_pattern(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot_path = tmp_path / "quality-snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    docs_root = tmp_path / "docs"
    _write_docs(docs_root, snapshot)

    source = docs_root / "18-综合审查报告-2026-02-24.md"
    (docs_root / "18-综合审查报告-2026-03-05.md").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    errors = check_doc_baseline_consistency.run_consistency_check(
        snapshot_path=snapshot_path,
        docs_root=docs_root,
        enforce_head_match=False,
    )
    assert any("18-综合审查报告-*.md" in item and "expected exactly 1 match" in item for item in errors)


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
