"""Resource-focused audit checks."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from rtos_sim.analysis.audit_report_builder import CheckOutcome, make_check_outcome


def _event_segment_key(event: dict[str, Any]) -> str | None:
    payload = event.get("payload", {})
    if isinstance(payload, dict):
        segment_key = payload.get("segment_key")
        if isinstance(segment_key, str) and segment_key:
            return segment_key
    return None


def _resource_hold_key(event: dict[str, Any]) -> tuple[str, str | None]:
    segment_key = _event_segment_key(event)
    if segment_key:
        segment_identity = f"segment_key:{segment_key}"
    else:
        # Backward-compatible fallback for legacy events missing payload.segment_key.
        job_id = event.get("job_id")
        segment_id = event.get("segment_id")
        correlation_id = event.get("correlation_id")
        segment_identity = f"legacy:{job_id}:{segment_id}:{correlation_id}"
    resource_id = event.get("resource_id")
    if not isinstance(resource_id, str) or not resource_id:
        resource_id = None
    return segment_identity, resource_id


def evaluate_resource_release_balance(events: list[dict[str, Any]]) -> CheckOutcome:
    issues: list[dict[str, Any]] = []
    active_holds: defaultdict[tuple[str, str | None], int] = defaultdict(int)
    for event in events:
        event_type = event.get("type")
        if event_type not in {"ResourceAcquire", "ResourceRelease"}:
            continue
        key = _resource_hold_key(event)
        if event_type == "ResourceAcquire":
            active_holds[key] += 1
        else:
            active_holds[key] -= 1
            if active_holds[key] < 0:
                issues.append(
                    {
                        "rule": "resource_release_balance",
                        "severity": "error",
                        "message": "ResourceRelease appears before matching ResourceAcquire",
                        "event_id": event.get("event_id"),
                        "key": key,
                    }
                )
                active_holds[key] = 0

    unreleased = [
        {"key": key, "count": count}
        for key, count in sorted(active_holds.items())
        if count > 0
    ]
    if unreleased:
        issues.append(
            {
                "rule": "resource_release_balance",
                "severity": "error",
                "message": "ResourceAcquire/ResourceRelease pairs are imbalanced",
                "unreleased": unreleased[:20],
            }
        )

    # Keep legacy semantics: check pass/fail is tied to unreleased holds only.
    return make_check_outcome(
        rule="resource_release_balance",
        passed=not unreleased,
        issues=issues,
    )


def evaluate_abort_cancel_release_visibility(events: list[dict[str, Any]]) -> CheckOutcome:
    aborted_jobs: set[str] = set()
    job_acquire_count: defaultdict[str, int] = defaultdict(int)
    job_cancel_release_count: defaultdict[str, int] = defaultdict(int)
    for event in events:
        event_type = event.get("type")
        job_id = event.get("job_id")
        payload = event.get("payload", {})
        if event_type == "DeadlineMiss" and payload.get("abort_on_miss") and job_id:
            aborted_jobs.add(job_id)
        if event_type == "Preempt" and payload.get("reason") in {"abort_on_miss", "abort_on_error"} and job_id:
            aborted_jobs.add(job_id)
        if event_type == "ResourceAcquire" and job_id:
            job_acquire_count[job_id] += 1
        if (
            event_type == "ResourceRelease"
            and job_id
            and isinstance(payload, dict)
            and payload.get("reason") == "cancel_segment"
        ):
            job_cancel_release_count[job_id] += 1

    missing_cancel_release_jobs = sorted(
        job_id
        for job_id in aborted_jobs
        if job_acquire_count[job_id] > 0 and job_cancel_release_count[job_id] == 0
    )

    issues: list[dict[str, Any]] = []
    if missing_cancel_release_jobs:
        issues.append(
            {
                "rule": "abort_cancel_release_visibility",
                "severity": "error",
                "message": "Aborted jobs that acquired resources must emit cancel-segment ResourceRelease events",
                "job_ids": missing_cancel_release_jobs,
            }
        )

    return make_check_outcome(
        rule="abort_cancel_release_visibility",
        passed=not missing_cancel_release_jobs,
        issues=issues,
    )


def evaluate_resource_partial_hold_on_block(events: list[dict[str, Any]]) -> CheckOutcome:
    partial_hold_issues: list[dict[str, Any]] = []
    segment_hold_counts: defaultdict[str, int] = defaultdict(int)
    for event in events:
        event_type = event.get("type")
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}
        segment_key = payload.get("segment_key")
        if not isinstance(segment_key, str) or not segment_key:
            continue
        if event_type == "ResourceAcquire":
            segment_hold_counts[segment_key] += 1
            continue
        if event_type == "ResourceRelease":
            segment_hold_counts[segment_key] = max(0, segment_hold_counts[segment_key] - 1)
            continue
        if event_type != "SegmentBlocked":
            continue

        if payload.get("resource_acquire_policy") != "atomic_rollback":
            continue
        if segment_hold_counts.get(segment_key, 0) > 0:
            partial_hold_issues.append(
                {
                    "event_id": event.get("event_id"),
                    "segment_key": segment_key,
                    "held_count": segment_hold_counts.get(segment_key, 0),
                    "reason": payload.get("reason"),
                }
            )

    issues: list[dict[str, Any]] = []
    if partial_hold_issues:
        issues.append(
            {
                "rule": "resource_partial_hold_on_block",
                "severity": "error",
                "message": "atomic_rollback blocked segments must not retain any acquired resources",
                "samples": partial_hold_issues[:20],
            }
        )

    return make_check_outcome(
        rule="resource_partial_hold_on_block",
        passed=not partial_hold_issues,
        issues=issues,
    )
