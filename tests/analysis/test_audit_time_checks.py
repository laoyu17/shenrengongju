from __future__ import annotations

from rtos_sim.analysis.audit_checks.time_deterministic_checks import (
    analyze_time_deterministic_ready,
    evaluate_time_deterministic_ready_consistency,
)


def test_analyze_time_deterministic_ready_collects_phase_jitter_issue() -> None:
    assets = analyze_time_deterministic_ready(
        [
            {
                "event_id": "e1",
                "type": "JobReleased",
                "job_id": "td@0",
                "payload": {"deterministic_hyper_period": 10.0},
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
            {
                "event_id": "e3",
                "type": "JobReleased",
                "job_id": "td@1",
                "payload": {"deterministic_hyper_period": 10.0},
            },
            {
                "event_id": "e4",
                "type": "SegmentReady",
                "job_id": "td@1",
                "time": 2.5,
                "payload": {
                    "segment_key": "td@1:s0:seg0",
                    "deterministic_window_id": 1,
                    "deterministic_offset_index": 0,
                    "deterministic_ready_time": 2.5,
                },
            },
        ]
    )

    assert assets["deterministic_segment_ready_count"] == 2
    assert assets["issue_count"] > 0
    reasons = {issue["reason"] for issue in assets["issue_samples"]}
    assert "deterministic_phase_jitter" in reasons


def test_time_deterministic_ready_consistency_pass_and_fail_paths() -> None:
    pass_outcome = evaluate_time_deterministic_ready_consistency(
        {
            "issue_samples": [],
            "deterministic_segment_ready_count": 3,
            "deterministic_task_count": 2,
        }
    )
    fail_outcome = evaluate_time_deterministic_ready_consistency(
        {
            "issue_samples": [{"event_id": "e9", "reason": "deterministic_ready_time_mismatch"}],
            "deterministic_segment_ready_count": 1,
            "deterministic_task_count": 1,
        }
    )

    assert pass_outcome["passed"] is True
    assert fail_outcome["passed"] is False
    assert fail_outcome["issues"][0]["rule"] == "time_deterministic_ready_consistency"
