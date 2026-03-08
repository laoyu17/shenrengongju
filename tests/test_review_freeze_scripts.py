from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def _looks_like_windows_system_bash(path: str | Path) -> bool:
    normalized = os.fspath(path).replace("/", "\\").lower()
    return "\\windows\\system32\\bash.exe" in normalized


def _candidate_bash_paths(env: dict[str, str]) -> list[Path]:
    if not sys.platform.startswith("win"):
        which = shutil.which("bash", path=env.get("PATH"))
        return [Path(which)] if which else []

    candidates: list[Path] = []
    for entry in os.get_exec_path(env):
        if not entry:
            continue
        candidates.append(Path(entry) / "bash.exe")

    for key in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
        base = (env.get(key) or os.environ.get(key) or "").strip()
        if base:
            git_root = Path(base) / "Git"
            candidates.append(git_root / "bin" / "bash.exe")
            candidates.append(git_root / "usr" / "bin" / "bash.exe")

    local_app_data = (env.get("LocalAppData") or os.environ.get("LocalAppData") or "").strip()
    if local_app_data:
        git_root = Path(local_app_data) / "Programs" / "Git"
        candidates.append(git_root / "bin" / "bash.exe")
        candidates.append(git_root / "usr" / "bin" / "bash.exe")

    return candidates


def _resolve_bash_command(env: dict[str, str]) -> str:
    explicit_bash = (env.get("BASH_BIN") or "").strip()
    if explicit_bash:
        candidate = Path(explicit_bash)
        if candidate.is_file():
            return os.fspath(candidate)
        raise FileNotFoundError(f"BASH_BIN not found: {candidate}")

    seen: set[str] = set()
    for candidate in _candidate_bash_paths(env):
        candidate_key = os.fspath(candidate).replace("/", "\\").lower()
        if candidate_key in seen:
            continue
        seen.add(candidate_key)
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            continue
        if sys.platform.startswith("win") and _looks_like_windows_system_bash(candidate):
            continue
        return os.fspath(candidate)

    fallback = shutil.which("bash", path=env.get("PATH"))
    if fallback and (not sys.platform.startswith("win") or not _looks_like_windows_system_bash(fallback)):
        return fallback
    raise FileNotFoundError("unable to locate usable bash executable for freeze script tests")


def _normalize_shell_command(cmd: list[str], env: dict[str, str]) -> list[str]:
    if cmd and cmd[0] == "bash":
        return [_resolve_bash_command(env), *cmd[1:]]
    return cmd


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    run_env = dict(os.environ)
    run_env.setdefault("PYTHON_BIN", sys.executable)
    if env is not None:
        run_env.update(env)
    effective_cmd = _normalize_shell_command(cmd, run_env)
    return subprocess.run(effective_cmd, cwd=cwd, env=run_env, check=False, capture_output=True, text=True)


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


def test_resolve_bash_command_prefers_explicit_bash_bin(tmp_path: Path, monkeypatch) -> None:
    explicit_bash = tmp_path / "portable-git" / "bin" / "bash.exe"
    explicit_bash.parent.mkdir(parents=True)
    explicit_bash.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    explicit_bash.chmod(0o755)

    monkeypatch.setattr(sys, "platform", "win32")
    resolved = _resolve_bash_command({"BASH_BIN": os.fspath(explicit_bash)})
    assert Path(resolved) == explicit_bash


def test_resolve_bash_command_skips_windows_system32_shim(tmp_path: Path, monkeypatch) -> None:
    system_bash = tmp_path / "Windows" / "System32" / "bash.exe"
    git_bash = tmp_path / "Git" / "bin" / "bash.exe"
    system_bash.parent.mkdir(parents=True)
    git_bash.parent.mkdir(parents=True)
    system_bash.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    git_bash.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    system_bash.chmod(0o755)
    git_bash.chmod(0o755)

    env = {
        "PATH": f"{system_bash.parent}{os.pathsep}{git_bash.parent}",
        "ProgramFiles": os.fspath(tmp_path),
    }
    monkeypatch.setattr(sys, "platform", "win32")
    resolved = _resolve_bash_command(env)
    assert Path(resolved) == git_bash


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


