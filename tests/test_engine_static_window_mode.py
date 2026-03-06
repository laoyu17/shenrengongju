from __future__ import annotations

from copy import deepcopy

import pytest

from rtos_sim.core import SimEngine
from rtos_sim.io import ConfigError, ConfigLoader


def _run_payload(payload: dict) -> tuple[list[dict], dict]:
    loader = ConfigLoader()
    spec = loader.load_data(payload)
    engine = SimEngine()
    engine.build(spec)
    engine.run()
    events = [event.model_dump(mode="json") for event in engine.events]
    return events, engine.metric_report()


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
                "id": "fixed",
                "name": "fixed-task",
                "task_type": "time_deterministic",
                "period": 100.0,
                "deadline": 100.0,
                "arrival": 0.0,
                "phase_offset": 0.0,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [
                            {
                                "id": "fixed_seg",
                                "index": 1,
                                "wcet": 6.0,
                                "mapping_hint": "c0",
                            }
                        ],
                    }
                ],
            },
            {
                "id": "dyn",
                "name": "dynamic-task",
                "task_type": "dynamic_rt",
                "period": 50.0,
                "deadline": 10.0,
                "arrival": 1.0,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [
                            {
                                "id": "dyn_seg",
                                "index": 1,
                                "wcet": 1.0,
                                "mapping_hint": "c0",
                            }
                        ],
                    }
                ],
            },
        ],
        "scheduler": {"name": "edf", "params": {}},
        "sim": {"duration": 12.0, "seed": 7},
    }


def _first_event_time(events: list[dict], *, event_type: str, segment_id: str) -> float:
    matches = [
        float(event["time"])
        for event in events
        if event["type"] == event_type and event.get("segment_id") == segment_id
    ]
    assert matches
    return min(matches)


def test_without_static_window_dynamic_task_preempts_fixed_task() -> None:
    payload = _base_payload()
    events, metrics = _run_payload(payload)

    preempts = [event for event in events if event["type"] == "Preempt"]
    dyn_start = _first_event_time(events, event_type="SegmentStart", segment_id="dyn_seg")

    assert preempts
    assert dyn_start < 6.0
    assert metrics["forced_preempt_count"] == 0


def test_static_window_blocks_preempt_and_delays_dynamic_dispatch_until_window_end() -> None:
    payload = _base_payload()
    payload["scheduler"]["params"] = {
        "static_window_mode": True,
        "static_windows": [{"core_id": "c0", "task_id": "fixed", "start": 0.0, "end": 6.0}],
    }
    events, _ = _run_payload(payload)

    dyn_start = _first_event_time(events, event_type="SegmentStart", segment_id="dyn_seg")
    fixed_end = _first_event_time(events, event_type="SegmentEnd", segment_id="fixed_seg")
    preempts = [event for event in events if event["type"] == "Preempt"]

    assert not preempts
    assert fixed_end == pytest.approx(6.0)
    assert dyn_start >= 6.0 - 1e-9


def test_static_window_boundary_forces_preempt_for_non_window_task() -> None:
    payload = _base_payload()
    payload["tasks"][0]["arrival"] = 2.0
    payload["tasks"][0]["subtasks"][0]["segments"][0]["wcet"] = 3.0
    payload["tasks"][1]["arrival"] = 0.0
    payload["tasks"][1]["deadline"] = 30.0
    payload["tasks"][1]["subtasks"][0]["segments"][0]["wcet"] = 6.0
    payload["scheduler"]["params"] = {
        "static_window_mode": True,
        "static_windows": [{"core_id": "c0", "task_id": "fixed", "start": 2.0, "end": 5.0}],
    }
    events, _ = _run_payload(payload)

    forced_preempts = [
        event
        for event in events
        if event["type"] == "Preempt" and event.get("payload", {}).get("reason") == "static_window_boundary"
    ]
    fixed_start = _first_event_time(events, event_type="SegmentStart", segment_id="fixed_seg")
    fixed_end = _first_event_time(events, event_type="SegmentEnd", segment_id="fixed_seg")

    assert forced_preempts
    assert fixed_start == pytest.approx(2.0)
    assert fixed_end == pytest.approx(5.0)


def test_static_window_build_rejects_overlapped_windows_on_same_core() -> None:
    payload = _base_payload()
    payload["scheduler"]["params"] = {
        "static_window_mode": True,
        "static_windows": [
            {"core_id": "c0", "task_id": "fixed", "start": 0.0, "end": 4.0},
            {"core_id": "c0", "task_id": "fixed", "start": 3.0, "end": 5.0},
        ],
    }
    loader = ConfigLoader()
    spec = loader.load_data(deepcopy(payload))
    engine = SimEngine()
    with pytest.raises(ValueError, match="overlap"):
        engine.build(spec)


