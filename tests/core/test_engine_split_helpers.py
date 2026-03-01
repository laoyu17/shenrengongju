from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

from rtos_sim.core.engine_abort import abort_job, protocols_for_segment
from rtos_sim.core.engine_dispatch import apply_dispatch
from rtos_sim.core.engine_release import (
    mark_segment_ready,
    queue_segment_ready,
    resolve_deterministic_ready_info,
)
from rtos_sim.core.engine_runtime import (
    check_deadline_miss,
    process_segment_ready_heap,
    schedule_until_stable,
)
from rtos_sim.events import EventType


@dataclass
class DummySegment:
    key: str
    job_id: str
    task_id: str = "t0"
    subtask_id: str = "s0"
    segment_id: str = "seg0"
    required_resources: list[str] = field(default_factory=list)
    mapping_hint: str | None = None
    finished: bool = False
    blocked: bool = False
    waiting_resource: str | None = None
    running_on: str | None = None
    started_at: float | None = None
    remaining_time: float = 1.0
    preemptible: bool = True
    absolute_deadline: float | None = 10.0
    task_period: float | None = 5.0
    release_time: float = 0.0
    effective_priority: float = 1.0
    deterministic_window_id: int | None = None
    deterministic_offset_index: int | None = None
    deterministic_ready_time: float | None = None


@dataclass
class DummyCore:
    core_id: str
    speed: float = 1.0
    running_segment_key: str | None = None
    running_since: float | None = None
    finish_time: float | None = None


class EventRecorder:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def publish(self, **kwargs: object) -> None:
        self.events.append(kwargs)


class SequenceProtocol:
    def __init__(self) -> None:
        self.release_calls: list[tuple[str, str]] = []
        self.cancel_calls: list[str] = []

    def request(
        self,
        segment_key: str,
        resource_id: str,
        core_id: str,
        request_priority: float,
    ) -> SimpleNamespace:
        if resource_id == "r0":
            return SimpleNamespace(granted=True, reason=None, priority_updates={}, metadata={})
        return SimpleNamespace(
            granted=False,
            reason="resource_busy",
            priority_updates={},
            metadata={"owner_segment": "holder@0:s0:seg0"},
        )

    def release(self, segment_key: str, resource_id: str) -> SimpleNamespace:
        self.release_calls.append((segment_key, resource_id))
        return SimpleNamespace(priority_updates={}, woken=[], metadata={})

    def cancel_segment(self, segment_key: str) -> SimpleNamespace:
        self.cancel_calls.append(segment_key)
        if segment_key.startswith("job@0"):
            return SimpleNamespace(
                priority_updates={},
                woken=["wait@0:s0:seg0"],
                metadata={"reason": "cancel_segment"},
            )
        return SimpleNamespace(priority_updates={}, woken=[], metadata={})


def test_resolve_deterministic_ready_info_uses_hyper_period_window() -> None:
    task = SimpleNamespace(
        task_type=SimpleNamespace(value="time_deterministic"),
        arrival=0.0,
        phase_offset=0.0,
    )
    engine = SimpleNamespace(
        _deterministic_hyper_period=10.0,
        _release_base_time=lambda _: 0.0,
    )

    ready_time, window_id, offset_index = resolve_deterministic_ready_info(
        engine,
        task=task,
        release_idx=3,
        release_time=16.0,
        release_offsets=[0.5, 1.5],
    )

    assert ready_time == 17.5
    assert window_id == 1
    assert offset_index == 1


def test_queue_and_mark_segment_ready_keep_pending_state_consistent() -> None:
    segment = DummySegment(
        key="job@0:s0:seg0",
        job_id="job@0",
        deterministic_ready_time=5.0,
        deterministic_window_id=2,
        deterministic_offset_index=1,
    )
    recorder = EventRecorder()
    scheduler_calls: list[str] = []

    engine = SimpleNamespace(
        _segments={segment.key: segment},
        _aborted_jobs=set(),
        _pending_segment_ready_times={},
        _segment_ready_heap=[],
        _ready=set(),
        _scheduler=SimpleNamespace(on_segment_ready=scheduler_calls.append),
        _event_bus=recorder,
    )

    queue_segment_ready(engine, segment.key, now=1.0)
    queue_segment_ready(engine, segment.key, now=1.0)

    assert engine._pending_segment_ready_times[segment.key] == 5.0
    assert len(engine._segment_ready_heap) == 1

    mark_segment_ready(engine, segment.key, now=5.0)

    assert scheduler_calls == [segment.key]
    assert segment.blocked is False
    assert segment.waiting_resource is None
    assert segment.key in engine._ready
    published = recorder.events[-1]
    assert published["event_type"] == EventType.SEGMENT_READY
    assert published["payload"]["deterministic_window_id"] == 2


