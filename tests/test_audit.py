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


def test_audit_detects_missing_owner_segment_for_resource_busy_chain() -> None:
    events = [
        {
            "event_id": "e1",
            "type": "SegmentBlocked",
            "job_id": "waiter@0",
            "resource_id": "r0",
            "payload": {
                "segment_key": "waiter@0:s0:seg0",
                "reason": "resource_busy",
            },
        }
    ]

    report = build_audit_report(events, scheduler_name="edf")
    assert report["status"] == "fail"
    assert any(issue["rule"] == "pip_priority_chain_consistency" for issue in report["issues"])


def test_audit_detects_unresolved_system_ceiling_block() -> None:
    events = [
        {
            "event_id": "e1",
            "type": "SegmentBlocked",
            "job_id": "task@0",
            "resource_id": "r0",
            "payload": {
                "segment_key": "task@0:s0:seg0",
                "reason": "system_ceiling_block",
                "priority_domain": "absolute_deadline",
                "system_ceiling": -5.0,
            },
        }
    ]

    report = build_audit_report(events, scheduler_name="edf")
    assert report["status"] == "fail"
    assert any(issue["rule"] == "pcp_ceiling_transition_consistency" for issue in report["issues"])


def test_audit_passes_when_system_ceiling_block_is_later_unblocked() -> None:
    events = [
        {
            "event_id": "e1",
            "type": "SegmentBlocked",
            "job_id": "task@0",
            "resource_id": "r0",
            "payload": {
                "segment_key": "task@0:s0:seg0",
                "reason": "system_ceiling_block",
                "priority_domain": "absolute_deadline",
                "system_ceiling": -5.0,
            },
        },
        {
            "event_id": "e2",
            "type": "SegmentUnblocked",
            "job_id": "task@0",
            "resource_id": "r0",
            "payload": {"segment_key": "task@0:s0:seg0"},
        },
    ]

    report = build_audit_report(events, scheduler_name="edf")
    assert report["checks"]["pcp_ceiling_transition_consistency"]["passed"] is True


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


def test_audit_resource_balance_uses_segment_key_when_segment_id_collides() -> None:
    events = [
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

    report = build_audit_report(events, scheduler_name="edf")
    assert report["status"] == "fail"
    assert any(issue["rule"] == "resource_release_balance" for issue in report["issues"])


def test_audit_keeps_wait_graph_on_deadline_miss_without_abort() -> None:
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
            },
        },
        {
            "event_id": "e4",
            "type": "DeadlineMiss",
            "job_id": "a@0",
            "payload": {"abort_on_miss": False},
        },
        {
            "event_id": "e5",
            "type": "SegmentBlocked",
            "job_id": "b@0",
            "segment_id": "segB",
            "resource_id": "r0",
            "payload": {
                "segment_key": "b@0:s0:segB",
                "reason": "resource_busy",
            },
        },
    ]

    report = build_audit_report(events, scheduler_name="edf")
    assert report["status"] == "fail"
    assert any(issue["rule"] == "wait_for_deadlock" for issue in report["issues"])


def test_audit_includes_model_relation_summary_when_provided() -> None:
    report = build_audit_report(
        events=[],
        scheduler_name="edf",
        model_relation_summary={"task_count": 1, "segment_count": 2},
    )

    assert report["status"] == "pass"
    assert report["model_relation_summary"]["task_count"] == 1


def test_audit_includes_rule_version_and_evidence() -> None:
    report = build_audit_report(events=[], scheduler_name="edf")

    assert report["rule_version"] == "0.4"
    assert report["check_catalog"]["catalog_version"] == "0.2"
    assert "resource_release_balance" in report["check_catalog"]["checks"]
    assert report["evidence"]["scheduler_name"] == "edf"
    assert report["evidence"]["event_count"] == 0
    assert report["evidence"]["checks_evaluated"] >= 1


