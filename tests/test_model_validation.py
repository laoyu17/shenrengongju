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
