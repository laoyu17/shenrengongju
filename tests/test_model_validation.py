from __future__ import annotations

import pytest

from rtos_sim.io import ConfigError, ConfigLoader


def _base_payload() -> dict:
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
                "period": 10,
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
        "sim": {"duration": 20, "seed": 1},
    }


def test_cycle_detected() -> None:
    payload = _base_payload()
    task = payload["tasks"][0]
    task["subtasks"] = [
        {
            "id": "s0",
            "predecessors": ["s1"],
            "successors": ["s1"],
            "segments": [{"id": "seg0", "index": 1, "wcet": 1}],
        },
        {
            "id": "s1",
            "predecessors": ["s0"],
            "successors": ["s0"],
            "segments": [{"id": "seg1", "index": 1, "wcet": 1}],
        },
    ]

    with pytest.raises(ConfigError):
        ConfigLoader().load_data(payload)


def test_unknown_mapping_hint_detected() -> None:
    payload = _base_payload()
    payload["tasks"][0]["subtasks"][0]["segments"][0]["mapping_hint"] = "c9"
    with pytest.raises(ConfigError):
        ConfigLoader().load_data(payload)


def test_mapping_hint_conflicts_with_resource_bound_core_detected() -> None:
    payload = _base_payload()
    payload["platform"]["cores"].append({"id": "c1", "type_id": "CPU", "speed_factor": 1.0})
    payload["resources"] = [{"id": "r0", "name": "lock", "bound_core_id": "c0", "protocol": "mutex"}]
    segment = payload["tasks"][0]["subtasks"][0]["segments"][0]
    segment["required_resources"] = ["r0"]
    segment["mapping_hint"] = "c1"
    with pytest.raises(ConfigError):
        ConfigLoader().load_data(payload)


def test_resource_bound_core_is_applied_when_mapping_hint_missing() -> None:
    payload = _base_payload()
    payload["platform"]["cores"].append({"id": "c1", "type_id": "CPU", "speed_factor": 1.0})
    payload["resources"] = [{"id": "r0", "name": "lock", "bound_core_id": "c0", "protocol": "mutex"}]
    payload["tasks"][0]["subtasks"][0]["segments"][0]["required_resources"] = ["r0"]
    spec = ConfigLoader().load_data(payload)
    segment = spec.tasks[0].subtasks[0].segments[0]
    assert segment.mapping_hint == "c0"


def test_segment_with_resources_bound_to_multiple_cores_is_rejected() -> None:
    payload = _base_payload()
    payload["platform"]["cores"].append({"id": "c1", "type_id": "CPU", "speed_factor": 1.0})
    payload["resources"] = [
        {"id": "r0", "name": "lock0", "bound_core_id": "c0", "protocol": "mutex"},
        {"id": "r1", "name": "lock1", "bound_core_id": "c1", "protocol": "mutex"},
    ]
    payload["tasks"][0]["subtasks"][0]["segments"][0]["required_resources"] = ["r0", "r1"]
    with pytest.raises(ConfigError):
        ConfigLoader().load_data(payload)


def test_time_deterministic_defaults_phase_and_release_offsets() -> None:
    payload = _base_payload()
    task = payload["tasks"][0]
    task["task_type"] = "time_deterministic"
    task["period"] = 10
    spec = ConfigLoader().load_data(payload)
    assert spec.tasks[0].phase_offset == pytest.approx(0.0)
    assert spec.tasks[0].subtasks[0].segments[0].release_offsets == [0.0]


def test_phase_offset_rejected_for_non_time_deterministic() -> None:
    payload = _base_payload()
    payload["tasks"][0]["phase_offset"] = 1.0
    with pytest.raises(ConfigError):
        ConfigLoader().load_data(payload)


def test_release_offsets_rejected_for_non_time_deterministic() -> None:
    payload = _base_payload()
    payload["tasks"][0]["subtasks"][0]["segments"][0]["release_offsets"] = [0.2]
    with pytest.raises(ConfigError):
        ConfigLoader().load_data(payload)


def test_release_offset_must_be_less_than_period() -> None:
    payload = _base_payload()
    task = payload["tasks"][0]
    task["task_type"] = "time_deterministic"
    task["period"] = 5
    task["subtasks"][0]["segments"][0]["release_offsets"] = [5.0]
    with pytest.raises(ConfigError):
        ConfigLoader().load_data(payload)