def test_i2_freeze_resolves_alternate_python_when_python_alias_is_unusable(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()

    (fake_bin / "python3").write_text(
        "#!/usr/bin/env bash\n"
        "echo 'Python3 was not found' >&2\n"
        "exit 1\n",
        encoding="utf-8",
    )
    (fake_bin / "python").write_text(
        "#!/usr/bin/env bash\n"
        "echo 'Python was not found' >&2\n"
        "exit 1\n",
        encoding="utf-8",
    )
    (fake_bin / "py").write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == \"-3\" ]]; then shift; fi\n"
        f"exec {os.fsdecode(os.fsencode(os.sys.executable))!r} \"$@\"\n",
        encoding="utf-8",
    )
    (fake_bin / "python3").chmod(0o755)
    (fake_bin / "python").chmod(0o755)
    (fake_bin / "py").chmod(0o755)

    env = dict(**os.environ)
    env["PYTHON_BIN"] = ""
    env["pythonLocation"] = ""
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"

    result = _run(
        ["bash", "review/scripts/i2_freeze_delivery_baseline.sh", "review/runtime/i2/test_freeze"],
        cwd=repo,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    meta = json.loads((repo / "review/runtime/i2/test_freeze/snapshot_meta.json").read_text(encoding="utf-8"))
    assert meta["freeze_kind"] == "clean_formal"
    assert meta["dirty_workspace"] is False


def test_i2_freeze_skips_python_alias_that_passes_probe_but_cannot_run_stdin(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()

    alias_stub = (
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == \"-c\" ]]; then\n"
        "  exit 0\n"
        "fi\n"
        "echo 'Open the Microsoft Store to install Python.'\n"
        "exit 1\n"
    )
    (fake_bin / "python3").write_text(alias_stub, encoding="utf-8")
    (fake_bin / "python").write_text(alias_stub, encoding="utf-8")
    (fake_bin / "py").write_text(
        "#!/usr/bin/env bash\n"
        "if [[ \"${1:-}\" == \"-3\" ]]; then shift; fi\n"
        f"exec {os.fsdecode(os.fsencode(os.sys.executable))!r} \"$@\"\n",
        encoding="utf-8",
    )
    (fake_bin / "python3").chmod(0o755)
    (fake_bin / "python").chmod(0o755)
    (fake_bin / "py").chmod(0o755)

    env = dict(**os.environ)
    env["PYTHON_BIN"] = ""
    env["pythonLocation"] = ""
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"

    result = _run(
        ["bash", "review/scripts/i2_freeze_delivery_baseline.sh", "review/runtime/i2/test_freeze"],
        cwd=repo,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    meta = json.loads((repo / "review/runtime/i2/test_freeze/snapshot_meta.json").read_text(encoding="utf-8"))
    assert meta["freeze_kind"] == "clean_formal"
    assert meta["dirty_workspace"] is False


def test_i2_freeze_prefers_py_launcher_for_windows_repro_commands(tmp_path: Path) -> None:
    repo = _setup_repo(tmp_path)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()

    for name in ["python3", "python", "py"]:
        script = fake_bin / name
        script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        script.chmod(0o755)

    env = dict(**os.environ)
    env["PYTHON_BIN"] = ""
    env["pythonLocation"] = ""
    env["OSTYPE"] = "msys"
    env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"

    result = _run(
        ["bash", "review/scripts/i2_freeze_delivery_baseline.sh", "review/runtime/i2/test_freeze"],
        cwd=repo,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    reproduce = (repo / "review/runtime/i2/test_freeze/reproduce_commands.txt").read_text(encoding="utf-8")
    assert reproduce.splitlines()[0] == "py -3 -m pytest -q"


def test_i2_clean_freeze_gate_orders_required_steps() -> None:
    script = (ROOT / "review/scripts/i2_clean_freeze_gate.sh").read_text(encoding="utf-8")
    assert script.index("run_step 01 pytest_full") < script.index("run_step 02 quality_snapshot")
    assert script.index("run_step 02 quality_snapshot") < script.index("run_step 03 doc_baseline_consistency")
    assert script.index("run_step 03 doc_baseline_consistency") < script.index("run_step 04 clean_workspace")
    assert script.index("run_step 04 clean_workspace") < script.index("run_step 05 freeze_clean")
    assert "DOC_BASELINE_SNAPSHOT_PATH" in script
    assert "--require-evidence-equals-head" not in script
    assert 'QUALITY_SNAPSHOT_SOURCE="$QUALITY_SNAPSHOT_PATH"' in script


def test_i2_refresh_formal_freeze_script_runs_gate_before_reference_check() -> None:
    script = (ROOT / "review/scripts/i2_refresh_formal_freeze.sh").read_text(encoding="utf-8")
    assert "review/scripts/i2_clean_freeze_gate.sh" in script
    assert script.index("review/scripts/i2_clean_freeze_gate.sh") < script.index("check_doc_reference_integrity.py")
    assert "freeze_fact_source" in script
    assert "quality_fact_source" in script
