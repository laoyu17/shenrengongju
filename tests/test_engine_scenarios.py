from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from rtos_sim.core import SimEngine
from rtos_sim.io import ConfigLoader


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _run_example(name: str):
    loader = ConfigLoader()
    spec = loader.load(str(EXAMPLES / name))
    engine = SimEngine()
    engine.build(spec)
    engine.run()
    events = [event.model_dump(mode="json") for event in engine.events]
    return events, engine.metric_report()


def _run_payload(payload: dict):
    loader = ConfigLoader()
    spec = loader.load_data(payload)
    engine = SimEngine()
    engine.build(spec)
    engine.run()
    events = [event.model_dump(mode="json") for event in engine.events]
    return events, engine.metric_report()


def test_at01_segment_order() -> None:
    events, metrics = _run_example("at01_single_dag_single_core.yaml")
    segment_end = [e["segment_id"] for e in events if e["type"] == "SegmentEnd"]
    assert "seg0" in segment_end
    assert "seg1" in segment_end
    assert metrics["jobs_completed"] >= 1


def test_at02_mutex_blocking() -> None:
    events, _ = _run_example("at02_resource_mutex.yaml")
    blocked = [e for e in events if e["type"] == "SegmentBlocked"]
    acquire = [e for e in events if e["type"] == "ResourceAcquire"]
    release = [e for e in events if e["type"] == "ResourceRelease"]
    assert blocked
    assert acquire
    assert release


def test_at03_resource_binding_core() -> None:
    events, _ = _run_example("at03_resource_binding.yaml")
    acquire = [e for e in events if e["type"] == "ResourceAcquire"]
    assert acquire
    assert all(e["core_id"] == "c0" for e in acquire)


def test_at04_deadline_miss() -> None:
    events, metrics = _run_example("at04_deadline_miss.yaml")
    assert any(e["type"] == "DeadlineMiss" for e in events)
    assert metrics["deadline_miss_count"] >= 1


def test_at05_preempt() -> None:
    events, metrics = _run_example("at05_preempt.yaml")
    assert any(e["type"] == "Preempt" for e in events)
    assert metrics["preempt_count"] >= 1


def test_at05_preempt_utilization_is_accounted_on_preempt_boundary() -> None:
    _, metrics = _run_example("at05_preempt.yaml")
    assert metrics["core_utilization"]["c0"] == pytest.approx(1.0)


def test_at06_time_deterministic_is_repeatable() -> None:
    events_a, metrics_a = _run_example("at06_time_deterministic.yaml")
    events_b, metrics_b = _run_example("at06_time_deterministic.yaml")

    assert events_a == events_b
    assert metrics_a == metrics_b

    release_times = [event["time"] for event in events_a if event["type"] == "JobReleased"]
    assert release_times == pytest.approx([0.0, 5.0, 10.0, 15.0])


def test_at07_heterogeneous_core_speed_scaling() -> None:
    events, metrics = _run_example("at07_heterogeneous_multicore.yaml")

    fast_end = next(
        event["time"]
        for event in events
        if event["type"] == "SegmentEnd" and str(event.get("job_id", "")).startswith("fast@")
    )
    slow_end = next(
        event["time"]
        for event in events
        if event["type"] == "SegmentEnd" and str(event.get("job_id", "")).startswith("slow@")
    )
    assert fast_end == pytest.approx(2.0)
    assert slow_end == pytest.approx(4.0)
    assert metrics["core_utilization"]["c1"] == pytest.approx(0.5)
    assert metrics["core_utilization"]["c0"] == pytest.approx(1.0)


def _single_core_payload(protocol: str) -> dict:
    return {
        "version": "0.2",
        "platform": {
            "processor_types": [
                {"id": "CPU", "name": "cpu", "core_count": 1, "speed_factor": 1.0},
            ],
            "cores": [{"id": "c0", "type_id": "CPU", "speed_factor": 1.0}],
        },
        "resources": [{"id": "r0", "name": "lock", "bound_core_id": "c0", "protocol": protocol}],
        "scheduler": {"name": "edf", "params": {}},
        "sim": {"duration": 20, "seed": 7},
    }


