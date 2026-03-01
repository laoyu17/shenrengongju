from __future__ import annotations

from dataclasses import dataclass

import pytest

from rtos_sim.ui.controllers.timeline_controller import TimelineController


@dataclass
class _Owner:
    _seen_event_ids: set[str]
    _max_time: float
    _job_deadlines: dict[str, float | None]
    _segment_resources: dict[str, set[str]]
    _active_segments: dict[str, dict]
    _metrics: list[str]
    _core_to_y: dict[str, float]


def _make_owner() -> _Owner:
    return _Owner(
        _seen_event_ids=set(),
        _max_time=0.0,
        _job_deadlines={},
        _segment_resources={},
        _active_segments={},
        _metrics=[],
        _core_to_y={"c0": 0.0},
    )


def test_on_event_batch_skips_duplicate_event_id() -> None:
    owner = _make_owner()
    controller = TimelineController(owner)

    controller.on_event_batch(
        [
            {
                "event_id": "dup",
                "type": "ResourceAcquire",
                "resource_id": "r0",
                "payload": {"segment_key": "j@0:s0:seg0"},
            },
            {
                "event_id": "dup",
                "type": "ResourceAcquire",
                "resource_id": "r1",
                "payload": {"segment_key": "j@0:s0:seg0"},
            },
        ]
    )

    assert owner._seen_event_ids == {"dup"}
    assert owner._segment_resources["j@0:s0:seg0"] == {"r0"}


def test_consume_segment_end_emits_completed_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _make_owner()
    controller = TimelineController(owner)

    metas = []
    monkeypatch.setattr(controller, "draw_gantt_segment", lambda meta: metas.append(meta))
    monkeypatch.setattr(controller, "draw_preempt_marker", lambda *_args: None)

    controller.on_event_batch(
        [
            {
                "event_id": "e0",
                "type": "JobReleased",
                "job_id": "job@0",
                "time": 0.0,
                "payload": {"absolute_deadline": 5.0},
            },
            {
                "event_id": "e1",
                "type": "SegmentStart",
                "job_id": "job@0",
                "segment_id": "seg0",
                "core_id": "c0",
                "time": 1.0,
                "payload": {
                    "segment_key": "job@0:s0:seg0",
                    "estimated_finish": 4.0,
                    "execution_time": 3.0,
                },
            },
            {
                "event_id": "e2",
                "type": "SegmentEnd",
                "job_id": "job@0",
                "segment_id": "seg0",
                "core_id": "c0",
                "time": 4.0,
                "payload": {"segment_key": "job@0:s0:seg0"},
            },
        ]
    )

    assert len(metas) == 1
    assert metas[0].status == "Completed"
    assert metas[0].duration == pytest.approx(3.0)
    assert owner._active_segments == {}
    assert any(line.startswith("[Segment] job@0:s0:seg0") for line in owner._metrics)


def test_preempt_event_marks_segment_preempted(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _make_owner()
    controller = TimelineController(owner)

    metas = []
    markers = []
    monkeypatch.setattr(controller, "draw_gantt_segment", lambda meta: metas.append(meta))
    monkeypatch.setattr(controller, "draw_preempt_marker", lambda x, core_id: markers.append((x, core_id)))

    controller.on_event_batch(
        [
            {
                "event_id": "s1",
                "type": "SegmentStart",
                "job_id": "job@1",
                "segment_id": "seg1",
                "core_id": "c0",
                "time": 2.0,
                "payload": {
                    "segment_key": "job@1:s0:seg1",
                    "estimated_finish": 5.0,
                    "execution_time": 3.0,
                },
            },
            {
                "event_id": "p1",
                "type": "Preempt",
                "job_id": "job@1",
                "segment_id": "seg1",
                "core_id": "c0",
                "time": 3.0,
                "payload": {"segment_key": "job@1:s0:seg1"},
            },
        ]
    )

    assert len(metas) == 1
    assert metas[0].status == "Preempted"
    assert metas[0].remaining_after_preempt == pytest.approx(2.0)
    assert markers == [(3.0, "c0")]
    assert any(line.startswith("[Preempt] job@1:s0:seg1") for line in owner._metrics)
