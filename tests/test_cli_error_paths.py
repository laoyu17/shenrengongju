from __future__ import annotations

import builtins
import json
from pathlib import Path
from types import ModuleType

import pytest

from rtos_sim.cli.main import main
from rtos_sim.io import ConfigError


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_cli_validate_returns_error_when_config_missing(tmp_path: Path) -> None:
    code = main(["validate", "-c", str(tmp_path / "missing.yaml")])
    assert code == 1


def test_cli_validate_returns_error_on_unexpected_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(_self: object, _path: str) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr("rtos_sim.cli.main.ConfigLoader.load", _boom)
    code = main(["validate", "-c", "ignored.yaml"])
    assert code == 1


def test_cli_run_returns_error_when_config_missing(tmp_path: Path) -> None:
    code = main(["run", "-c", str(tmp_path / "missing.yaml")])
    assert code == 1


def test_cli_run_rejects_non_positive_delta() -> None:
    code = main(
        [
            "run",
            "-c",
            str(EXAMPLES / "at01_single_dag_single_core.yaml"),
            "--step",
            "--delta",
            "0",
        ]
    )
    assert code == 1


def test_cli_run_rejects_negative_pause_at() -> None:
    code = main(
        [
            "run",
            "-c",
            str(EXAMPLES / "at01_single_dag_single_core.yaml"),
            "--pause-at",
            "-1",
        ]
    )
    assert code == 1