def test_pip_owner_inherits_priority_after_blocking() -> None:
    payload = _single_core_payload("mutex")
    payload["resources"] = [
        {"id": "r_dummy", "name": "dummy", "bound_core_id": "c0", "protocol": "mutex"},
        {"id": "r0", "name": "lock", "bound_core_id": "c0", "protocol": "pip"},
    ]
    payload["tasks"] = [
        {
            "id": "low",
            "name": "low",
            "task_type": "dynamic_rt",
            "deadline": 50,
            "arrival": 0,
            "subtasks": [
                {
                    "id": "s0",
                    "predecessors": [],
                    "successors": [],
                    "segments": [{"id": "seg0", "index": 1, "wcet": 4, "required_resources": ["r0"]}],
                }
            ],
        },
        {
            "id": "med",
            "name": "med",
            "task_type": "dynamic_rt",
            "deadline": 20,
            "arrival": 0.5,
            "subtasks": [
                {
                    "id": "s0",
                    "predecessors": [],
                    "successors": [],
                    "segments": [{"id": "seg0", "index": 1, "wcet": 2}],
                }
            ],
        },
        {
            "id": "high",
            "name": "high",
            "task_type": "dynamic_rt",
            "deadline": 5,
            "arrival": 1.0,
            "subtasks": [
                {
                    "id": "s0",
                    "predecessors": [],
                    "successors": [],
                    "segments": [{"id": "seg0", "index": 1, "wcet": 1, "required_resources": ["r0"]}],
                }
            ],
        },
    ]

    loader = ConfigLoader()
    spec = loader.load_data(payload)
    engine = SimEngine()
    engine.build(spec)
    engine.run()
    events = [event.model_dump(mode="json") for event in engine.events]

    blocked_idx = next(
        idx
        for idx, event in enumerate(events)
        if event["type"] == "SegmentBlocked" and str(event.get("job_id", "")).startswith("high@")
    )
    next_start = next(event for event in events[blocked_idx + 1 :] if event["type"] == "SegmentStart")
    assert str(next_start["job_id"]).startswith("low@")


def test_pcp_ceiling_prevents_medium_task_from_preempting_lock_holder() -> None:
    payload = _single_core_payload("pcp")
    payload["tasks"] = [
        {
            "id": "low",
            "name": "low",
            "task_type": "dynamic_rt",
            "deadline": 50,
            "arrival": 0,
            "subtasks": [
                {
                    "id": "s0",
                    "predecessors": [],
                    "successors": [],
                    "segments": [{"id": "seg0", "index": 1, "wcet": 4, "required_resources": ["r0"]}],
                }
            ],
        },
        {
            "id": "med",
            "name": "med",
            "task_type": "dynamic_rt",
            "deadline": 20,
            "arrival": 0.5,
            "subtasks": [
                {
                    "id": "s0",
                    "predecessors": [],
                    "successors": [],
                    "segments": [{"id": "seg0", "index": 1, "wcet": 2}],
                }
            ],
        },
        {
            "id": "high",
            "name": "high",
            "task_type": "dynamic_rt",
            "deadline": 5,
            "arrival": 2.0,
            "subtasks": [
                {
                    "id": "s0",
                    "predecessors": [],
                    "successors": [],
                    "segments": [{"id": "seg0", "index": 1, "wcet": 1, "required_resources": ["r0"]}],
                }
            ],
        },
    ]

    loader = ConfigLoader()
    spec = loader.load_data(payload)
    engine = SimEngine()
    engine.build(spec)
    engine.run()
    events = [event.model_dump(mode="json") for event in engine.events]

    low_end = next(
        event["time"]
        for event in events
        if event["type"] == "SegmentEnd" and str(event.get("job_id", "")).startswith("low@")
    )
    med_start = next(
        event["time"]
        for event in events
        if event["type"] == "SegmentStart" and str(event.get("job_id", "")).startswith("med@")
    )
    assert med_start >= low_end - 1e-9


