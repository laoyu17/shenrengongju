from __future__ import annotations

from rtos_sim.analysis.audit_checks.deadlock_checks import evaluate_wait_for_deadlock


def test_wait_for_deadlock_detects_two_segment_cycle() -> None:
    outcome = evaluate_wait_for_deadlock(
        [
            {
                "event_id": "a1",
                "type": "ResourceAcquire",
                "resource_id": "r0",
                "payload": {"segment_key": "job_a@0:s0:seg0"},
            },
            {
                "event_id": "b1",
                "type": "ResourceAcquire",
                "resource_id": "r1",
                "payload": {"segment_key": "job_b@0:s0:seg0"},
            },
            {
                "event_id": "a2",
                "type": "SegmentBlocked",
                "resource_id": "r1",
                "payload": {
                    "segment_key": "job_a@0:s0:seg0",
                    "reason": "resource_busy",
                    "owner_segment": "job_b@0:s0:seg0",
                },
            },
            {
                "event_id": "b2",
                "type": "SegmentBlocked",
                "resource_id": "r0",
                "payload": {
                    "segment_key": "job_b@0:s0:seg0",
                    "reason": "resource_busy",
                    "owner_segment": "job_a@0:s0:seg0",
                },
            },
        ]
    )

    assert outcome["passed"] is False
    assert outcome["issues"][0]["rule"] == "wait_for_deadlock"
    cycle = outcome["issues"][0]["samples"][0]["cycle_segments"]
    assert set(cycle) == {"job_a@0:s0:seg0", "job_b@0:s0:seg0"}


def test_wait_for_deadlock_clears_aborted_waiter_before_new_block() -> None:
    outcome = evaluate_wait_for_deadlock(
        [
            {
                "event_id": "a1",
                "type": "SegmentBlocked",
                "job_id": "job_a@0",
                "payload": {
                    "segment_key": "job_a@0:s0:seg0",
                    "reason": "resource_busy",
                    "owner_segment": "job_b@0:s0:seg0",
                },
            },
            {
                "event_id": "a2",
                "type": "DeadlineMiss",
                "job_id": "job_a@0",
                "payload": {"abort_on_miss": True},
            },
            {
                "event_id": "b1",
                "type": "SegmentBlocked",
                "job_id": "job_b@0",
                "payload": {
                    "segment_key": "job_b@0:s0:seg0",
                    "reason": "resource_busy",
                    "owner_segment": "job_a@0:s0:seg0",
                },
            },
        ]
    )

    assert outcome["passed"] is True
    assert outcome["issues"] == []