def test_cli_run_step_without_delta_handles_no_progress(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def _no_advance(_self: object, _delta: float | None = None) -> None:
        return

    monkeypatch.setattr("rtos_sim.cli.main.SimEngine.step", _no_advance)
    code = main(
        [
            "run",
            "-c",
            str(EXAMPLES / "at01_single_dag_single_core.yaml"),
            "--step",
            "--until",
            "0.5",
            "--events-out",
            str(tmp_path / "events.jsonl"),
            "--metrics-out",
            str(tmp_path / "metrics.json"),
        ]
    )
    assert code == 0


def test_cli_run_returns_error_on_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _runtime(_self: object, _spec: object) -> None:
        raise RuntimeError("runtime")

    monkeypatch.setattr("rtos_sim.cli.main.SimEngine.build", _runtime)
    code = main(["run", "-c", str(EXAMPLES / "at01_single_dag_single_core.yaml")])
    assert code == 1


def test_cli_run_returns_error_on_unexpected_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def _type_error(_self: object, _spec: object) -> None:
        raise TypeError("unexpected")

    monkeypatch.setattr("rtos_sim.cli.main.SimEngine.build", _type_error)
    code = main(["run", "-c", str(EXAMPLES / "at01_single_dag_single_core.yaml")])
    assert code == 1


def test_cli_ui_returns_error_when_import_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    origin_import = builtins.__import__

    def _fake_import(
        name: str,
        globals_: dict | None = None,
        locals_: dict | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "rtos_sim.ui.app":
            raise ImportError("ui missing")
        return origin_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    code = main(["ui"])
    assert code == 1


def test_cli_ui_returns_error_when_launch_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    origin_import = builtins.__import__
    fake_module = ModuleType("rtos_sim.ui.app")

    def _raise_ui(config_path: str | None = None) -> None:
        _ = config_path
        raise RuntimeError("ui boom")

    fake_module.run_ui = _raise_ui  # type: ignore[attr-defined]

    def _fake_import(
        name: str,
        globals_: dict | None = None,
        locals_: dict | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "rtos_sim.ui.app":
            return fake_module
        return origin_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    code = main(["ui"])
    assert code == 1


def test_cli_ui_returns_ok_when_launch_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    origin_import = builtins.__import__
    fake_module = ModuleType("rtos_sim.ui.app")

    def _ok_ui(config_path: str | None = None) -> None:
        _ = config_path
        return

    fake_module.run_ui = _ok_ui  # type: ignore[attr-defined]

    def _fake_import(
        name: str,
        globals_: dict | None = None,
        locals_: dict | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == "rtos_sim.ui.app":
            return fake_module
        return origin_import(name, globals_, locals_, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    code = main(["ui"])
    assert code == 0


def test_cli_batch_run_returns_error_on_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _config_error(_self: object, *_args: object, **_kwargs: object) -> object:
        raise ConfigError("bad batch")

    monkeypatch.setattr("rtos_sim.cli.main.ExperimentRunner.run_batch", _config_error)
    code = main(["batch-run", "-b", "ignored.yaml"])
    assert code == 1


def test_cli_batch_run_returns_error_on_unexpected_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def _unexpected(_self: object, *_args: object, **_kwargs: object) -> object:
        raise RuntimeError("batch boom")

    monkeypatch.setattr("rtos_sim.cli.main.ExperimentRunner.run_batch", _unexpected)
    code = main(["batch-run", "-b", "ignored.yaml"])
    assert code == 1


def test_cli_compare_returns_error_when_metrics_is_not_object(tmp_path: Path) -> None:
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    left.write_text("[]", encoding="utf-8")
    right.write_text("{}", encoding="utf-8")

    code = main(["compare", "--left-metrics", str(left), "--right-metrics", str(right)])
    assert code == 1


def test_cli_inspect_model_returns_error_on_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _config_error(_self: object, _path: str) -> object:
        raise ConfigError("bad config")

    monkeypatch.setattr("rtos_sim.cli.main.ConfigLoader.load", _config_error)
    code = main(["inspect-model", "-c", "ignored.yaml"])
    assert code == 1


def test_cli_inspect_model_returns_error_on_unexpected_load_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _unexpected(_self: object, _path: str) -> object:
        raise RuntimeError("load boom")

    monkeypatch.setattr("rtos_sim.cli.main.ConfigLoader.load", _unexpected)
    code = main(["inspect-model", "-c", "ignored.yaml"])
    assert code == 1


def test_cli_inspect_model_returns_error_on_report_build_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _report_boom(_spec: object) -> object:
        raise RuntimeError("report boom")

    monkeypatch.setattr("rtos_sim.cli.main.build_model_relations_report", _report_boom)
    code = main(["inspect-model", "-c", str(EXAMPLES / "at01_single_dag_single_core.yaml")])
    assert code == 1


def test_cli_migrate_config_returns_error_when_input_missing(tmp_path: Path) -> None:
    code = main(
        [
            "migrate-config",
            "--in",
            str(tmp_path / "missing.yaml"),
            "--out",
            str(tmp_path / "out.yaml"),
        ]
    )
    assert code == 1


def test_cli_migrate_config_returns_error_when_input_json_invalid(tmp_path: Path) -> None:
    source = tmp_path / "bad.json"
    source.write_text("{bad json", encoding="utf-8")
    code = main(
        [
            "migrate-config",
            "--in",
            str(source),
            "--out",
            str(tmp_path / "out.yaml"),
        ]
    )
    assert code == 1


def test_cli_migrate_config_returns_error_when_input_root_not_object(tmp_path: Path) -> None:
    source = tmp_path / "bad_root.json"
    source.write_text("[]", encoding="utf-8")
    code = main(
        [
            "migrate-config",
            "--in",
            str(source),
            "--out",
            str(tmp_path / "out.yaml"),
        ]
    )
    assert code == 1


def test_cli_migrate_config_returns_error_on_unexpected_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    def _unexpected(_self: object, _payload: dict) -> tuple[dict, dict]:
        raise RuntimeError("migrate boom")

    monkeypatch.setattr("rtos_sim.cli.main.ConfigLoader.migrate_data", _unexpected)
    code = main(
        [
            "migrate-config",
            "--in",
            str(EXAMPLES / "at01_single_dag_single_core.yaml"),
            "--out",
            "ignored.yaml",
        ]
    )
    assert code == 1


def test_cli_migrate_config_returns_error_when_write_output_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def _write_boom(_path: str, _payload: dict[str, object]) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("rtos_sim.cli.main._write_config_payload", _write_boom)
    code = main(
        [
            "migrate-config",
            "--in",
            str(EXAMPLES / "at01_single_dag_single_core.yaml"),
            "--out",
            "ignored.yaml",
        ]
    )
    assert code == 1


def test_cli_migrate_config_can_write_json_output(tmp_path: Path) -> None:
    out_json = tmp_path / "migrated.json"
    code = main(
        [
            "migrate-config",
            "--in",
            str(EXAMPLES / "at01_single_dag_single_core.yaml"),
            "--out",
            str(out_json),
        ]
    )
    assert code == 0
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["version"] == "0.2"
