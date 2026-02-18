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


def test_runtime_bound_core_violation_emits_error_and_aborts_job() -> None:
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
        "resources": [{"id": "r0", "name": "lock", "bound_core_id": "c0", "protocol": "mutex"}],
        "tasks": [
            {
                "id": "t0",
                "name": "task",
                "task_type": "dynamic_rt",
                "arrival": 0.0,
                "deadline": 10.0,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [{"id": "seg0", "index": 1, "wcet": 1.0, "required_resources": ["r0"]}],
                    }
                ],
            }
        ],
        "scheduler": {"name": "edf", "params": {}},
        "sim": {"duration": 5.0, "seed": 9},
    }
    loader = ConfigLoader()
    spec = loader.load_data(payload)
    # 运行期兜底验证：人为破坏已通过校验的映射，触发 bound_core_violation。
    spec.tasks[0].subtasks[0].segments[0].mapping_hint = "c1"

    engine = SimEngine()
    engine.build(spec)
    engine.run()
    events = [event.model_dump(mode="json") for event in engine.events]

    blocked = next(event for event in events if event["type"] == "SegmentBlocked")
    assert blocked["payload"]["reason"] == "bound_core_violation"
    error = next(event for event in events if event["type"] == "Error")
    assert error["payload"]["reason"] == "bound_core_violation"
    assert error["job_id"].startswith("t0@")
    assert not any(event["type"] == "SegmentStart" for event in events)
    assert not any(event["type"] == "JobComplete" for event in events)


def test_at04_deadline_miss() -> None:
    events, metrics = _run_example("at04_deadline_miss.yaml")
    assert any(e["type"] == "DeadlineMiss" for e in events)
    assert metrics["deadline_miss_count"] >= 1


def test_at05_preempt() -> None:
    events, metrics = _run_example("at05_preempt.yaml")
    assert any(e["type"] == "Preempt" for e in events)
    assert metrics["preempt_count"] >= 1
    assert metrics["scheduler_preempt_count"] >= 1
    assert metrics["forced_preempt_count"] == 0


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


def test_at08_migration() -> None:
    events, metrics = _run_example("at08_migration.yaml")
    migrate_events = [
        event
        for event in events
        if event["type"] == "Migrate" and str(event.get("job_id", "")).startswith("low@")
    ]
    assert migrate_events
    assert metrics["migrate_count"] >= 1
    assert any(
        event["payload"].get("from_core") == "c0" and event["payload"].get("to_core") == "c1"
        for event in migrate_events
    )

    low_starts = [
        event["core_id"]
        for event in events
        if event["type"] == "SegmentStart" and str(event.get("job_id", "")).startswith("low@")
    ]
    assert set(low_starts) >= {"c0", "c1"}


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
    assert blocked["payload"]["priority_domain"] == "absolute_deadline"
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
    assert metrics["jobs_aborted"] == 1
    assert metrics["forced_preempt_count"] == 1
    assert metrics["scheduler_preempt_count"] == 0
    assert metrics["preempt_count"] == 1


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


def test_scheduler_and_forced_preempt_metrics_are_split() -> None:
    scheduler_events, scheduler_metrics = _run_example("at05_preempt.yaml")
    assert any(event["type"] == "Preempt" for event in scheduler_events)
    assert scheduler_metrics["scheduler_preempt_count"] >= 1
    assert scheduler_metrics["forced_preempt_count"] == 0

    abort_payload = {
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
                        "segments": [{"id": "seg0", "index": 1, "wcet": 3.0}],
                    }
                ],
            }
        ],
        "scheduler": {"name": "edf", "params": {}},
        "sim": {"duration": 5.0, "seed": 13},
    }
    abort_events, abort_metrics = _run_payload(abort_payload)
    assert any(event["type"] == "Preempt" for event in abort_events)
    assert abort_metrics["forced_preempt_count"] == 1
    assert abort_metrics["scheduler_preempt_count"] == 0
    assert abort_metrics["jobs_aborted"] == 1


