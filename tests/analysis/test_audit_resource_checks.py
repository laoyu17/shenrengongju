from __future__ import annotations

from rtos_sim.analysis.audit_checks.resource_checks import (
    evaluate_abort_cancel_release_visibility,
    evaluate_resource_partial_hold_on_block,
    evaluate_resource_release_balance,
)


def test_resource_release_balance_detects_segment_key_mismatch() -> None:
    outcome = evaluate_resource_release_balance(
        [
            {
                "event_id": "e1",
                "type": "ResourceAcquire",
                "job_id": "t0@0",
                "segment_id": "seg0",
                "resource_id": "r0",
                "payload": {"segment_key": "t0@0:s0:seg0"},
            },
            {
                "event_id": "e2",
                "type": "ResourceRelease",
                "job_id": "t0@0",
                "segment_id": "seg0",
                "resource_id": "r0",
                "payload": {"segment_key": "t0@0:s1:seg0"},
            },
        ]
    )

    assert outcome["passed"] is False
    assert outcome["issues"] and outcome["issues"][0]["rule"] == "resource_release_balance"


def test_abort_cancel_release_visibility_requires_cancel_release() -> None:
    outcome = evaluate_abort_cancel_release_visibility(
        [
            {
                "event_id": "e1",
                "type": "ResourceAcquire",
                "job_id": "holder@0",
                "resource_id": "r0",
                "payload": {"segment_key": "holder@0:s0:seg0"},
            },
            {
                "event_id": "e2",
                "type": "Preempt",
                "job_id": "holder@0",
                "payload": {"reason": "abort_on_miss"},
            },
        ]
    )

    assert outcome["passed"] is False
    assert outcome["issues"][0]["rule"] == "abort_cancel_release_visibility"
    assert "holder@0" in outcome["issues"][0]["job_ids"]


def test_resource_partial_hold_on_block_flags_atomic_rollback_leak() -> None:
    outcome = evaluate_resource_partial_hold_on_block(
        [
            {
                "event_id": "e1",
                "type": "ResourceAcquire",
                "job_id": "w@0",
                "resource_id": "r0",
                "payload": {"segment_key": "w@0:s0:seg0"},
            },
            {
                "event_id": "e2",
                "type": "SegmentBlocked",
                "job_id": "w@0",
                "resource_id": "r1",
                "payload": {
                    "segment_key": "w@0:s0:seg0",
                    "reason": "resource_busy",
                    "resource_acquire_policy": "atomic_rollback",
                },
            },
        ]
    )

    assert outcome["passed"] is False
    assert outcome["issues"][0]["rule"] == "resource_partial_hold_on_block"
