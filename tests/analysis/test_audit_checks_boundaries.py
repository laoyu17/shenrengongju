from __future__ import annotations

from rtos_sim.analysis.audit_checks.protocol_checks import evaluate_pcp_priority_domain_alignment
from rtos_sim.analysis.audit_checks.resource_checks import evaluate_resource_release_balance
from rtos_sim.analysis.audit_checks.time_deterministic_checks import analyze_time_deterministic_ready


def test_resource_release_balance_supports_legacy_segment_identity() -> None:
    outcome = evaluate_resource_release_balance(
        [
            {
                "event_id": "e1",
                "type": "ResourceAcquire",
                "job_id": "legacy@0",
                "segment_id": "seg0",
                "correlation_id": "legacy@0",
                "resource_id": "r0",
            },
            {
                "event_id": "e2",
                "type": "ResourceRelease",
                "job_id": "legacy@0",
                "segment_id": "seg0",
                "correlation_id": "legacy@0",
                "resource_id": "r0",
            },
        ]
    )

    assert outcome["passed"] is True
    assert outcome["issues"] == []


def test_pcp_priority_domain_alignment_is_ignored_for_non_edf_scheduler() -> None:
    outcome = evaluate_pcp_priority_domain_alignment(
        [
            {
                "event_id": "e1",
                "type": "SegmentBlocked",
                "payload": {
                    "reason": "system_ceiling_block",
                    "priority_domain": "fixed_priority",
                },
            }
        ],
        scheduler_name="rm",
    )

    assert outcome["passed"] is True
    assert outcome["issues"] == []


def test_time_deterministic_analysis_flags_duplicate_window_offset() -> None:
    assets = analyze_time_deterministic_ready(
        [
            {
                "event_id": "r1",
                "type": "JobReleased",
                "job_id": "td@0",
                "payload": {"deterministic_hyper_period": 10.0},
            },
            {
                "event_id": "e1",
                "type": "SegmentReady",
                "job_id": "td@0",
                "time": 2.0,
                "payload": {
                    "segment_key": "td@0:s0:seg0",
                    "deterministic_window_id": 0,
                    "deterministic_offset_index": 0,
                    "deterministic_ready_time": 2.0,
                },
            },
            {
                "event_id": "e2",
                "type": "SegmentReady",
                "job_id": "td@0",
                "time": 2.0,
                "payload": {
                    "segment_key": "td@0:s0:seg0",
                    "deterministic_window_id": 0,
                    "deterministic_offset_index": 0,
                    "deterministic_ready_time": 2.0,
                },
            },
        ]
    )

    reasons = {item["reason"] for item in assets["issue_samples"]}
    assert "duplicate_window_offset" in reasons