def test_dispatch_retry_same_tick_after_block_keeps_cpu_busy() -> None:
    payload = {
        "version": "0.2",
        "platform": {
            "processor_types": [
                {"id": "CPU", "name": "cpu", "core_count": 1, "speed_factor": 1.0},
            ],
            "cores": [{"id": "c0", "type_id": "CPU", "speed_factor": 1.0}],
        },
        "resources": [{"id": "r0", "name": "lock", "bound_core_id": "c0", "protocol": "mutex"}],
        "tasks": [
            {
                "id": "low",
                "name": "low",
                "task_type": "dynamic_rt",
                "arrival": 0.0,
                "deadline": 30.0,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [{"id": "seg0", "index": 1, "wcet": 5.0, "required_resources": ["r0"]}],
                    }
                ],
            },
            {
                "id": "high",
                "name": "high",
                "task_type": "dynamic_rt",
                "arrival": 1.0,
                "deadline": 2.0,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [{"id": "seg0", "index": 1, "wcet": 1.0, "required_resources": ["r0"]}],
                    }
                ],
            },
        ],
        "scheduler": {"name": "edf", "params": {}},
        "sim": {"duration": 6.0, "seed": 7},
    }

    events, _ = _run_payload(payload)
    blocked_time = next(
        event["time"]
        for event in events
        if event["type"] == "SegmentBlocked" and str(event.get("job_id", "")).startswith("high@")
    )
    low_starts = [
        event["time"]
        for event in events
        if event["type"] == "SegmentStart" and str(event.get("job_id", "")).startswith("low@")
    ]
    assert len(low_starts) >= 2
    assert low_starts[1] == pytest.approx(blocked_time)


def test_horizon_truncation_emits_segment_end_and_accounts_utilization() -> None:
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
                "deadline": 20.0,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [{"id": "seg0", "index": 1, "wcet": 10.0}],
                    }
                ],
            }
        ],
        "scheduler": {"name": "edf", "params": {}},
        "sim": {"duration": 20.0, "seed": 11},
    }
    loader = ConfigLoader()
    spec = loader.load_data(payload)
    engine = SimEngine()
    engine.build(spec)
    engine.run(until=5.0)
    events = [event.model_dump(mode="json") for event in engine.events]
    metrics = engine.metric_report()

    truncated_end = next(event for event in events if event["type"] == "SegmentEnd")
    assert truncated_end["time"] == pytest.approx(5.0)
    assert truncated_end["payload"]["ended_by"] == "horizon"
    assert truncated_end["payload"]["truncated"] is True
    assert metrics["max_time"] == pytest.approx(5.0)
    assert metrics["core_utilization"]["c0"] == pytest.approx(1.0)
    assert metrics["jobs_completed"] == 0


def test_release_model_supports_periodic_sporadic_and_aperiodic() -> None:
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
                "id": "periodic",
                "name": "periodic",
                "task_type": "time_deterministic",
                "arrival": 0.0,
                "period": 5.0,
                "deadline": 5.0,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [{"id": "seg0", "index": 1, "wcet": 0.2}],
                    }
                ],
            },
            {
                "id": "sporadic",
                "name": "sporadic",
                "task_type": "dynamic_rt",
                "arrival": 0.0,
                "deadline": 3.0,
                "min_inter_arrival": 3.0,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [{"id": "seg0", "index": 1, "wcet": 0.2}],
                    }
                ],
            },
            {
                "id": "aperiodic",
                "name": "aperiodic",
                "task_type": "non_rt",
                "arrival": 1.0,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [{"id": "seg0", "index": 1, "wcet": 0.2}],
                    }
                ],
            },
        ],
        "scheduler": {"name": "edf", "params": {}},
        "sim": {"duration": 13.0, "seed": 5},
    }

    events, _ = _run_payload(payload)
    release_map: dict[str, list[float]] = {"periodic": [], "sporadic": [], "aperiodic": []}
    for event in events:
        if event["type"] != "JobReleased":
            continue
        task_id = event["payload"]["task_id"]
        if task_id in release_map:
            release_map[task_id].append(event["time"])

    assert release_map["periodic"] == pytest.approx([0.0, 5.0, 10.0])
    assert release_map["sporadic"] == pytest.approx([0.0, 3.0, 6.0, 9.0, 12.0])
    assert release_map["aperiodic"] == pytest.approx([1.0])


def test_time_deterministic_phase_offset_and_release_offsets() -> None:
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
                "id": "det",
                "name": "det",
                "task_type": "time_deterministic",
                "arrival": 0.0,
                "phase_offset": 1.0,
                "period": 4.0,
                "deadline": 4.0,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [
                            {
                                "id": "seg0",
                                "index": 1,
                                "wcet": 0.1,
                                "release_offsets": [0.5, 1.5],
                            }
                        ],
                    }
                ],
            }
        ],
        "scheduler": {"name": "edf", "params": {}},
        "sim": {"duration": 12.0, "seed": 19},
    }

    events, _ = _run_payload(payload)

    release_times = [event["time"] for event in events if event["type"] == "JobReleased"]
    assert release_times == pytest.approx([1.0, 5.0, 9.0])

    ready_events = [event for event in events if event["type"] == "SegmentReady"]
    assert [event["time"] for event in ready_events] == pytest.approx([1.5, 6.5, 9.5])
    assert [event["payload"]["deterministic_offset_index"] for event in ready_events] == [0, 1, 0]
    assert [event["payload"]["deterministic_window_id"] for event in ready_events] == [0, 1, 2]
    assert [event["payload"]["deterministic_ready_time"] for event in ready_events] == pytest.approx(
        [1.5, 6.5, 9.5]
    )

    start_events = [event for event in events if event["type"] == "SegmentStart"]
    assert [event["payload"]["deterministic_offset_index"] for event in start_events] == [0, 1, 0]
    assert [event["payload"]["deterministic_window_id"] for event in start_events] == [0, 1, 2]


