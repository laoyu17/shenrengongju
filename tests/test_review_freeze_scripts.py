from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, env=env, check=False, capture_output=True, text=True)


def _setup_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "review/scripts").mkdir(parents=True)
    (repo / "review/runtime").mkdir(parents=True)
    (repo / "review/runtime/i1/ci_gate").mkdir(parents=True)
    (repo / "review/runtime/i1/sched_rate_gate").mkdir(parents=True)
    (repo / "review/runtime/i2").mkdir(parents=True)
    (repo / ".github/workflows").mkdir(parents=True)
    (repo / "artifacts/quality").mkdir(parents=True)

    for relative_path in [
        "review/scripts/i2_freeze_delivery_baseline.sh",
        "review/scripts/i2_clean_freeze_gate.sh",
    ]:
        source = ROOT / relative_path
        target = repo / relative_path
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    (repo / "review/scripts/i1_ci_gate.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (repo / "review/scripts/i1_freeze_sched_rate_gate.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (repo / "review/scripts/strict_plan_pipeline.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (repo / "review/runtime/runtime_evidence.json").write_text("{}\n", encoding="utf-8")
    (repo / "review/runtime/command_results.tsv").write_text("id\trc\n", encoding="utf-8")
    (repo / "review/runtime/i1/ci_gate/results.tsv").write_text("id\trc\n", encoding="utf-8")
    (repo / "review/runtime/i1/sched_rate_gate/summary.txt").write_text("ok\n", encoding="utf-8")
    (repo / "review/03-问题台账.csv").write_text("id,status\nRISK-001,open\n", encoding="utf-8")
    (repo / "review/06-收口执行记录.md").write_text("# record\n", encoding="utf-8")
    (repo / ".github/workflows/ci.yml").write_text("name: test\n", encoding="utf-8")
    (repo / "artifacts/quality/quality-snapshot.json").write_text(
        json.dumps({"status": "pass", "evidence_git_sha": "0" * 40, "git_sha": "0" * 40}) + "\n",
        encoding="utf-8",
    )

    _run(["git", "init"], cwd=repo)
    _run(["git", "config", "user.name", "Test User"], cwd=repo)
    _run(["git", "config", "user.email", "test@example.com"], cwd=repo)
    _run(["git", "add", "."], cwd=repo)
    commit = _run(["git", "commit", "-m", "init"], cwd=repo)
    assert commit.returncode == 0, commit.stderr
    return repo


def test_i2_freeze_rejects_dirty_workspace_without_allow_override(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    result = _run(
        ["bash", "review/scripts/i2_freeze_delivery_baseline.sh", "review/runtime/i2/test_freeze"],
        cwd=repo,
    )

    assert result.returncode == 2
    assert "requires clean workspace" in result.stderr
    assert not (repo / "review/runtime/i2/test_freeze/tag.txt").exists()
    assert not (repo / "review/runtime/i2/test_freeze/snapshot_meta.json").exists()
    assert _run(["git", "tag"], cwd=repo).stdout.strip() == ""


def test_i2_freeze_allows_dirty_evidence_snapshot_with_override(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    env = dict(**os.environ, ALLOW_DIRTY_FREEZE="1")

    result = _run(
        ["bash", "review/scripts/i2_freeze_delivery_baseline.sh", "review/runtime/i2/test_freeze"],
        cwd=repo,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    meta = json.loads((repo / "review/runtime/i2/test_freeze/snapshot_meta.json").read_text(encoding="utf-8"))
    assert meta["dirty_workspace"] is True
    assert meta["freeze_kind"] == "dirty_evidence"
    assert meta["formal_freeze"] is False

    tag_text = (repo / "review/runtime/i2/test_freeze/tag.txt").read_text(encoding="utf-8")
    assert "tag_status=skipped_dirty_evidence" in tag_text
    assert _run(["git", "tag"], cwd=repo).stdout.strip() == ""


def test_i2_freeze_creates_clean_formal_snapshot_and_tag(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)

    result = _run(
        ["bash", "review/scripts/i2_freeze_delivery_baseline.sh", "review/runtime/i2/test_freeze"],
        cwd=repo,
    )

    assert result.returncode == 0, result.stderr
    meta = json.loads((repo / "review/runtime/i2/test_freeze/snapshot_meta.json").read_text(encoding="utf-8"))
    assert meta["dirty_workspace"] is False
    assert meta["freeze_kind"] == "clean_formal"
    assert meta["formal_freeze"] is True
    assert _run(["git", "tag"], cwd=repo).stdout.strip()


def test_i2_clean_freeze_gate_orders_required_steps() -> None:
    script = (ROOT / "review/scripts/i2_clean_freeze_gate.sh").read_text(encoding="utf-8")
    assert script.index("run_step 01 pytest_full") < script.index("run_step 02 quality_snapshot")
    assert script.index("run_step 02 quality_snapshot") < script.index("run_step 03 doc_baseline_consistency")
    assert script.index("run_step 03 doc_baseline_consistency") < script.index("run_step 04 clean_workspace")
    assert script.index("run_step 04 clean_workspace") < script.index("run_step 05 freeze_clean")
    assert "--require-evidence-equals-head" in script
    assert "QUALITY_SNAPSHOT_SOURCE=\"$QUALITY_SNAPSHOT_PATH\"" in script
