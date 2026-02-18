"""Post-simulation audit checks for protocol/event correctness."""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _is_edf_scheduler(name: str | None) -> bool:
    if name is None:
        return False
    scheduler = str(name).strip().lower()
    return scheduler in {"edf", "earliest_deadline_first"}


def _event_segment_key(event: dict[str, Any]) -> str | None:
    payload = event.get("payload", {})
    if isinstance(payload, dict):
        segment_key = payload.get("segment_key")
        if isinstance(segment_key, str) and segment_key:
            return segment_key
    return None


def _find_wait_cycle(wait_for: dict[str, str], start: str) -> list[str]:
    index_by_segment: dict[str, int] = {}
    path: list[str] = []
    cursor = start
    while cursor in wait_for:
        if cursor in index_by_segment:
            return path[index_by_segment[cursor] :]
        index_by_segment[cursor] = len(path)
        path.append(cursor)
        cursor = wait_for[cursor]
    return []


def build_audit_report(events: list[dict[str, Any]], *, scheduler_name: str | None = None) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}

    active_holds: defaultdict[tuple[str | None, str | None, str | None], int] = defaultdict(int)
    for event in events:
        event_type = event.get("type")
        if event_type not in {"ResourceAcquire", "ResourceRelease"}:
            continue
        key = (
            event.get("job_id"),
            event.get("segment_id"),
            event.get("resource_id"),
        )
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
    checks["resource_release_balance"] = {"passed": not unreleased}

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
    if missing_cancel_release_jobs:
        issues.append(
            {
                "rule": "abort_cancel_release_visibility",
                "severity": "error",
                "message": "Aborted jobs that acquired resources must emit cancel-segment ResourceRelease events",
                "job_ids": missing_cancel_release_jobs,
            }
        )
    checks["abort_cancel_release_visibility"] = {"passed": not missing_cancel_release_jobs}

    priority_domain_issues: list[dict[str, Any]] = []
    ceiling_numeric_domain_issues: list[dict[str, Any]] = []
    if _is_edf_scheduler(scheduler_name):
        for event in events:
            if event.get("type") != "SegmentBlocked":
                continue
            payload = event.get("payload", {})
            if not isinstance(payload, dict):
                continue
            if payload.get("reason") != "system_ceiling_block":
                continue
            priority_domain = payload.get("priority_domain")
            if priority_domain != "absolute_deadline":
                priority_domain_issues.append(
                    {
                        "event_id": event.get("event_id"),
                        "observed": priority_domain,
                    }
                )
            system_ceiling = payload.get("system_ceiling")
            if isinstance(system_ceiling, (int, float)) and system_ceiling >= 0:
                ceiling_numeric_domain_issues.append(
                    {
                        "event_id": event.get("event_id"),
                        "system_ceiling": float(system_ceiling),
                    }
                )
    if priority_domain_issues:
        issues.append(
            {
                "rule": "pcp_priority_domain_alignment",
                "severity": "error",
                "message": "EDF + PCP must use absolute_deadline priority domain for system ceiling decisions",
                "samples": priority_domain_issues[:20],
            }
        )
    checks["pcp_priority_domain_alignment"] = {
        "passed": not priority_domain_issues,
        "scheduler": scheduler_name,
    }
    if ceiling_numeric_domain_issues:
        issues.append(
            {
                "rule": "pcp_ceiling_numeric_domain",
                "severity": "error",
                "message": "EDF + PCP system_ceiling should remain in negative priority domain",
                "samples": ceiling_numeric_domain_issues[:20],
            }
        )
    checks["pcp_ceiling_numeric_domain"] = {
        "passed": not ceiling_numeric_domain_issues,
        "scheduler": scheduler_name,
    }

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
    if partial_hold_issues:
        issues.append(
            {
                "rule": "resource_partial_hold_on_block",
                "severity": "error",
                "message": "atomic_rollback blocked segments must not retain any acquired resources",
                "samples": partial_hold_issues[:20],
            }
        )
    checks["resource_partial_hold_on_block"] = {
        "passed": not partial_hold_issues,
    }

    wait_for: dict[str, str] = {}
    resource_owner: dict[str, str] = {}
    deadlock_samples: list[dict[str, Any]] = []
    observed_cycles: set[tuple[str, ...]] = set()
    for event in events:
        event_type = str(event.get("type", ""))
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}
        segment_key = _event_segment_key(event)
        resource_id = event.get("resource_id")
        job_id = event.get("job_id")

        if event_type == "ResourceAcquire":
            if (
                isinstance(resource_id, str)
                and resource_id
                and isinstance(segment_key, str)
                and segment_key
            ):
                resource_owner[resource_id] = segment_key
                wait_for.pop(segment_key, None)
            continue

        if event_type == "ResourceRelease":
            if (
                isinstance(resource_id, str)
                and resource_id
                and isinstance(segment_key, str)
                and segment_key
                and resource_owner.get(resource_id) == segment_key
            ):
                resource_owner.pop(resource_id, None)
            continue

        if event_type == "SegmentBlocked":
            if payload.get("reason") != "resource_busy":
                continue
            if not isinstance(segment_key, str) or not segment_key:
                continue
            owner_segment = payload.get("owner_segment")
            if (
                (not isinstance(owner_segment, str) or not owner_segment)
                and isinstance(resource_id, str)
                and resource_id
            ):
                owner_segment = resource_owner.get(resource_id)
            if not isinstance(owner_segment, str) or not owner_segment or owner_segment == segment_key:
                continue
            wait_for[segment_key] = owner_segment
            cycle = _find_wait_cycle(wait_for, segment_key)
            if not cycle:
                continue
            cycle_key = tuple(sorted(cycle))
            if cycle_key in observed_cycles:
                continue
            observed_cycles.add(cycle_key)
            deadlock_samples.append(
                {
                    "event_id": event.get("event_id"),
                    "cycle_segments": cycle,
                    "resource_id": resource_id,
                }
            )
            continue

        if event_type == "SegmentUnblocked" and isinstance(segment_key, str) and segment_key:
            wait_for.pop(segment_key, None)
            continue

        if event_type in {"JobComplete", "DeadlineMiss"} and isinstance(job_id, str) and job_id:
            prefix = f"{job_id}:"
            for waiter in [key for key in wait_for if key.startswith(prefix)]:
                wait_for.pop(waiter, None)
            for rid, owner in list(resource_owner.items()):
                if owner.startswith(prefix):
                    resource_owner.pop(rid, None)

    if deadlock_samples:
        issues.append(
            {
                "rule": "wait_for_deadlock",
                "severity": "error",
                "message": "wait-for cycle detected among blocked segments",
                "samples": deadlock_samples[:20],
            }
        )
    checks["wait_for_deadlock"] = {"passed": not deadlock_samples}

    return {
        "status": "pass" if not issues else "fail",
        "issue_count": len(issues),
        "issues": issues,
        "checks": checks,
    }
