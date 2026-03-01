from __future__ import annotations

from rtos_sim.analysis.audit_checks.protocol_checks import (
    build_protocol_proof_assets,
    evaluate_pcp_ceiling_transition_consistency,
    evaluate_pcp_priority_domain_alignment,
    evaluate_pip_owner_hold_consistency,
)


def test_protocol_proof_assets_track_preempt_abort_resolution() -> None:
    assets = build_protocol_proof_assets(
        [
            {
                "event_id": "b1",
                "type": "SegmentBlocked",
                "job_id": "task@0",
                "resource_id": "r0",
                "payload": {
                    "segment_key": "task@0:s0:seg0",
                    "reason": "system_ceiling_block",
                    "priority_domain": "absolute_deadline",
                    "system_ceiling": -3.0,
                },
            },
            {
                "event_id": "p1",
                "type": "Preempt",
                "job_id": "task@0",
                "payload": {"reason": "abort_on_error"},
            },
        ]
    )

    assert assets["proof_asset_version"] == "0.2"
    assert assets["pcp_ceiling_block_count"] == 1
    assert assets["pcp_ceiling_resolution_count"] == 1
    assert assets["pcp_ceiling_resolution_reason_counts"]["preempt_abort"] == 1


def test_pcp_priority_domain_alignment_fails_for_non_absolute_deadline() -> None:
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
        scheduler_name="edf",
    )

    assert outcome["passed"] is False
    assert outcome["issues"][0]["rule"] == "pcp_priority_domain_alignment"


def test_pip_owner_hold_consistency_uses_proof_asset_mismatch_count() -> None:
    outcome = evaluate_pip_owner_hold_consistency(
        {
            "pip_owner_mismatch_count": 1,
            "pip_owner_mismatch_samples": [
                {"event_id": "e9", "resource_id": "r0", "reported_owner": "a", "expected_owner": "b"}
            ],
        }
    )

    assert outcome["passed"] is False
    assert outcome["issues"][0]["rule"] == "pip_owner_hold_consistency"


def test_pcp_ceiling_transition_consistency_detects_unresolved_block() -> None:
    outcome = evaluate_pcp_ceiling_transition_consistency(
        [
            {
                "event_id": "e1",
                "type": "SegmentBlocked",
                "job_id": "task@0",
                "resource_id": "r0",
                "payload": {
                    "segment_key": "task@0:s0:seg0",
                    "reason": "system_ceiling_block",
                },
            }
        ]
    )

    assert outcome["passed"] is False
    assert outcome["issues"][0]["rule"] == "pcp_ceiling_transition_consistency"