def test_time_deterministic_segment_stays_on_mapping_core() -> None:
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
                "id": "det",
                "name": "det",
                "task_type": "time_deterministic",
                "arrival": 0.0,
                "phase_offset": 0.0,
                "period": 2.0,
                "deadline": 2.0,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [
                            {
                                "id": "seg0",
                                "index": 1,
                                "wcet": 0.5,
                                "mapping_hint": "c0",
                            }
                        ],
                    }
                ],
            },
            {
                "id": "bg",
                "name": "bg",
                "task_type": "dynamic_rt",
                "arrival": 0.0,
                "period": 1.0,
                "deadline": 1.0,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [{"id": "seg0", "index": 1, "wcet": 0.3, "mapping_hint": "c1"}],
                    }
                ],
            },
        ],
        "scheduler": {"name": "edf", "params": {}},
        "sim": {"duration": 6.0, "seed": 101},
    }

    events, _ = _run_payload(payload)
    det_starts = [
        event for event in events if event["type"] == "SegmentStart" and str(event.get("job_id", "")).startswith("det@")
    ]
    assert det_starts
    assert all(event["core_id"] == "c0" for event in det_starts)
    assert not any(
        event["type"] == "Migrate" and str(event.get("job_id", "")).startswith("det@")
        for event in events
    )


def test_abort_cancel_emits_segment_unblocked_for_woken_waiter() -> None:
    payload = {
        "version": "0.2",
        "platform": {
            "processor_types": [
                {"id": "CPU", "name": "cpu", "core_count": 1, "speed_factor": 1.0},
            ],
            "cores": [{"id": "c0", "type_id": "CPU", "speed_factor": 1.0}],
        },
        "resources": [{"id": "r0", "name": "lock", "bound_core_id": "c0", "protocol": "mutex"}],
        "tasks": [
            {
                "id": "holder",
                "name": "holder",
                "task_type": "dynamic_rt",
                "arrival": 0.0,
                "deadline": 0.5,
                "abort_on_miss": True,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [
                            {"id": "seg0", "index": 1, "wcet": 3.0, "required_resources": ["r0"]}
                        ],
                    }
                ],
            },
            {
                "id": "waiter",
                "name": "waiter",
                "task_type": "dynamic_rt",
                "arrival": 0.1,
                "deadline": 0.2,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [
                            {"id": "seg0", "index": 1, "wcet": 0.2, "required_resources": ["r0"]}
                        ],
                    }
                ],
            },
        ],
        "scheduler": {"name": "edf", "params": {}},
        "sim": {"duration": 4.0, "seed": 23},
    }

    events, _ = _run_payload(payload)
    assert any(
        event["type"] == "SegmentBlocked" and str(event.get("job_id", "")).startswith("waiter@")
        for event in events
    )

    miss_time = next(
        event["time"]
        for event in events
        if event["type"] == "DeadlineMiss" and str(event.get("job_id", "")).startswith("holder@")
    )
    wake_event = next(
        event
        for event in events
        if event["type"] == "SegmentUnblocked" and str(event.get("job_id", "")).startswith("waiter@")
    )
    release_event = next(
        event
        for event in events
        if event["type"] == "ResourceRelease"
        and str(event.get("job_id", "")).startswith("holder@")
        and event.get("resource_id") == "r0"
    )
    assert wake_event["payload"]["reason"] == "cancel_segment"
    assert wake_event["time"] == pytest.approx(miss_time)
    assert release_event["payload"]["reason"] == "cancel_segment"
    assert release_event["time"] == pytest.approx(miss_time)

    waiter_start = next(
        event["time"]
        for event in events
        if event["type"] == "SegmentStart" and str(event.get("job_id", "")).startswith("waiter@")
    )
    assert waiter_start >= wake_event["time"] - 1e-9
