from __future__ import annotations

from rtos_sim.analysis import build_audit_report


def test_audit_passes_for_balanced_resource_events() -> None:
    events = [
        {
            "event_id": "e1",
            "type": "ResourceAcquire",
            "job_id": "t0@0",
            "segment_id": "seg0",
            "resource_id": "r0",
            "payload": {},
        },
        {
            "event_id": "e2",
            "type": "ResourceRelease",
            "job_id": "t0@0",
            "segment_id": "seg0",
            "resource_id": "r0",
            "payload": {},
        },
    ]

    report = build_audit_report(events, scheduler_name="edf")
    assert report["status"] == "pass"
    assert report["issue_count"] == 0


def test_audit_detects_missing_cancel_release_for_aborted_job() -> None:
    events = [
        {
            "event_id": "e1",
            "type": "ResourceAcquire",
            "job_id": "holder@0",
            "segment_id": "seg0",
            "resource_id": "r0",
            "payload": {},
        },
        {
            "event_id": "e2",
            "type": "DeadlineMiss",
            "job_id": "holder@0",
            "payload": {"abort_on_miss": True},
        },
    ]

    report = build_audit_report(events, scheduler_name="edf")
    assert report["status"] == "fail"
    assert any(issue["rule"] == "abort_cancel_release_visibility" for issue in report["issues"])


def test_audit_detects_pcp_priority_domain_mismatch() -> None:
    events = [
        {
            "event_id": "e1",
            "type": "SegmentBlocked",
            "job_id": "task@0",
            "payload": {
                "reason": "system_ceiling_block",
                "priority_domain": "fixed_priority",
            },
        }
    ]

    report = build_audit_report(events, scheduler_name="edf")
    assert report["status"] == "fail"
    assert any(issue["rule"] == "pcp_priority_domain_alignment" for issue in report["issues"])


def test_audit_detects_non_negative_system_ceiling_in_edf() -> None:
    events = [
        {
            "event_id": "e1",
            "type": "SegmentBlocked",
            "job_id": "task@0",
            "payload": {
                "reason": "system_ceiling_block",
                "priority_domain": "absolute_deadline",
                "system_ceiling": 0.0,
            },
        }
    ]

    report = build_audit_report(events, scheduler_name="edf")
    assert report["status"] == "fail"
    assert any(issue["rule"] == "pcp_ceiling_numeric_domain" for issue in report["issues"])


def test_audit_detects_partial_hold_for_atomic_rollback_block() -> None:
    events = [
        {
            "event_id": "e1",
            "type": "ResourceAcquire",
            "job_id": "waiter@0",
            "segment_id": "seg0",
            "resource_id": "r0",
            "payload": {"segment_key": "waiter@0:s0:seg0"},
        },
        {
            "event_id": "e2",
            "type": "SegmentBlocked",
            "job_id": "waiter@0",
            "segment_id": "seg0",
            "resource_id": "r1",
            "payload": {
                "segment_key": "waiter@0:s0:seg0",
                "reason": "resource_busy",
                "resource_acquire_policy": "atomic_rollback",
            },
        },
    ]

    report = build_audit_report(events, scheduler_name="edf")
    assert report["status"] == "fail"
    assert any(issue["rule"] == "resource_partial_hold_on_block" for issue in report["issues"])


def test_audit_passes_atomic_rollback_when_resources_released_before_block() -> None:
    events = [
        {
            "event_id": "e1",
            "type": "ResourceAcquire",
            "job_id": "waiter@0",
            "segment_id": "seg0",
            "resource_id": "r0",
            "payload": {"segment_key": "waiter@0:s0:seg0"},
        },
        {
            "event_id": "e2",
            "type": "ResourceRelease",
            "job_id": "waiter@0",
            "segment_id": "seg0",
            "resource_id": "r0",
            "payload": {"segment_key": "waiter@0:s0:seg0", "reason": "acquire_rollback"},
        },
        {
            "event_id": "e3",
            "type": "SegmentBlocked",
            "job_id": "waiter@0",
            "segment_id": "seg0",
            "resource_id": "r1",
            "payload": {
                "segment_key": "waiter@0:s0:seg0",
                "reason": "resource_busy",
                "resource_acquire_policy": "atomic_rollback",
            },
        },
    ]

    report = build_audit_report(events, scheduler_name="edf")
    assert report["checks"]["resource_partial_hold_on_block"]["passed"] is True


def test_audit_detects_wait_for_deadlock_cycle() -> None:
    events = [
        {
            "event_id": "e1",
            "type": "ResourceAcquire",
            "job_id": "a@0",
            "segment_id": "segA",
            "resource_id": "r0",
            "payload": {"segment_key": "a@0:s0:segA"},
        },
        {
            "event_id": "e2",
            "type": "ResourceAcquire",
            "job_id": "b@0",
            "segment_id": "segB",
            "resource_id": "r1",
            "payload": {"segment_key": "b@0:s0:segB"},
        },
        {
            "event_id": "e3",
            "type": "SegmentBlocked",
            "job_id": "a@0",
            "segment_id": "segA",
            "resource_id": "r1",
            "payload": {
                "segment_key": "a@0:s0:segA",
                "reason": "resource_busy",
                "owner_segment": "b@0:s0:segB",
            },
        },
        {
            "event_id": "e4",
            "type": "SegmentBlocked",
            "job_id": "b@0",
            "segment_id": "segB",
            "resource_id": "r0",
            "payload": {
                "segment_key": "b@0:s0:segB",
                "reason": "resource_busy",
                "owner_segment": "a@0:s0:segA",
            },
        },
    ]

    report = build_audit_report(events, scheduler_name="edf")
    assert report["status"] == "fail"
    assert any(issue["rule"] == "wait_for_deadlock" for issue in report["issues"])


def test_audit_wait_for_deadlock_check_passes_without_cycle() -> None:
    events = [
        {
            "event_id": "e1",
            "type": "ResourceAcquire",
            "job_id": "a@0",
            "segment_id": "segA",
            "resource_id": "r0",
            "payload": {"segment_key": "a@0:s0:segA"},
        },
        {
            "event_id": "e2",
            "type": "SegmentBlocked",
            "job_id": "b@0",
            "segment_id": "segB",
            "resource_id": "r0",
            "payload": {
                "segment_key": "b@0:s0:segB",
                "reason": "resource_busy",
                "owner_segment": "a@0:s0:segA",
            },
        },
    ]

    report = build_audit_report(events, scheduler_name="edf")
    assert report["checks"]["wait_for_deadlock"]["passed"] is True
