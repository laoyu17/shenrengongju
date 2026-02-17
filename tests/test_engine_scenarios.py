from __future__ import annotations

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