def test_pcp_system_ceiling_blocks_even_when_target_resource_is_free() -> None:
    payload = {
        "version": "0.2",
        "platform": {
            "processor_types": [
                {"id": "CPU", "name": "cpu", "core_count": 2, "speed_factor": 1.0},
            ],
            "cores": [
                {"id": "c0", "type_id": "CPU", "speed_factor": 1.0},
                {"id": "c1", "type_id": "CPU", "speed_factor": 1.0},
            ],
        },
        "scheduler": {"name": "edf", "params": {}},
        "sim": {"duration": 20, "seed": 7},
    }
    payload["resources"] = [
        {"id": "r0", "name": "lockA", "bound_core_id": "c0", "protocol": "pcp"},
        {"id": "r1", "name": "lockB", "bound_core_id": "c1", "protocol": "pcp"},
    ]
    payload["tasks"] = [
        {
            "id": "low",
            "name": "low",
            "task_type": "dynamic_rt",
            "deadline": 50,
            "arrival": 0,
            "subtasks": [
                {
                    "id": "s0",
                    "predecessors": [],
                    "successors": [],
                    "segments": [
                        {
                            "id": "seg0",
                            "index": 1,
                            "wcet": 4,
                            "required_resources": ["r0"],
                            "mapping_hint": "c0",
                        }
                    ],
                }
            ],
        },
        {
            "id": "med",
            "name": "med",
            "task_type": "dynamic_rt",
            "deadline": 20,
            "arrival": 0.5,
            "subtasks": [
                {
                    "id": "s0",
                    "predecessors": [],
                    "successors": [],
                    "segments": [
                        {
                            "id": "seg0",
                            "index": 1,
                            "wcet": 1,
                            "required_resources": ["r1"],
                            "mapping_hint": "c1",
                        }
                    ],
                }
            ],
        },
        {
            "id": "high",
            "name": "high",
            "task_type": "dynamic_rt",
            "deadline": 5,
            "arrival": 2,
            "subtasks": [
                {
                    "id": "s0",
                    "predecessors": [],
                    "successors": [],
                    "segments": [
                        {
                            "id": "seg0",
                            "index": 1,
                            "wcet": 1,
                            "required_resources": ["r0"],
                            "mapping_hint": "c0",
                        }
                    ],
                }
            ],
        },
    ]

    events, _ = _run_payload(payload)
    blocked = next(
        event
        for event in events
        if event["type"] == "SegmentBlocked" and str(event.get("job_id", "")).startswith("med@")
    )
    assert blocked["payload"]["reason"] == "system_ceiling_block"
    med_start = next(
        event["time"]
        for event in events
        if event["type"] == "SegmentStart" and str(event.get("job_id", "")).startswith("med@")
    )
    assert med_start >= 5.0


def test_scheduler_allow_preempt_parameter_can_disable_preemption() -> None:
    payload = _single_core_payload("mutex")
    payload["scheduler"]["params"] = {"allow_preempt": False}
    payload["tasks"] = [
        {
            "id": "low",
            "name": "low",
            "task_type": "dynamic_rt",
            "deadline": 20,
            "arrival": 0,
            "subtasks": [
                {
                    "id": "s0",
                    "predecessors": [],
                    "successors": [],
                    "segments": [{"id": "seg0", "index": 1, "wcet": 5}],
                }
            ],
        },
        {
            "id": "high",
            "name": "high",
            "task_type": "dynamic_rt",
            "deadline": 3,
            "arrival": 1,
            "subtasks": [
                {
                    "id": "s0",
                    "predecessors": [],
                    "successors": [],
                    "segments": [{"id": "seg0", "index": 1, "wcet": 1}],
                }
            ],
        },
    ]

    events, _ = _run_payload(payload)
    assert not any(event["type"] == "Preempt" for event in events)