def test_static_window_segment_key_enforces_exact_segment() -> None:
    payload = {
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
                "id": "fixed",
                "name": "fixed-task",
                "task_type": "time_deterministic",
                "period": 100.0,
                "deadline": 100.0,
                "arrival": 0.0,
                "phase_offset": 0.0,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [
                            {
                                "id": "seg_a",
                                "index": 1,
                                "wcet": 2.0,
                                "mapping_hint": "c0",
                            }
                        ],
                    },
                    {
                        "id": "s1",
                        "predecessors": [],
                        "successors": [],
                        "segments": [
                            {
                                "id": "seg_b",
                                "index": 1,
                                "wcet": 2.0,
                                "mapping_hint": "c0",
                            }
                        ],
                    },
                ],
            }
        ],
        "scheduler": {
            "name": "edf",
            "params": {
                "static_window_mode": True,
                "static_windows": [
                    {
                        "core_id": "c0",
                        "segment_key": "fixed:s1:seg_b",
                        "start": 0.0,
                        "end": 2.0,
                    }
                ],
            },
        },
        "sim": {"duration": 6.0, "seed": 7},
    }

    events, _ = _run_payload(payload)
    seg_b_start = _first_event_time(events, event_type="SegmentStart", segment_id="seg_b")
    seg_a_start = _first_event_time(events, event_type="SegmentStart", segment_id="seg_a")

    assert seg_b_start == pytest.approx(0.0)
    assert seg_a_start >= 2.0 - 1e-9


def test_static_window_schema_rejects_non_array_windows() -> None:
    payload = _base_payload()
    payload["scheduler"]["params"] = {
        "static_window_mode": True,
        "static_windows": {"core_id": "c0", "task_id": "fixed", "start": 0.0, "end": 1.0},
    }

    with pytest.raises(ConfigError, match=r"scheduler\.params\.static_windows"):
        ConfigLoader().load_data(payload)


def test_static_window_schema_rejects_window_without_target_selector() -> None:
    payload = _base_payload()
    payload["scheduler"]["params"] = {
        "static_window_mode": True,
        "static_windows": [{"core_id": "c0", "start": 0.0, "end": 1.0}],
    }

    with pytest.raises(ConfigError, match=r"scheduler\.params\.static_windows\.0"):
        ConfigLoader().load_data(payload)


def test_static_window_schema_rejects_subtask_without_segment_id() -> None:
    payload = _base_payload()
    payload["scheduler"]["params"] = {
        "static_window_mode": True,
        "static_windows": [
            {
                "core_id": "c0",
                "task_id": "fixed",
                "subtask_id": "s0",
                "start": 0.0,
                "end": 1.0,
            }
        ],
    }

    with pytest.raises(ConfigError, match=r"scheduler\.params\.static_windows\.0: .*segment_id"):
        ConfigLoader().load_data(payload)


def test_static_window_release_index_targets_specific_job_instance() -> None:
    payload = {
        "version": "0.2",
        "platform": {
            "processor_types": [{"id": "CPU", "name": "cpu", "core_count": 1, "speed_factor": 1.0}],
            "cores": [{"id": "c0", "type_id": "CPU", "speed_factor": 1.0}],
        },
        "resources": [],
        "tasks": [
            {
                "id": "fixed",
                "name": "fixed",
                "task_type": "time_deterministic",
                "period": 4.0,
                "deadline": 10.0,
                "arrival": 0.0,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [
                            {"id": "seg0", "index": 1, "wcet": 6.0, "mapping_hint": "c0"}
                        ],
                    }
                ],
            }
        ],
        "scheduler": {
            "name": "edf",
            "params": {
                "static_window_mode": True,
                "static_windows": [
                    {"core_id": "c0", "task_id": "fixed", "release_index": 1, "start": 4.0, "end": 5.0}
                ],
            },
        },
        "sim": {"duration": 8.0, "seed": 7},
    }

    events, _ = _run_payload(payload)
    forced_preempts = [
        event for event in events
        if event["type"] == "Preempt" and event.get("payload", {}).get("reason") == "static_window_boundary"
    ]
    starts_at_four = [
        event for event in events
        if event["type"] == "SegmentStart" and abs(float(event["time"]) - 4.0) <= 1e-9
    ]

    assert forced_preempts
    assert starts_at_four
    assert starts_at_four[0]["job_id"] == "fixed@1"
