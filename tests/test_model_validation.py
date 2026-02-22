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
    payload["platform"]["processor_types"][0]["core_count"] = 2
    payload["platform"]["cores"].append({"id": "c1", "type_id": "CPU", "speed_factor": 1.0})
    payload["resources"] = [{"id": "r0", "name": "lock", "bound_core_id": "c0", "protocol": "mutex"}]
    segment = payload["tasks"][0]["subtasks"][0]["segments"][0]
    segment["required_resources"] = ["r0"]
    segment["mapping_hint"] = "c1"
    with pytest.raises(ConfigError):
        ConfigLoader().load_data(payload)


def test_resource_bound_core_is_applied_when_mapping_hint_missing() -> None:
    payload = _base_payload()
    payload["platform"]["processor_types"][0]["core_count"] = 2
    payload["platform"]["cores"].append({"id": "c1", "type_id": "CPU", "speed_factor": 1.0})
    payload["resources"] = [{"id": "r0", "name": "lock", "bound_core_id": "c0", "protocol": "mutex"}]
    payload["tasks"][0]["subtasks"][0]["segments"][0]["required_resources"] = ["r0"]
    spec = ConfigLoader().load_data(payload)
    segment = spec.tasks[0].subtasks[0].segments[0]
    assert segment.mapping_hint == "c0"


def test_segment_with_resources_bound_to_multiple_cores_is_rejected() -> None:
    payload = _base_payload()
    payload["platform"]["processor_types"][0]["core_count"] = 2
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
    segment = spec.tasks[0].subtasks[0].segments[0]
    assert spec.tasks[0].phase_offset == pytest.approx(0.0)
    assert segment.release_offsets == [0.0]
    assert segment.mapping_hint == "c0"


def test_time_deterministic_requires_mapping_hint_on_multicore_when_not_derivable() -> None:
    payload = _base_payload()
    payload["platform"]["processor_types"][0]["core_count"] = 2
    payload["platform"]["cores"].append({"id": "c1", "type_id": "CPU", "speed_factor": 1.0})
    task = payload["tasks"][0]
    task["task_type"] = "time_deterministic"
    task["period"] = 10
    with pytest.raises(ConfigError):
        ConfigLoader().load_data(payload)


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


def test_processor_type_core_count_must_match_declared_cores() -> None:
    payload = _base_payload()
    payload["platform"]["processor_types"][0]["core_count"] = 2
    with pytest.raises(ConfigError, match="core_count"):
        ConfigLoader().load_data(payload)


def test_dynamic_rt_random_arrival_requires_min_inter_arrival() -> None:
    payload = _base_payload()
    payload["tasks"][0]["max_inter_arrival"] = 2.0
    payload["tasks"][0].pop("period", None)
    payload["tasks"][0].pop("min_inter_arrival", None)
    with pytest.raises(ConfigError, match="max_inter_arrival requires"):
        ConfigLoader().load_data(payload)


def test_dynamic_rt_max_inter_arrival_must_be_ge_min_inter_arrival() -> None:
    payload = _base_payload()
    payload["tasks"][0]["min_inter_arrival"] = 3.0
    payload["tasks"][0]["max_inter_arrival"] = 2.0
    with pytest.raises(ConfigError, match="max_inter_arrival must be"):
        ConfigLoader().load_data(payload)


def test_uniform_arrival_model_requires_max_inter_arrival() -> None:
    payload = _base_payload()
    payload["tasks"][0]["arrival_model"] = "uniform_interval"
    payload["tasks"][0].pop("max_inter_arrival", None)
    with pytest.raises(ConfigError, match="arrival_model=uniform_interval"):
        ConfigLoader().load_data(payload)


def test_fixed_arrival_model_rejects_max_inter_arrival() -> None:
    payload = _base_payload()
    payload["tasks"][0]["arrival_model"] = "fixed_interval"
    payload["tasks"][0]["max_inter_arrival"] = 12.0
    with pytest.raises(ConfigError, match="arrival_model=fixed_interval"):
        ConfigLoader().load_data(payload)


def test_arrival_model_only_valid_for_dynamic_rt() -> None:
    payload = _base_payload()
    payload["tasks"][0]["task_type"] = "non_rt"
    payload["tasks"][0]["arrival_model"] = "fixed_interval"
    with pytest.raises(ConfigError, match="arrival_model is only valid for dynamic_rt"):
        ConfigLoader().load_data(payload)


def test_arrival_process_rejected_for_time_deterministic() -> None:
    payload = _base_payload()
    payload["tasks"][0]["task_type"] = "time_deterministic"
    payload["tasks"][0]["arrival_process"] = {"type": "fixed", "params": {"interval": 1.0}}
    with pytest.raises(ConfigError, match="arrival_process is not valid"):
        ConfigLoader().load_data(payload)