def test_scheduler_tie_breaker_lifo_changes_equal_deadline_preempt_order() -> None:
    base = _single_core_payload("mutex")
    base["resources"] = []
    base["tasks"] = [
        {
            "id": "old",
            "name": "old",
            "task_type": "dynamic_rt",
            "deadline": 10,
            "arrival": 0,
            "subtasks": [
                {
                    "id": "s0",
                    "predecessors": [],
                    "successors": [],
                    "segments": [{"id": "seg0", "index": 1, "wcet": 4}],
                }
            ],
        },
        {
            "id": "new",
            "name": "new",
            "task_type": "dynamic_rt",
            "deadline": 9,
            "arrival": 1,
            "subtasks": [
                {
                    "id": "s0",
                    "predecessors": [],
                    "successors": [],
                    "segments": [{"id": "seg0", "index": 1, "wcet": 1}],
                }
            ],
        },
    ]

    fifo_payload = deepcopy(base)
    fifo_payload["scheduler"]["params"] = {"tie_breaker": "fifo"}
    lifo_payload = deepcopy(base)
    lifo_payload["scheduler"]["params"] = {"tie_breaker": "lifo"}

    fifo_events, _ = _run_payload(fifo_payload)
    lifo_events, _ = _run_payload(lifo_payload)

    assert not any(event["type"] == "Preempt" for event in fifo_events)
    assert any(event["type"] == "Preempt" for event in lifo_events)


def test_event_id_mode_supports_deterministic_and_random() -> None:
    payload = _single_core_payload("mutex")
    payload["resources"] = []
    payload["tasks"] = [
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
    ]

    deterministic = deepcopy(payload)
    deterministic["scheduler"]["params"] = {"event_id_mode": "deterministic"}
    events_a, _ = _run_payload(deterministic)
    events_b, _ = _run_payload(deterministic)
    assert [event["event_id"] for event in events_a] == [event["event_id"] for event in events_b]

    random_mode = deepcopy(payload)
    random_mode["scheduler"]["params"] = {"event_id_mode": "random"}
    random_a, _ = _run_payload(random_mode)
    random_b, _ = _run_payload(random_mode)
    assert [event["event_id"] for event in random_a] != [event["event_id"] for event in random_b]


def test_metric_report_includes_idle_cores() -> None:
    payload = {
        "version": "0.2",
        "platform": {
            "processor_types": [
                {"id": "CPU", "name": "cpu", "core_count": 2, "speed_factor": 1.0},
            ],
            "cores": [
                {"id": "c0", "type_id": "CPU", "speed_factor": 1.0},
                {"id": "c1", "type_id": "CPU", "speed_factor": 1.0},
            ],
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
                        "segments": [{"id": "seg0", "index": 1, "wcet": 1, "mapping_hint": "c0"}],
                    }
                ],
            }
        ],
        "scheduler": {"name": "edf", "params": {}},
        "sim": {"duration": 2, "seed": 7},
    }

    _, metrics = _run_payload(payload)
    assert set(metrics["core_utilization"]) == {"c0", "c1"}
    assert metrics["core_utilization"]["c1"] == pytest.approx(0.0)


def test_subscribe_before_build_keeps_stream_after_reset() -> None:
    loader = ConfigLoader()
    spec = loader.load(str(EXAMPLES / "at05_preempt.yaml"))
    engine = SimEngine()

    streamed = []
    engine.subscribe(streamed.append)
    engine.build(spec)
    engine.run()

    assert streamed
    assert len(streamed) == len(engine.events)
    assert any(event.type.value == "SegmentStart" for event in streamed)


def test_deadline_miss_triggers_at_deadline_boundary_without_other_events() -> None:
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
                "id": "t0",
                "name": "t0",
                "task_type": "dynamic_rt",
                "arrival": 0.0,
                "deadline": 2.0,
                "abort_on_miss": False,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [{"id": "seg0", "index": 1, "wcet": 5.0}],
                    }
                ],
            }
        ],
        "scheduler": {"name": "edf", "params": {}},
        "sim": {"duration": 8.0, "seed": 7},
    }

    events, _ = _run_payload(payload)
    miss_event = next(event for event in events if event["type"] == "DeadlineMiss")
    segment_end = next(event for event in events if event["type"] == "SegmentEnd")

    assert miss_event["time"] == pytest.approx(2.0, abs=1e-6)
    assert miss_event["time"] < segment_end["time"]


