"""Protocol-domain audit checks and proof assets."""

from __future__ import annotations

from collections import Counter
from typing import Any

from rtos_sim.analysis.audit_report_builder import CheckOutcome, make_check_outcome

AUDIT_PROOF_ASSET_VERSION = "0.2"
PROTOCOL_PROOF_RULE_VERSION = "0.4"


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


def _compute_wait_chain_max_depth(wait_edges: list[dict[str, Any]]) -> int:
    return max(_compute_wait_chain_depths(wait_edges), default=0)


def _compute_wait_chain_depths(wait_edges: list[dict[str, Any]]) -> list[int]:
    graph: dict[str, str] = {}
    for edge in wait_edges:
        segment_key = edge.get("segment_key")
        owner_segment = edge.get("owner_segment")
        if isinstance(segment_key, str) and segment_key and isinstance(owner_segment, str) and owner_segment:
            graph[segment_key] = owner_segment

    depths: list[int] = []
    for start in graph:
        seen: set[str] = set()
        depth = 0
        cursor = start
        while cursor in graph and cursor not in seen:
            seen.add(cursor)
            depth += 1
            cursor = graph[cursor]
        depths.append(depth)
    return depths


def _build_event_ref_list(rows: list[dict[str, Any]], *, keys: tuple[str, ...] = ("event_id",)) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in keys:
            value = row.get(key)
            if isinstance(value, str) and value and value not in seen:
                refs.append(value)
                seen.add(value)
    return refs[:20]


def _categorize_unresolved_block(row: dict[str, Any]) -> str:
    priority_domain = row.get("priority_domain")
    resource_id = row.get("resource_id")
    if isinstance(priority_domain, str) and priority_domain and priority_domain != "absolute_deadline":
        return "priority_domain_mismatch"
    if not isinstance(resource_id, str) or not resource_id:
        return "missing_resource_id"
    return "missing_terminal_resolution"


def build_protocol_proof_assets(events: list[dict[str, Any]]) -> dict[str, Any]:
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
        for segment_key in sorted(key for key in pcp_ceiling_blocked if key.startswith(segment_prefix)):
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
    pip_wait_edge_count = len(pip_wait_edges)
    pip_owner_known_count = sum(
        1
        for edge in pip_wait_edges
        if isinstance(edge.get("owner_segment"), str) and str(edge.get("owner_segment")).strip()
    )
    pip_wait_owner_coverage = 1.0 if pip_wait_edge_count == 0 else pip_owner_known_count / pip_wait_edge_count
    pcp_ceiling_block_count = len(pcp_ceiling_blocks)
    pcp_ceiling_resolution_count = len(pcp_ceiling_resolutions)
    pcp_ceiling_unresolved_count = len(unresolved)
    pcp_resolution_reason_counts = Counter(str(item.get("resolved_by", "unknown")) for item in pcp_ceiling_resolutions)
    pcp_ceiling_unresolved_ratio = (
        0.0 if pcp_ceiling_block_count == 0 else pcp_ceiling_unresolved_count / pcp_ceiling_block_count
    )
    wait_chain_depths = _compute_wait_chain_depths(pip_wait_edges)
    wait_chain_depth_counts = Counter(wait_chain_depths)
    unresolved_category_counts = Counter(_categorize_unresolved_block(item) for item in unresolved)
    return {
        "proof_asset_version": AUDIT_PROOF_ASSET_VERSION,
        "rule_version": PROTOCOL_PROOF_RULE_VERSION,
        "pip_wait_edge_count": pip_wait_edge_count,
        "pip_wait_edges": pip_wait_edges[:50],
        "pip_wait_chain_max_depth": max(wait_chain_depths, default=0),
        "pip_wait_owner_coverage": pip_wait_owner_coverage,
        "pip_owner_mismatch_count": len(pip_owner_mismatch),
        "pip_owner_mismatch_samples": pip_owner_mismatch[:20],
        "pcp_ceiling_block_count": pcp_ceiling_block_count,
        "pcp_ceiling_blocks": pcp_ceiling_blocks[:50],
        "pcp_ceiling_resolution_count": pcp_ceiling_resolution_count,
        "pcp_ceiling_resolutions": pcp_ceiling_resolutions[:50],
        "pcp_ceiling_resolution_reason_counts": dict(sorted(pcp_resolution_reason_counts.items())),
        "pcp_ceiling_unresolved_count": pcp_ceiling_unresolved_count,
        "pcp_ceiling_unresolved_samples": unresolved[:20],
        "pcp_ceiling_unresolved_ratio": pcp_ceiling_unresolved_ratio,
        "chain_depth_stats": {
            "max_depth": max(wait_chain_depths, default=0),
            "by_depth": {
                str(depth): count
                for depth, count in sorted(wait_chain_depth_counts.items())
            },
        },
        "unclosed_category_counts": {
            str(category): count
            for category, count in sorted(unresolved_category_counts.items())
        },
        "sample_event_refs": {
            "pip_wait_edges": _build_event_ref_list(pip_wait_edges),
            "pip_owner_mismatch": _build_event_ref_list(pip_owner_mismatch),
            "pcp_ceiling_blocks": _build_event_ref_list(pcp_ceiling_blocks),
            "pcp_ceiling_resolutions": _build_event_ref_list(
                pcp_ceiling_resolutions,
                keys=("blocked_event_id", "resolved_event_id"),
            ),
            "pcp_ceiling_unresolved": _build_event_ref_list(unresolved),
        },
        "failure_samples": {
            "pip_owner_mismatch": pip_owner_mismatch[:10],
            "pcp_ceiling_unresolved": unresolved[:10],
        },
    }