def test_arrival_process_fixed_requires_interval_for_non_rt() -> None:
    payload = _base_payload()
    payload["tasks"][0]["task_type"] = "non_rt"
    payload["tasks"][0]["arrival_process"] = {"type": "fixed", "params": {}}
    with pytest.raises(ConfigError, match="arrival_process type=fixed requires"):
        ConfigLoader().load_data(payload)


def test_arrival_process_one_shot_defaults_max_releases() -> None:
    payload = _base_payload()
    payload["tasks"][0]["arrival_process"] = {"type": "one_shot"}
    spec = ConfigLoader().load_data(payload)
    assert spec.tasks[0].arrival_process is not None
    assert spec.tasks[0].arrival_process.max_releases == 1


def test_arrival_process_uniform_validates_bounds() -> None:
    payload = _base_payload()
    payload["tasks"][0]["arrival_process"] = {
        "type": "uniform",
        "params": {"min_interval": 3.0, "max_interval": 2.0},
    }
    with pytest.raises(ConfigError, match="max_interval must be >="):
        ConfigLoader().load_data(payload)


def test_arrival_process_poisson_requires_rate() -> None:
    payload = _base_payload()
    payload["tasks"][0]["arrival_process"] = {"type": "poisson", "params": {}}
    with pytest.raises(ConfigError, match="requires params.rate"):
        ConfigLoader().load_data(payload)


def test_arrival_process_rejects_unsupported_params() -> None:
    payload = _base_payload()
    payload["tasks"][0]["arrival_process"] = {
        "type": "fixed",
        "params": {"interval": 2.0, "bad": 1.0},
    }
    with pytest.raises(ConfigError, match="unsupported keys"):
        ConfigLoader().load_data(payload)


def test_arrival_process_custom_requires_generator() -> None:
    payload = _base_payload()
    payload["tasks"][0]["arrival_process"] = {
        "type": "custom",
        "params": {"interval": 1.0},
    }
    with pytest.raises(ConfigError, match="generator"):
        ConfigLoader().load_data(payload)


def test_arrival_process_custom_allows_generator_and_scalar_params() -> None:
    payload = _base_payload()
    payload["tasks"][0]["arrival_process"] = {
        "type": "custom",
        "params": {"generator": "constant_interval", "interval": 1.5, "mode": "demo"},
    }
    spec = ConfigLoader().load_data(payload)
    process = spec.tasks[0].arrival_process
    assert process is not None
    assert process.params["generator"] == "constant_interval"


def test_arrival_process_custom_rejects_nested_params() -> None:
    payload = _base_payload()
    payload["tasks"][0]["arrival_process"] = {
        "type": "custom",
        "params": {"generator": "constant_interval", "options": {"k": 1}},
    }
    with pytest.raises(ConfigError, match="scalar|given schemas"):
        ConfigLoader().load_data(payload)


def test_task_mapping_hint_applies_to_segments_without_mapping_hint() -> None:
    payload = _base_payload()
    payload["platform"]["processor_types"][0]["core_count"] = 2
    payload["platform"]["cores"].append({"id": "c1", "type_id": "CPU", "speed_factor": 1.0})
    payload["tasks"][0]["task_mapping_hint"] = "c1"
    spec = ConfigLoader().load_data(payload)
    assert spec.tasks[0].subtasks[0].segments[0].mapping_hint == "c1"


def test_subtask_mapping_hint_overrides_task_mapping_hint() -> None:
    payload = _base_payload()
    payload["platform"]["processor_types"][0]["core_count"] = 2
    payload["platform"]["cores"].append({"id": "c1", "type_id": "CPU", "speed_factor": 1.0})
    payload["tasks"][0]["task_mapping_hint"] = "c0"
    payload["tasks"][0]["subtasks"][0]["subtask_mapping_hint"] = "c1"
    spec = ConfigLoader().load_data(payload)
    assert spec.tasks[0].subtasks[0].segments[0].mapping_hint == "c1"


def test_segment_mapping_hint_overrides_parent_mapping_hints() -> None:
    payload = _base_payload()
    payload["platform"]["processor_types"][0]["core_count"] = 2
    payload["platform"]["cores"].append({"id": "c1", "type_id": "CPU", "speed_factor": 1.0})
    payload["tasks"][0]["task_mapping_hint"] = "c0"
    payload["tasks"][0]["subtasks"][0]["subtask_mapping_hint"] = "c0"
    payload["tasks"][0]["subtasks"][0]["segments"][0]["mapping_hint"] = "c1"
    spec = ConfigLoader().load_data(payload)
    assert spec.tasks[0].subtasks[0].segments[0].mapping_hint == "c1"


def test_unknown_task_mapping_hint_detected() -> None:
    payload = _base_payload()
    payload["tasks"][0]["task_mapping_hint"] = "c9"
    with pytest.raises(ConfigError, match="task_mapping_hint"):
        ConfigLoader().load_data(payload)
