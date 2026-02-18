from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest
import yaml

from rtos_sim.io import ConfigError, ConfigLoader
from rtos_sim.model import ModelSpec


def _base_payload_v02() -> dict[str, Any]:
    return {
        "version": "0.2",
        "platform": {
            "processor_types": [
                {"id": "CPU", "name": "cpu", "core_count": 1, "speed_factor": 1.0},
            ],
            "cores": [{"id": "c0", "type_id": "CPU", "speed_factor": 1.0}],
        },
        "resources": [],
        "tasks": [
            {
                "id": "t0",
                "name": "task",
                "task_type": "dynamic_rt",
                "deadline": 10,
                "arrival": 0,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [{"id": "seg0", "index": 1, "wcet": 1}],
                    }
                ],
            }
        ],
        "scheduler": {"name": "edf", "params": {}},
        "sim": {"duration": 5, "seed": 1},
    }


def _base_payload_v01() -> dict[str, Any]:
    payload = _base_payload_v02()
    payload["version"] = "0.1"
    payload.pop("resources", None)
    payload["scheduler"] = {"name": "edf"}
    task = payload["tasks"][0]
    task.pop("arrival", None)
    task.pop("abort_on_miss", None)
    subtask = task["subtasks"][0]
    subtask.pop("predecessors", None)
    subtask.pop("successors", None)
    segment = subtask["segments"][0]
    segment.pop("required_resources", None)
    segment.pop("preemptible", None)
    return payload


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_load_raises_when_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="config file not found"):
        ConfigLoader().load(str(tmp_path / "missing.yaml"))


def test_load_raises_on_invalid_yaml_syntax(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("version: [", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid config syntax"):
        ConfigLoader().load(str(path))


def test_load_raises_on_invalid_json_syntax(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"version": "0.2",}', encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid config syntax"):
        ConfigLoader().load(str(path))


def test_load_raises_when_root_is_not_object(tmp_path: Path) -> None:
    path = tmp_path / "list_root.yaml"
    path.write_text("- 1\n- 2\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="config root must be object"):
        ConfigLoader().load(str(path))


@pytest.mark.parametrize("suffix", [".yaml", ".yml", ".json"])
def test_save_supports_yaml_yml_json(tmp_path: Path, suffix: str) -> None:
    loader = ConfigLoader()
    spec = loader.load_data(_base_payload_v02())
    output = tmp_path / f"out{suffix}"
    loader.save(spec, str(output))

    text = output.read_text(encoding="utf-8")
    if suffix in {".yaml", ".yml"}:
        parsed = yaml.safe_load(text)
        assert parsed["version"] == "0.2"
    else:
        parsed = json.loads(text)
        assert parsed["version"] == "0.2"
        assert text.lstrip().startswith("{")


def test_validate_returns_empty_for_modelspec_instance() -> None:
    loader = ConfigLoader()
    spec: ModelSpec = loader.load_data(_base_payload_v02())
    assert loader.validate(spec) == []


def test_validate_returns_empty_for_valid_path(tmp_path: Path) -> None:
    path = tmp_path / "ok.yaml"
    _write_yaml(path, _base_payload_v02())
    assert ConfigLoader().validate(str(path)) == []


def test_validate_returns_issue_for_invalid_path(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("- 1\n", encoding="utf-8")

    issues = ConfigLoader().validate(str(path))
    assert len(issues) == 1
    assert issues[0].path == str(path)
    assert "config root must be object" in issues[0].message


def test_migrate_01_to_02_fills_default_fields() -> None:
    loader = ConfigLoader()
    spec = loader.load_data(_base_payload_v01())

    assert spec.version == "0.2"
    assert spec.resources == []
    assert spec.scheduler.params == {}
    task = spec.tasks[0]
    subtask = task.subtasks[0]
    segment = subtask.segments[0]
    assert task.arrival == 0
    assert task.abort_on_miss is False
    assert subtask.predecessors == []
    assert subtask.successors == []
    assert segment.required_resources == []
    assert segment.preemptible is True


@pytest.mark.parametrize(
    ("mutator", "expected"),
    [
        (lambda p: p.update({"scheduler": "oops"}), "scheduler must be object"),
        (lambda p: p["scheduler"].update({"params": []}), "scheduler.params must be object"),
        (lambda p: p.update({"tasks": "oops"}), "tasks must be list"),
        (lambda p: p.update({"tasks": ["oops"]}), "tasks[0] must be object"),
        (
            lambda p: p["tasks"][0].update({"subtasks": "oops"}),
            "tasks[0].subtasks must be list",
        ),
        (
            lambda p: p["tasks"][0].update({"subtasks": ["oops"]}),
            "tasks[0].subtasks[0] must be object",
        ),
        (
            lambda p: p["tasks"][0]["subtasks"][0].update({"segments": "oops"}),
            "tasks[0].subtasks[0].segments must be list",
        ),
        (
            lambda p: p["tasks"][0]["subtasks"][0].update({"segments": ["oops"]}),
            "tasks[0].subtasks[0].segments[0] must be object",
        ),
    ],
)
def test_migrate_01_invalid_structure_is_wrapped_as_config_error(
    mutator: Callable[[dict[str, Any]], None],
    expected: str,
) -> None:
    payload = _base_payload_v01()
    mutator(payload)
    with pytest.raises(ConfigError) as exc:
        ConfigLoader().load_data(payload)
    message = str(exc.value)
    assert "invalid config structure" in message
    assert expected in message


def test_schema_validation_message_is_aggregated_and_limited_to_8_entries() -> None:
    payload = {
        "version": "0.2",
        "platform": {
            "processor_types": [],
            "cores": [],
            "extra": 1,
        },
        "resources": [
            {"id": 1, "name": 2, "bound_core_id": 3, "protocol": "bad"},
        ],
        "tasks": [
            {
                "id": 1,
                "name": 2,
                "task_type": "bad",
                "subtasks": [],
                "extra": 1,
            }
        ],
        "scheduler": {"name": 1, "params": [], "extra": 1},
        "sim": {"duration": 0, "seed": "x", "extra": 1},
        "extra": 1,
    }

    with pytest.raises(ConfigError, match="schema validation failed") as exc:
        ConfigLoader().load_data(payload)

    details = str(exc.value).split("schema validation failed: ", 1)[1].split(" | ")
    assert len(details) == 8
    assert all(": " in item for item in details)


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"resource_acquire_policy": "bad"}, "resource_acquire_policy"),
        ({"event_id_mode": 123}, "event_id_mode"),
        ({"etm": 123}, "etm"),
        ({"etm_params": []}, "etm_params"),
    ],
)
def test_scheduler_params_validation_rules(params: dict[str, Any], expected: str) -> None:
    payload = _base_payload_v02()
    payload["scheduler"]["params"] = params
    with pytest.raises(ConfigError, match=expected):
        ConfigLoader().load_data(payload)


def test_event_id_mode_invalid_string_fails_when_validation_default_strict() -> None:
    payload = _base_payload_v02()
    payload["scheduler"]["params"] = {"event_id_mode": "bad_mode"}
    with pytest.raises(ConfigError, match="event_id_mode"):
        ConfigLoader().load_data(payload)


def test_event_id_validation_parameter_is_rejected_after_hard_fail_cutover() -> None:
    payload = _base_payload_v02()
    payload["scheduler"]["params"] = {"event_id_mode": "deterministic", "event_id_validation": "strict"}
    with pytest.raises(ConfigError, match="event_id_validation"):
        ConfigLoader().load_data(payload)