def evaluate_protocol_proof_asset_completeness(protocol_proof_assets: dict[str, Any]) -> CheckOutcome:
    issues_samples: list[dict[str, Any]] = []

    chain_depth_stats = protocol_proof_assets.get("chain_depth_stats")
    if not isinstance(chain_depth_stats, dict) or not isinstance(chain_depth_stats.get("by_depth"), dict):
        issues_samples.append({"field": "chain_depth_stats", "reason": "missing_or_invalid"})

    unclosed_category_counts = protocol_proof_assets.get("unclosed_category_counts")
    if not isinstance(unclosed_category_counts, dict):
        issues_samples.append({"field": "unclosed_category_counts", "reason": "missing_or_invalid"})

    sample_event_refs = protocol_proof_assets.get("sample_event_refs")
    if not isinstance(sample_event_refs, dict):
        issues_samples.append({"field": "sample_event_refs", "reason": "missing_or_invalid"})

    failure_samples = protocol_proof_assets.get("failure_samples")
    if not isinstance(failure_samples, dict):
        issues_samples.append({"field": "failure_samples", "reason": "missing_or_invalid"})

    rule_version = protocol_proof_assets.get("rule_version")
    if not isinstance(rule_version, str) or not rule_version:
        issues_samples.append({"field": "rule_version", "reason": "missing_or_invalid"})

    pip_owner_mismatch_count = int(protocol_proof_assets.get("pip_owner_mismatch_count", 0))
    if pip_owner_mismatch_count > 0:
        refs = sample_event_refs.get("pip_owner_mismatch") if isinstance(sample_event_refs, dict) else None
        samples = failure_samples.get("pip_owner_mismatch") if isinstance(failure_samples, dict) else None
        if not isinstance(refs, list) or not refs:
            issues_samples.append({"field": "sample_event_refs.pip_owner_mismatch", "reason": "expected_non_empty"})
        if not isinstance(samples, list) or not samples:
            issues_samples.append({"field": "failure_samples.pip_owner_mismatch", "reason": "expected_non_empty"})

    pcp_ceiling_unresolved_count = int(protocol_proof_assets.get("pcp_ceiling_unresolved_count", 0))
    if pcp_ceiling_unresolved_count > 0:
        refs = sample_event_refs.get("pcp_ceiling_unresolved") if isinstance(sample_event_refs, dict) else None
        samples = failure_samples.get("pcp_ceiling_unresolved") if isinstance(failure_samples, dict) else None
        if not isinstance(refs, list) or not refs:
            issues_samples.append({"field": "sample_event_refs.pcp_ceiling_unresolved", "reason": "expected_non_empty"})
        if not isinstance(samples, list) or not samples:
            issues_samples.append({"field": "failure_samples.pcp_ceiling_unresolved", "reason": "expected_non_empty"})
        if not isinstance(unclosed_category_counts, dict) or not unclosed_category_counts:
            issues_samples.append({"field": "unclosed_category_counts", "reason": "expected_non_empty"})

    issues: list[dict[str, Any]] = []
    if issues_samples:
        issues.append(
            {
                "rule": "protocol_proof_asset_completeness",
                "severity": "error",
                "message": "research_v2 requires complete protocol proof assets with refs and failure samples",
                "samples": issues_samples[:20],
            }
        )

    return make_check_outcome(
        rule="protocol_proof_asset_completeness",
        passed=not issues_samples,
        issues=issues,
        check_payload={
            "proof_asset_rule_version": rule_version,
            "pip_owner_mismatch_count": pip_owner_mismatch_count,
            "pcp_ceiling_unresolved_count": pcp_ceiling_unresolved_count,
        },
    )


