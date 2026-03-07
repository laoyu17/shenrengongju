"""Post-simulation audit checks for protocol/event correctness."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .audit_checks import (
    analyze_time_deterministic_ready,
    build_protocol_proof_assets,
    evaluate_abort_cancel_release_visibility,
    evaluate_pcp_ceiling_numeric_domain,
    evaluate_pcp_ceiling_transition_consistency,
    evaluate_pcp_priority_domain_alignment,
    evaluate_protocol_proof_asset_completeness,
    evaluate_pip_owner_hold_consistency,
    evaluate_pip_priority_chain_consistency,
    evaluate_resource_partial_hold_on_block,
    evaluate_resource_release_balance,
    evaluate_time_deterministic_ready_consistency,
    evaluate_wait_for_deadlock,
)
from .audit_report_builder import append_check_outcome


AUDIT_RULE_VERSION = "0.4"
AUDIT_COMPLIANCE_PROFILE_VERSION = "0.2"
AUDIT_PROOF_ASSET_VERSION = "0.2"
AUDIT_CHECK_CATALOG_VERSION = "0.2"
AUDIT_TIME_DETERMINISTIC_PROOF_VERSION = "0.1"

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
    "time_deterministic_ready_consistency",
)

RESEARCH_V2_REQUIRED_CHECKS: tuple[str, ...] = (
    *RESEARCH_REQUIRED_CHECKS,
    "protocol_proof_asset_completeness",
)

CHECK_CATALOG: dict[str, dict[str, Any]] = {
    "resource_release_balance": {
        "severity": "error",
        "description": "ResourceAcquire/ResourceRelease must remain balanced per segment-resource hold key.",
        "profiles": ["engineering_v1", "research_v1", "research_v2"],
    },
    "abort_cancel_release_visibility": {
        "severity": "error",
        "description": "Aborted jobs that held resources must emit cancel-segment ResourceRelease records.",
        "profiles": ["engineering_v1", "research_v1", "research_v2"],
    },
    "pcp_priority_domain_alignment": {
        "severity": "error",
        "description": "EDF+PCP blocked events must use absolute_deadline priority domain.",
        "profiles": ["research_v1", "research_v2"],
    },
    "pcp_ceiling_numeric_domain": {
        "severity": "error",
        "description": "EDF+PCP system ceiling should stay in negative numeric domain.",
        "profiles": ["research_v1", "research_v2"],
    },
    "resource_partial_hold_on_block": {
        "severity": "error",
        "description": "atomic_rollback blocked segments must not keep partially acquired resources.",
        "profiles": ["engineering_v1", "research_v1", "research_v2"],
    },
    "pip_priority_chain_consistency": {
        "severity": "error",
        "description": "resource_busy events must expose a valid non-self owner_segment chain.",
        "profiles": ["research_v1", "research_v2"],
    },
    "pcp_ceiling_transition_consistency": {
        "severity": "error",
        "description": "system_ceiling_block segments must be unblocked or terminally cleared.",
        "profiles": ["research_v1", "research_v2"],
    },
    "wait_for_deadlock": {
        "severity": "error",
        "description": "wait-for graph must remain acyclic among blocked segments.",
        "profiles": ["engineering_v1", "research_v1", "research_v2"],
    },
    "pip_owner_hold_consistency": {
        "severity": "error",
        "description": "resource_busy owner_segment must match the active runtime owner of the same resource.",
        "profiles": ["research_v1", "research_v2"],
    },
    "time_deterministic_ready_consistency": {
        "severity": "error",
        "description": (
            "time_deterministic SegmentReady events must align with deterministic_ready_time "
            "and remain phase-stable across hyper-period windows."
        ),
        "profiles": ["research_v1", "research_v2"],
    },
    "protocol_proof_asset_completeness": {
        "severity": "error",
        "description": "research_v2 requires categorized protocol proof assets with event refs and failure samples.",
        "profiles": ["research_v2"],
    },
}


def _collect_issue_event_ids(issue: dict[str, Any]) -> list[str]:
    ids: set[str] = set()
    direct_event_id = issue.get("event_id")
    if isinstance(direct_event_id, str) and direct_event_id:
        ids.add(direct_event_id)

    samples = issue.get("samples")
    if isinstance(samples, list):
        for sample in samples:
            if not isinstance(sample, dict):
                continue
            event_id = sample.get("event_id")
            if isinstance(event_id, str) and event_id:
                ids.add(event_id)
    return sorted(ids)


def _enrich_checks_with_issue_refs(checks: dict[str, Any], issues: list[dict[str, Any]]) -> None:
    by_rule: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for issue in issues:
        rule = issue.get("rule")
        if isinstance(rule, str) and rule:
            by_rule[rule].append(issue)

    for rule, result in checks.items():
        if not isinstance(result, dict):
            continue
        related = by_rule.get(rule, [])
        result["issue_count"] = len(related)
        event_ids: set[str] = set()
        for issue in related:
            event_ids.update(_collect_issue_event_ids(issue))
        if event_ids:
            result["sample_event_ids"] = sorted(event_ids)[:20]


def _build_check_catalog() -> dict[str, Any]:
    return {
        "catalog_version": AUDIT_CHECK_CATALOG_VERSION,
        "checks": CHECK_CATALOG,
    }


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
    failed_check_event_refs = {
        rule: result.get("sample_event_ids", [])
        for rule, result in checks.items()
        if isinstance(result, dict)
        and result.get("passed") is False
        and isinstance(result.get("sample_event_ids"), list)
        and result.get("sample_event_ids")
    }
    return {
        "scheduler_name": scheduler_name,
        "event_count": len(events),
        "event_type_counts": dict(sorted(event_type_counts.items())),
        "checks_evaluated": len(checks),
        "checks_failed": failed_checks,
        "checks_passed": len(checks) - len(failed_checks),
        "failed_check_event_refs": failed_check_event_refs,
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
            "research_v2": {
                "description": "研究增强基线，额外要求协议证明资产具备分类统计、事件引用与失败样本。",
                **_build_profile_status(checks, RESEARCH_V2_REQUIRED_CHECKS),
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

    protocol_proof_assets = build_protocol_proof_assets(events)
    time_deterministic_proof_assets = analyze_time_deterministic_ready(events)

    outcomes = [
        evaluate_resource_release_balance(events),
        evaluate_abort_cancel_release_visibility(events),
        evaluate_pcp_priority_domain_alignment(events, scheduler_name=scheduler_name),
        evaluate_pcp_ceiling_numeric_domain(events, scheduler_name=scheduler_name),
        evaluate_resource_partial_hold_on_block(events),
        evaluate_pip_priority_chain_consistency(events),
        evaluate_pcp_ceiling_transition_consistency(events),
        evaluate_wait_for_deadlock(events),
        evaluate_pip_owner_hold_consistency(protocol_proof_assets),
        evaluate_time_deterministic_ready_consistency(time_deterministic_proof_assets),
        evaluate_protocol_proof_asset_completeness(protocol_proof_assets),
    ]

    for outcome in outcomes:
        append_check_outcome(checks=checks, issues=issues, outcome=outcome)

    _enrich_checks_with_issue_refs(checks, issues)

    report = {
        "rule_version": AUDIT_RULE_VERSION,
        "status": "pass" if not issues else "fail",
        "issue_count": len(issues),
        "issues": issues,
        "checks": checks,
        "check_catalog": _build_check_catalog(),
        "evidence": _build_audit_evidence(events, checks, scheduler_name=scheduler_name),
        "protocol_proof_assets": protocol_proof_assets,
        "time_deterministic_proof_assets": time_deterministic_proof_assets,
        "compliance_profiles": _build_compliance_profiles(checks),
    }
    if isinstance(model_relation_summary, dict):
        report["model_relation_summary"] = model_relation_summary
    return report