def test_process_segment_ready_heap_discards_stale_entry() -> None:
    calls: list[tuple[str, float]] = []
    engine = SimpleNamespace(
        _segment_ready_heap=[(1.0, "seg"), (2.0, "seg")],
        _pending_segment_ready_times={"seg": 2.0},
        _mark_segment_ready=lambda segment_key, now: calls.append((segment_key, now)),
    )

    process_segment_ready_heap(engine, now=2.0)

    assert calls == [("seg", 2.0)]
    assert "seg" not in engine._pending_segment_ready_times


def test_schedule_until_stable_emits_retry_limit_error_when_starved() -> None:
    recorder = EventRecorder()
    schedule_calls: list[float] = []

    def always_changed(now: float) -> tuple[float, bool]:
        schedule_calls.append(now)
        return now, True

    engine = SimpleNamespace(
        SCHEDULE_RETRY_LIMIT=2,
        _schedule=always_changed,
        _ready={"seg"},
        _cores={"c0": DummyCore(core_id="c0")},
        _event_bus=recorder,
    )

    returned_now = schedule_until_stable(engine, now=0.0)

    assert returned_now == 0.0
    assert len(schedule_calls) == 2
    error_event = recorder.events[-1]
    assert error_event["event_type"] == EventType.ERROR
    assert error_event["payload"]["reason"] == "schedule_retry_limit"


def test_check_deadline_miss_marks_state_and_aborts_when_configured() -> None:
    recorder = EventRecorder()
    abort_calls: list[tuple[str, float]] = []
    state = SimpleNamespace(
        completed=False,
        missed_deadline=False,
        absolute_deadline=1.0,
        job_id="job@0",
    )
    job_runtime = SimpleNamespace(
        state=state,
        task=SimpleNamespace(abort_on_miss=True),
    )
    engine = SimpleNamespace(
        _jobs={"job@0": job_runtime},
        _event_bus=recorder,
        _abort_job=lambda job_id, now: abort_calls.append((job_id, now)),
    )

    check_deadline_miss(engine, now=1.5)

    assert state.missed_deadline is True
    assert abort_calls == [("job@0", 1.5)]
    miss_event = recorder.events[-1]
    assert miss_event["event_type"] == EventType.DEADLINE_MISS


def test_apply_dispatch_mapping_hint_violation_aborts_job() -> None:
    recorder = EventRecorder()
    abort_calls: list[tuple[str, float, dict[str, object]]] = []
    segment = DummySegment(key="job@0:s0:seg0", job_id="job@0", mapping_hint="c1")

    def _abort(job_id: str, now: float, **kwargs: object) -> None:
        abort_calls.append((job_id, now, kwargs))

    engine = SimpleNamespace(
        _aborted_jobs=set(),
        _cores={"c0": DummyCore(core_id="c0")},
        _ready={segment.key},
        _segments={segment.key: segment},
        _held_resources={segment.key: set()},
        _event_bus=recorder,
        _abort_job=_abort,
        _etm=SimpleNamespace(estimate=lambda *args, **kwargs: 1.0),
        _overheads=SimpleNamespace(
            on_migration=lambda *args, **kwargs: 0.0,
            on_context_switch=lambda *args, **kwargs: 0.0,
        ),
    )

    outcome = apply_dispatch(engine, "job@0", None, "c0", now=0.0)

    assert outcome == "error"
    assert abort_calls[0][0] == "job@0"
    assert abort_calls[0][2]["preempt_reason"] == "abort_on_error"
    assert recorder.events[0]["event_type"] == EventType.ERROR