def evaluate_pcp_priority_domain_alignment(
    events: list[dict[str, Any]],
    *,
    scheduler_name: str | None,
) -> CheckOutcome:
    issues_samples: list[dict[str, Any]] = []
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
                issues_samples.append(
                    {
                        "event_id": event.get("event_id"),
                        "observed": priority_domain,
                    }
                )

    issues: list[dict[str, Any]] = []
    if issues_samples:
        issues.append(
            {
                "rule": "pcp_priority_domain_alignment",
                "severity": "error",
                "message": "EDF + PCP must use absolute_deadline priority domain for system ceiling decisions",
                "samples": issues_samples[:20],
            }
        )

    return make_check_outcome(
        rule="pcp_priority_domain_alignment",
        passed=not issues_samples,
        issues=issues,
        check_payload={"scheduler": scheduler_name},
    )


def evaluate_pcp_ceiling_numeric_domain(
    events: list[dict[str, Any]],
    *,
    scheduler_name: str | None,
) -> CheckOutcome:
    issues_samples: list[dict[str, Any]] = []
    if _is_edf_scheduler(scheduler_name):
        for event in events:
            if event.get("type") != "SegmentBlocked":
                continue
            payload = event.get("payload", {})
            if not isinstance(payload, dict):
                continue
            if payload.get("reason") != "system_ceiling_block":
                continue
            system_ceiling = payload.get("system_ceiling")
            if isinstance(system_ceiling, (int, float)) and system_ceiling >= 0:
                issues_samples.append(
                    {
                        "event_id": event.get("event_id"),
                        "system_ceiling": float(system_ceiling),
                    }
                )

    issues: list[dict[str, Any]] = []
    if issues_samples:
        issues.append(
            {
                "rule": "pcp_ceiling_numeric_domain",
                "severity": "error",
                "message": "EDF + PCP system_ceiling should remain in negative priority domain",
                "samples": issues_samples[:20],
            }
        )

    return make_check_outcome(
        rule="pcp_ceiling_numeric_domain",
        passed=not issues_samples,
        issues=issues,
        check_payload={"scheduler": scheduler_name},
    )


def evaluate_pip_priority_chain_consistency(events: list[dict[str, Any]]) -> CheckOutcome:
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

    issues: list[dict[str, Any]] = []
    if pip_chain_issues:
        issues.append(
            {
                "rule": "pip_priority_chain_consistency",
                "severity": "error",
                "message": "resource_busy events must expose a valid owner_segment chain",
                "samples": pip_chain_issues[:20],
            }
        )

    return make_check_outcome(
        rule="pip_priority_chain_consistency",
        passed=not pip_chain_issues,
        issues=issues,
    )


def evaluate_pcp_ceiling_transition_consistency(events: list[dict[str, Any]]) -> CheckOutcome:
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

    issues: list[dict[str, Any]] = []
    if unresolved_ceiling:
        issues.append(
            {
                "rule": "pcp_ceiling_transition_consistency",
                "severity": "error",
                "message": "segments blocked by system ceiling must be unblocked or terminally cleared",
                "samples": unresolved_ceiling[:20],
            }
        )

    return make_check_outcome(
        rule="pcp_ceiling_transition_consistency",
        passed=not unresolved_ceiling,
        issues=issues,
    )


def evaluate_pip_owner_hold_consistency(protocol_proof_assets: dict[str, Any]) -> CheckOutcome:
    pip_owner_mismatch_count = int(protocol_proof_assets["pip_owner_mismatch_count"])

    issues: list[dict[str, Any]] = []
    if pip_owner_mismatch_count > 0:
        issues.append(
            {
                "rule": "pip_owner_hold_consistency",
                "severity": "error",
                "message": "resource_busy owner_segment must match active resource owner",
                "samples": protocol_proof_assets["pip_owner_mismatch_samples"],
            }
        )

    return make_check_outcome(
        rule="pip_owner_hold_consistency",
        passed=pip_owner_mismatch_count == 0,
        issues=issues,
    )
