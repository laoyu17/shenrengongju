"""Post-simulation audit checks for protocol/event correctness."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


AUDIT_RULE_VERSION = "0.2"
AUDIT_COMPLIANCE_PROFILE_VERSION = "0.1"

ENGINEERING_REQUIRED_CHECKS: tuple[str, ...] = (
    "resource_release_balance",
    "abort_cancel_release_visibility",
    "resource_partial_hold_on_block",
    "wait_for_deadlock",
)

RESEARCH_REQUIRED_CHECKS: tuple[str, ...] = (
    "resource_release_balance",
    "abort_cancel_release_visibility",
    "pcp_priority_domain_alignment",
    "pcp_ceiling_numeric_domain",
    "resource_partial_hold_on_block",
    "pip_priority_chain_consistency",
    "pcp_ceiling_transition_consistency",
    "wait_for_deadlock",
    "pip_owner_hold_consistency",
)


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


def _build_audit_evidence(
    events: list[dict[str, Any]],
    checks: dict[str, Any],
    *,
    scheduler_name: str | None,
) -> dict[str, Any]:
    event_type_counts = Counter(str(event.get("type", "unknown")) for event in events)
    failed_checks = sorted(
        rule
        for rule, result in checks.items()
        if isinstance(result, dict) and result.get("passed") is False
    )
    return {
        "scheduler_name": scheduler_name,
        "event_count": len(events),
        "event_type_counts": dict(sorted(event_type_counts.items())),
        "checks_evaluated": len(checks),
        "checks_failed": failed_checks,
        "checks_passed": len(checks) - len(failed_checks),
    }


def _build_protocol_proof_assets(events: list[dict[str, Any]]) -> dict[str, Any]:
    resource_owner: dict[str, str] = {}
    pip_wait_edges: list[dict[str, Any]] = []
    pip_owner_mismatch: list[dict[str, Any]] = []
    pcp_ceiling_blocked: dict[str, dict[str, Any]] = {}
    pcp_ceiling_blocks: list[dict[str, Any]] = []
    pcp_ceiling_resolutions: list[dict[str, Any]] = []

    def resolve_ceiling_blocks(
        *,
        segment_prefix: str | None,
        reason: str,
        resolver_event_id: str | None,
        resolver_event_type: str,
    ) -> None:
        if not segment_prefix:
            return
        for segment_key in sorted(
            key for key in pcp_ceiling_blocked if key.startswith(segment_prefix)
        ):
            block_info = pcp_ceiling_blocked.pop(segment_key)
            pcp_ceiling_resolutions.append(
                {
                    "segment_key": segment_key,
                    "blocked_event_id": block_info.get("event_id"),
                    "resolved_event_id": resolver_event_id,
                    "resolved_by": reason,
                    "resolver_event_type": resolver_event_type,
                }
            )

    for event in events:
        event_type = str(event.get("type", ""))
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}
        event_id = event.get("event_id")
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
            reason = payload.get("reason")
            if reason == "resource_busy":
                owner_segment = payload.get("owner_segment")
                if (
                    (not isinstance(owner_segment, str) or not owner_segment)
                    and isinstance(resource_id, str)
                    and resource_id
                ):
                    owner_segment = resource_owner.get(resource_id)
                row = {
                    "event_id": event_id,
                    "segment_key": segment_key,
                    "resource_id": resource_id,
                    "owner_segment": owner_segment,
                    "request_priority": payload.get("request_priority"),
                }
                pip_wait_edges.append(row)
                if (
                    isinstance(owner_segment, str)
                    and owner_segment
                    and isinstance(resource_id, str)
                    and resource_id
                ):
                    expected_owner = resource_owner.get(resource_id)
                    if expected_owner is not None and expected_owner != owner_segment:
                        pip_owner_mismatch.append(
                            {
                                "event_id": event_id,
                                "resource_id": resource_id,
                                "reported_owner": owner_segment,
                                "expected_owner": expected_owner,
                                "segment_key": segment_key,
                            }
                        )
                continue

            if reason == "system_ceiling_block":
                if isinstance(segment_key, str) and segment_key:
                    block_row = {
                        "event_id": event_id,
                        "segment_key": segment_key,
                        "resource_id": resource_id,
                        "system_ceiling": payload.get("system_ceiling"),
                        "priority_domain": payload.get("priority_domain"),
                    }
                    pcp_ceiling_blocked[segment_key] = block_row
                    pcp_ceiling_blocks.append(block_row)
                continue

        if event_type == "SegmentUnblocked":
            if isinstance(segment_key, str) and segment_key in pcp_ceiling_blocked:
                resolve_ceiling_blocks(
                    segment_prefix=segment_key,
                    reason="segment_unblocked",
                    resolver_event_id=event_id,
                    resolver_event_type=event_type,
                )
            continue

        if event_type == "JobComplete":
            if isinstance(job_id, str) and job_id:
                resolve_ceiling_blocks(
                    segment_prefix=f"{job_id}:",
                    reason="job_complete",
                    resolver_event_id=event_id,
                    resolver_event_type=event_type,
                )
            continue

        if event_type == "DeadlineMiss" and payload.get("abort_on_miss"):
            if isinstance(job_id, str) and job_id:
                resolve_ceiling_blocks(
                    segment_prefix=f"{job_id}:",
                    reason="deadline_abort",
                    resolver_event_id=event_id,
                    resolver_event_type=event_type,
                )
            continue

        if event_type == "Preempt" and payload.get("reason") in {"abort_on_miss", "abort_on_error"}:
            if isinstance(job_id, str) and job_id:
                resolve_ceiling_blocks(
                    segment_prefix=f"{job_id}:",
                    reason="preempt_abort",
                    resolver_event_id=event_id,
                    resolver_event_type=event_type,
                )

    unresolved = [
        {"segment_key": segment_key, **row}
        for segment_key, row in sorted(pcp_ceiling_blocked.items())
    ]
    return {
        "pip_wait_edge_count": len(pip_wait_edges),
        "pip_wait_edges": pip_wait_edges[:50],
        "pip_owner_mismatch_count": len(pip_owner_mismatch),
        "pip_owner_mismatch_samples": pip_owner_mismatch[:20],
        "pcp_ceiling_block_count": len(pcp_ceiling_blocks),
        "pcp_ceiling_blocks": pcp_ceiling_blocks[:50],
        "pcp_ceiling_resolution_count": len(pcp_ceiling_resolutions),
        "pcp_ceiling_resolutions": pcp_ceiling_resolutions[:50],
        "pcp_ceiling_unresolved_count": len(unresolved),
        "pcp_ceiling_unresolved_samples": unresolved[:20],
    }


def _build_profile_status(checks: dict[str, Any], required_checks: tuple[str, ...]) -> dict[str, Any]:
    passed: list[str] = []
    failed: list[str] = []
    missing: list[str] = []
    for check_name in required_checks:
        result = checks.get(check_name)
        if not isinstance(result, dict):
            missing.append(check_name)
            continue
        if result.get("passed") is True:
            passed.append(check_name)
        else:
            failed.append(check_name)

    total = len(required_checks)
    return {
        "status": "pass" if not failed and not missing else "fail",
        "required_checks": list(required_checks),
        "passed_checks": passed,
        "failed_checks": failed,
        "missing_checks": missing,
        "pass_rate": 1.0 if total == 0 else len(passed) / total,
    }


def _build_compliance_profiles(checks: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile_version": AUDIT_COMPLIANCE_PROFILE_VERSION,
        "default_profile": "research_v1",
        "profiles": {
            "engineering_v1": {
                "description": "工程交付基线，覆盖资源平衡/终止路径/死锁基础安全项",
                **_build_profile_status(checks, ENGINEERING_REQUIRED_CHECKS),
            },
            "research_v1": {
                "description": "研究复现基线，覆盖协议域一致性与证明辅助链路",
                **_build_profile_status(checks, RESEARCH_REQUIRED_CHECKS),
            },
        },
    }


def build_audit_report(
    events: list[dict[str, Any]],
    *,
    scheduler_name: str | None = None,
    model_relation_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}

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

    pip_chain_issues: list[dict[str, Any]] = []
    for event in events:
        if event.get("type") != "SegmentBlocked":
            continue
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}
        if payload.get("reason") != "resource_busy":
            continue

        segment_key = _event_segment_key(event)
        owner_segment = payload.get("owner_segment")
        if not isinstance(segment_key, str) or not segment_key:
            pip_chain_issues.append(
                {
                    "event_id": event.get("event_id"),
                    "reason": "missing_segment_key",
                }
            )
            continue
        if not isinstance(owner_segment, str) or not owner_segment:
            pip_chain_issues.append(
                {
                    "event_id": event.get("event_id"),
                    "segment_key": segment_key,
                    "reason": "missing_owner_segment",
                }
            )
            continue
        if owner_segment == segment_key:
            pip_chain_issues.append(
                {
                    "event_id": event.get("event_id"),
                    "segment_key": segment_key,
                    "owner_segment": owner_segment,
                    "reason": "self_owner_segment",
                }
            )

    if pip_chain_issues:
        issues.append(
            {
                "rule": "pip_priority_chain_consistency",
                "severity": "error",
                "message": "resource_busy events must expose a valid owner_segment chain",
                "samples": pip_chain_issues[:20],
            }
        )
    checks["pip_priority_chain_consistency"] = {"passed": not pip_chain_issues}

    pcp_ceiling_blocked: dict[str, dict[str, Any]] = {}
    for event in events:
        event_type = event.get("type")
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}

        if event_type == "SegmentBlocked" and payload.get("reason") == "system_ceiling_block":
            segment_key = _event_segment_key(event)
            if isinstance(segment_key, str) and segment_key:
                pcp_ceiling_blocked[segment_key] = {
                    "event_id": event.get("event_id"),
                    "resource_id": event.get("resource_id"),
                }
            continue

        if event_type == "SegmentUnblocked":
            segment_key = _event_segment_key(event)
            if isinstance(segment_key, str) and segment_key in pcp_ceiling_blocked:
                pcp_ceiling_blocked.pop(segment_key, None)
            continue

        if event_type == "JobComplete":
            job_id = event.get("job_id")
            if isinstance(job_id, str) and job_id:
                prefix = f"{job_id}:"
                for key in [segment for segment in pcp_ceiling_blocked if segment.startswith(prefix)]:
                    pcp_ceiling_blocked.pop(key, None)
            continue

        if event_type == "DeadlineMiss" and payload.get("abort_on_miss"):
            job_id = event.get("job_id")
            if isinstance(job_id, str) and job_id:
                prefix = f"{job_id}:"
                for key in [segment for segment in pcp_ceiling_blocked if segment.startswith(prefix)]:
                    pcp_ceiling_blocked.pop(key, None)
            continue

        if event_type == "Preempt" and payload.get("reason") in {"abort_on_miss", "abort_on_error"}:
            job_id = event.get("job_id")
            if isinstance(job_id, str) and job_id:
                prefix = f"{job_id}:"
                for key in [segment for segment in pcp_ceiling_blocked if segment.startswith(prefix)]:
                    pcp_ceiling_blocked.pop(key, None)

    unresolved_ceiling = [
        {
            "segment_key": segment_key,
            **sample,
        }
        for segment_key, sample in sorted(pcp_ceiling_blocked.items())
    ]
    if unresolved_ceiling:
        issues.append(
            {
                "rule": "pcp_ceiling_transition_consistency",
                "severity": "error",
                "message": "segments blocked by system ceiling must be unblocked or terminally cleared",
                "samples": unresolved_ceiling[:20],
            }
        )
    checks["pcp_ceiling_transition_consistency"] = {"passed": not unresolved_ceiling}

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

        if event_type == "JobComplete" and isinstance(job_id, str) and job_id:
            prefix = f"{job_id}:"
            for waiter in [key for key in wait_for if key.startswith(prefix)]:
                wait_for.pop(waiter, None)
            for rid, owner in list(resource_owner.items()):
                if owner.startswith(prefix):
                    resource_owner.pop(rid, None)
            continue

        if event_type == "DeadlineMiss" and isinstance(job_id, str) and job_id:
            if not payload.get("abort_on_miss"):
                continue
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

    protocol_proof_assets = _build_protocol_proof_assets(events)
    pip_owner_mismatch_count = int(protocol_proof_assets["pip_owner_mismatch_count"])
    if pip_owner_mismatch_count > 0:
        issues.append(
            {
                "rule": "pip_owner_hold_consistency",
                "severity": "error",
                "message": "resource_busy owner_segment must match active resource owner",
                "samples": protocol_proof_assets["pip_owner_mismatch_samples"],
            }
        )
    checks["pip_owner_hold_consistency"] = {
        "passed": pip_owner_mismatch_count == 0,
    }

    report = {
        "rule_version": AUDIT_RULE_VERSION,
        "status": "pass" if not issues else "fail",
        "issue_count": len(issues),
        "issues": issues,
        "checks": checks,
        "evidence": _build_audit_evidence(events, checks, scheduler_name=scheduler_name),
        "protocol_proof_assets": protocol_proof_assets,
        "compliance_profiles": _build_compliance_profiles(checks),
    }
    if isinstance(model_relation_summary, dict):
        report["model_relation_summary"] = model_relation_summary
    return report
