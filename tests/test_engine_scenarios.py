from __future__ import annotations

from pathlib import Path

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