def test_apply_dispatch_atomic_rollback_releases_partial_hold() -> None:
    recorder = EventRecorder()
    protocol = SequenceProtocol()
    segment = DummySegment(
        key="job@0:s0:seg0",
        job_id="job@0",
        required_resources=["r0", "r1"],
    )

    engine = SimpleNamespace(
        _aborted_jobs=set(),
        _cores={"c0": DummyCore(core_id="c0")},
        _ready={segment.key},
        _segments={segment.key: segment},
        _held_resources={segment.key: set()},
        _resource_acquire_policy="atomic_rollback",
        _event_bus=recorder,
        _protocol_for_resource=lambda _rid: protocol,
        _apply_priority_updates=lambda _updates: None,
        _abort_job=lambda *_args, **_kwargs: None,
        _etm=SimpleNamespace(estimate=lambda *args, **kwargs: 1.0),
        _overheads=SimpleNamespace(
            on_migration=lambda *args, **kwargs: 0.0,
            on_context_switch=lambda *args, **kwargs: 0.0,
        ),
    )

    outcome = apply_dispatch(engine, "job@0", None, "c0", now=0.0)

    assert outcome == "blocked"
    assert segment.blocked is True
    assert segment.waiting_resource == "r1"
    assert engine._held_resources[segment.key] == set()
    blocked = next(event for event in recorder.events if event["event_type"] == EventType.SEGMENT_BLOCKED)
    assert blocked["payload"]["rollback_applied"] is True
    assert blocked["payload"]["rollback_released_resources"] == ["r0"]


def test_abort_job_releases_resources_and_unblocks_waiters() -> None:
    recorder = EventRecorder()
    protocol = SequenceProtocol()
    preempt_calls: list[tuple[str, dict[str, object]]] = []
    unregister_calls: list[str] = []

    main_segment = DummySegment(
        key="job@0:s0:seg0",
        job_id="job@0",
        required_resources=["r0"],
        blocked=True,
        waiting_resource="r0",
        running_on="c0",
    )
    waiting_segment = DummySegment(
        key="wait@0:s0:seg0",
        job_id="wait@0",
        blocked=True,
        waiting_resource="r0",
    )

    core = DummyCore(core_id="c0", running_segment_key=main_segment.key, running_since=0.0, finish_time=5.0)

    engine = SimpleNamespace(
        _aborted_jobs=set(),
        _segments={main_segment.key: main_segment, waiting_segment.key: waiting_segment},
        _cores={"c0": core},
        _ready={main_segment.key},
        _pending_segment_ready_times={main_segment.key: 1.0},
        _held_resources={main_segment.key: {"r0"}, waiting_segment.key: set()},
        _resource_protocols={"r0": protocol},
        _protocol=protocol,
        _resource_bound_cores={"r0": "c0"},
        _event_bus=recorder,
        _apply_priority_updates=lambda _updates: None,
        _unregister_active_job_priority=lambda job_id: unregister_calls.append(job_id),
    )

    def _apply_preempt(core_id: str, now: float, **kwargs: object) -> None:
        preempt_calls.append((core_id, kwargs))
        core_ref = engine._cores[core_id]
        core_ref.running_segment_key = None
        core_ref.running_since = None
        core_ref.finish_time = None

    engine._apply_preempt = _apply_preempt

    abort_job(engine, "job@0", now=2.0)

    assert "job@0" in engine._aborted_jobs
    assert main_segment.finished is True
    assert main_segment.key not in engine._ready
    assert main_segment.key not in engine._pending_segment_ready_times
    assert engine._held_resources[main_segment.key] == set()
    assert waiting_segment.key in engine._ready
    assert waiting_segment.blocked is False
    assert waiting_segment.waiting_resource is None
    assert unregister_calls == ["job@0"]
    assert preempt_calls and preempt_calls[0][1]["force"] is True
    release = next(event for event in recorder.events if event["event_type"] == EventType.RESOURCE_RELEASE)
    assert release["payload"]["reason"] == "cancel_segment"


def test_protocols_for_segment_deduplicates_protocol_instances() -> None:
    protocol = SequenceProtocol()
    segment = DummySegment(
        key="job@0:s0:seg0",
        job_id="job@0",
        required_resources=["r0", "r1"],
    )
    engine = SimpleNamespace(
        _resource_protocols={"r0": protocol, "r1": protocol},
        _protocol=None,
    )

    resolved = protocols_for_segment(engine, segment)

    assert resolved == [protocol]