def test_audit_protocol_proof_assets_include_pip_and_pcp_traces() -> None:
    events = [
        {
            "event_id": "e1",
            "type": "ResourceAcquire",
            "job_id": "owner@0",
            "resource_id": "r0",
            "payload": {"segment_key": "owner@0:s0:seg0"},
        },
        {
            "event_id": "e2",
            "type": "SegmentBlocked",
            "job_id": "waiter@0",
            "resource_id": "r0",
            "payload": {
                "segment_key": "waiter@0:s0:seg0",
                "reason": "resource_busy",
                "owner_segment": "owner@0:s0:seg0",
            },
        },
        {
            "event_id": "e3",
            "type": "SegmentBlocked",
            "job_id": "waiter@0",
            "resource_id": "r1",
            "payload": {
                "segment_key": "waiter@0:s0:seg1",
                "reason": "system_ceiling_block",
                "priority_domain": "absolute_deadline",
                "system_ceiling": -8.0,
            },
        },
        {
            "event_id": "e4",
            "type": "SegmentUnblocked",
            "job_id": "waiter@0",
            "resource_id": "r1",
            "payload": {"segment_key": "waiter@0:s0:seg1"},
        },
    ]

    report = build_audit_report(events, scheduler_name="edf")

    assets = report["protocol_proof_assets"]
    assert assets["proof_asset_version"] == "0.2"
    assert assets["pip_wait_edge_count"] == 1
    assert assets["pip_wait_chain_max_depth"] == 1
    assert assets["pip_wait_owner_coverage"] == 1.0
    assert assets["pcp_ceiling_block_count"] == 1
    assert assets["pcp_ceiling_resolution_count"] == 1
    assert assets["pcp_ceiling_resolution_reason_counts"]["segment_unblocked"] == 1
    assert assets["pcp_ceiling_unresolved_count"] == 0
    assert assets["pcp_ceiling_unresolved_ratio"] == 0.0
    assert report["checks"]["pip_owner_hold_consistency"]["passed"] is True


def test_audit_detects_pip_owner_hold_mismatch() -> None:
    events = [
        {
            "event_id": "e1",
            "type": "ResourceAcquire",
            "job_id": "owner@0",
            "resource_id": "r0",
            "payload": {"segment_key": "owner@0:s0:seg0"},
        },
        {
            "event_id": "e2",
            "type": "SegmentBlocked",
            "job_id": "waiter@0",
            "resource_id": "r0",
            "payload": {
                "segment_key": "waiter@0:s0:seg0",
                "reason": "resource_busy",
                "owner_segment": "another@0:s0:seg0",
            },
        },
    ]

    report = build_audit_report(events, scheduler_name="edf")
    assert report["status"] == "fail"
    assert any(issue["rule"] == "pip_owner_hold_consistency" for issue in report["issues"])


def test_audit_includes_compliance_profiles() -> None:
    report = build_audit_report(events=[], scheduler_name="edf")

    profiles = report["compliance_profiles"]
    assert profiles["profile_version"] == "0.2"
    assert profiles["default_profile"] == "research_v1"
    assert profiles["profiles"]["engineering_v1"]["status"] == "pass"
    assert profiles["profiles"]["research_v1"]["status"] == "pass"


def test_audit_compliance_profile_tracks_check_failures() -> None:
    events = [
        {
            "event_id": "e1",
            "type": "SegmentBlocked",
            "job_id": "waiter@0",
            "resource_id": "r0",
            "payload": {
                "segment_key": "waiter@0:s0:seg0",
                "reason": "resource_busy",
            },
        }
    ]

    report = build_audit_report(events, scheduler_name="edf")
    research_profile = report["compliance_profiles"]["profiles"]["research_v1"]
    engineering_profile = report["compliance_profiles"]["profiles"]["engineering_v1"]

    assert research_profile["status"] == "fail"
    assert "pip_priority_chain_consistency" in research_profile["failed_checks"]
    assert engineering_profile["status"] == "pass"


def test_audit_check_contains_sample_event_ids_for_failed_rule() -> None:
    events = [
        {
            "event_id": "e1",
            "type": "SegmentBlocked",
            "job_id": "waiter@0",
            "resource_id": "r0",
            "payload": {
                "segment_key": "waiter@0:s0:seg0",
                "reason": "resource_busy",
            },
        }
    ]

    report = build_audit_report(events, scheduler_name="edf")
    failed = report["checks"]["pip_priority_chain_consistency"]

    assert failed["passed"] is False
    assert failed["issue_count"] == 1
    assert failed["sample_event_ids"] == ["e1"]
    assert report["evidence"]["failed_check_event_refs"]["pip_priority_chain_consistency"] == ["e1"]


def test_audit_time_deterministic_ready_consistency_passes_for_stable_phase() -> None:
    events = [
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
            "time": 12.0,
            "payload": {
                "segment_key": "td@1:s0:seg0",
                "deterministic_window_id": 1,
                "deterministic_offset_index": 0,
                "deterministic_ready_time": 12.0,
            },
        },
    ]

    report = build_audit_report(events, scheduler_name="edf")
    assert report["checks"]["time_deterministic_ready_consistency"]["passed"] is True
    assert report["time_deterministic_proof_assets"]["deterministic_segment_ready_count"] == 2
    assert report["time_deterministic_proof_assets"]["deterministic_task_count"] == 1


def test_audit_detects_time_deterministic_phase_jitter() -> None:
    events = [
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

    report = build_audit_report(events, scheduler_name="edf")
    assert report["status"] == "fail"
    assert any(issue["rule"] == "time_deterministic_ready_consistency" for issue in report["issues"])
    assert report["checks"]["time_deterministic_ready_consistency"]["passed"] is False
