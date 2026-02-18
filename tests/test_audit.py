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