def test_abort_on_miss_forces_stop_without_job_completion() -> None:
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
                "id": "t0",
                "name": "t0",
                "task_type": "dynamic_rt",
                "arrival": 0.0,
                "deadline": 1.0,
                "abort_on_miss": True,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [
                            {
                                "id": "seg0",
                                "index": 1,
                                "wcet": 3.0,
                                "preemptible": False,
                            }
                        ],
                    }
                ],
            }
        ],
        "scheduler": {"name": "edf", "params": {}},
        "sim": {"duration": 5.0, "seed": 7},
    }

    events, metrics = _run_payload(payload)
    miss_time = next(event["time"] for event in events if event["type"] == "DeadlineMiss")
    starts = [event for event in events if event["type"] == "SegmentStart"]

    assert len(starts) == 1
    assert all(event["time"] <= miss_time + 1e-12 for event in starts)
    assert not any(event["type"] == "SegmentEnd" for event in events)
    assert not any(event["type"] == "JobComplete" for event in events)
    assert metrics["jobs_completed"] == 0


def test_abort_on_miss_removes_waiter_from_pip_queue() -> None:
    payload = {
        "version": "0.2",
        "platform": {
            "processor_types": [
                {"id": "CPU", "name": "cpu", "core_count": 1, "speed_factor": 1.0},
            ],
            "cores": [{"id": "c0", "type_id": "CPU", "speed_factor": 1.0}],
        },
        "resources": [{"id": "r0", "name": "lock", "bound_core_id": "c0", "protocol": "pip"}],
        "tasks": [
            {
                "id": "low",
                "name": "low",
                "task_type": "dynamic_rt",
                "arrival": 0.0,
                "deadline": 20.0,
                "abort_on_miss": False,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [
                            {"id": "seg0", "index": 1, "wcet": 4.0, "required_resources": ["r0"]}
                        ],
                    }
                ],
            },
            {
                "id": "wait",
                "name": "wait",
                "task_type": "dynamic_rt",
                "arrival": 0.1,
                "deadline": 0.5,
                "abort_on_miss": True,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [
                            {"id": "seg0", "index": 1, "wcet": 1.0, "required_resources": ["r0"]}
                        ],
                    }
                ],
            },
            {
                "id": "other",
                "name": "other",
                "task_type": "dynamic_rt",
                "arrival": 0.2,
                "deadline": 5.0,
                "abort_on_miss": False,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [
                            {"id": "seg0", "index": 1, "wcet": 1.0, "required_resources": ["r0"]}
                        ],
                    }
                ],
            },
        ],
        "scheduler": {"name": "edf", "params": {}},
        "sim": {"duration": 10.0, "seed": 7},
    }

    events, _ = _run_payload(payload)
    miss_event = next(
        event
        for event in events
        if event["type"] == "DeadlineMiss" and str(event.get("job_id", "")).startswith("wait@")
    )
    miss_time = miss_event["time"]
    assert any(
        event["type"] == "SegmentBlocked" and str(event.get("job_id", "")).startswith("wait@")
        for event in events
    )

    assert not any(
        event["type"] == "SegmentUnblocked"
        and str(event.get("job_id", "")).startswith("wait@")
        and event["time"] > miss_time
        for event in events
    )
    assert not any(
        event["type"] == "SegmentStart"
        and str(event.get("job_id", "")).startswith("wait@")
        and event["time"] > miss_time
        for event in events
    )

    low_release = next(
        event["time"]
        for event in events
        if event["type"] == "ResourceRelease" and str(event.get("job_id", "")).startswith("low@")
    )
    other_start = next(
        event["time"]
        for event in events
        if event["type"] == "SegmentStart" and str(event.get("job_id", "")).startswith("other@")
    )
    assert other_start >= low_release - 1e-9
