"""Build research-facing review reports from audit/relation/quality artifacts."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _profile_status(audit_report: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profiles = _safe_dict(_safe_dict(audit_report.get("compliance_profiles")).get("profiles"))
    profile = _safe_dict(profiles.get(profile_name))
    return {
        "status": str(profile.get("status") or "unknown"),
        "failed_checks": sorted(
            item for item in profile.get("failed_checks", []) if isinstance(item, str)
        ),
        "missing_checks": sorted(
            item for item in profile.get("missing_checks", []) if isinstance(item, str)
        ),
        "pass_rate": profile.get("pass_rate"),
    }


def _failed_check_details(audit_report: dict[str, Any], failed_checks: list[str]) -> list[dict[str, Any]]:
    issue_by_rule: dict[str, list[dict[str, Any]]] = {}
    for issue in audit_report.get("issues", []):
        if not isinstance(issue, dict):
            continue
        rule = issue.get("rule")
        if isinstance(rule, str) and rule:
            issue_by_rule.setdefault(rule, []).append(issue)

    details: list[dict[str, Any]] = []
    checks = _safe_dict(audit_report.get("checks"))
    severity_rank = {"error": 3, "warning": 2, "warn": 2, "info": 1}
    for rule in failed_checks:
        check = _safe_dict(checks.get(rule))
        issues = issue_by_rule.get(rule, [])
        sample_count = 0
        severities: list[str] = []
        messages: list[str] = []
        sample_event_ids: set[str] = set()
        for issue in issues:
            severity = issue.get("severity")
            if isinstance(severity, str) and severity:
                severities.append(severity.lower())

            message = issue.get("message")
            if isinstance(message, str) and message:
                messages.append(message)

            direct_event_id = issue.get("event_id")
            if isinstance(direct_event_id, str) and direct_event_id:
                sample_event_ids.add(direct_event_id)

            samples = issue.get("samples")
            if isinstance(samples, list):
                sample_count += len(samples)
                for sample in samples:
                    if not isinstance(sample, dict):
                        continue
                    sample_event_id = sample.get("event_id")
                    if isinstance(sample_event_id, str) and sample_event_id:
                        sample_event_ids.add(sample_event_id)
            elif isinstance(direct_event_id, str) and direct_event_id:
                sample_count += 1

        for event_id in check.get("sample_event_ids", []):
            if isinstance(event_id, str) and event_id:
                sample_event_ids.add(event_id)

        dedup_messages: list[str] = []
        seen_messages: set[str] = set()
        for message in messages:
            if message not in seen_messages:
                dedup_messages.append(message)
                seen_messages.add(message)

        if sample_count == 0 and sample_event_ids:
            sample_count = len(sample_event_ids)
        details.append(
            {
                "rule": rule,
                "severity": (
                    max(severities, key=lambda item: severity_rank.get(item, 0))
                    if severities
                    else "error"
                ),
                "issue_count": len(issues),
                "message": "; ".join(dedup_messages) if dedup_messages else "check failed",
                "sample_count": sample_count,
                "sample_event_ids": sorted(sample_event_ids),
            }
        )
    return details


def build_research_report_payload(
    *,
    audit_report: dict[str, Any] | None,
    model_relations_report: dict[str, Any] | None,
    quality_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    audit = _safe_dict(audit_report)
    relations = _safe_dict(model_relations_report)
    quality = _safe_dict(quality_snapshot)

    engineering_profile = _profile_status(audit, "engineering_v1")
    research_profile = _profile_status(audit, "research_v1")

    audit_status = str(audit.get("status") or "unknown") if audit else "missing"
    model_status = str(relations.get("status") or "unknown") if relations else "missing"
    quality_status = str(quality.get("status") or "unknown") if quality else "missing"

    warnings: list[str] = []
    if not audit:
        warnings.append("missing audit report")
    if not relations:
        warnings.append("missing model relations report")
    if not quality:
        warnings.append("missing quality snapshot")

    overall_status = "incomplete"
    if not warnings:
        if (
            research_profile["status"] == "pass"
            and engineering_profile["status"] == "pass"
            and model_status == "pass"
            and quality_status == "pass"
        ):
            overall_status = "pass"
        else:
            overall_status = "fail"

    failed_checks = sorted(set(research_profile["failed_checks"] + engineering_profile["failed_checks"]))
    failed_check_details = _failed_check_details(audit, failed_checks)

    quality_pytest = _safe_dict(quality.get("pytest"))
    quality_coverage = _safe_dict(quality.get("coverage"))
    proof_assets = _safe_dict(audit.get("protocol_proof_assets"))

    return {
        "report_version": "0.1",
        "generated_at_utc": _utc_now(),
        "status": overall_status,
        "warnings": warnings,
        "statuses": {
            "audit": audit_status,
            "model_relations": model_status,
            "quality": quality_status,
            "engineering_v1": engineering_profile["status"],
            "research_v1": research_profile["status"],
        },
        "profiles": {
            "engineering_v1": engineering_profile,
            "research_v1": research_profile,
        },
        "failed_check_details": failed_check_details,
        "quality": {
            "pytest_passed": quality_pytest.get("passed"),
            "pytest_failed": quality_pytest.get("failed"),
            "coverage_line_rate": quality_coverage.get("line_rate"),
            "coverage_line_rate_display": quality_coverage.get("line_rate_display"),
        },
        "proof_assets": {
            "pip_wait_edge_count": proof_assets.get("pip_wait_edge_count"),
            "pip_wait_chain_max_depth": proof_assets.get("pip_wait_chain_max_depth"),
            "pip_wait_owner_coverage": proof_assets.get("pip_wait_owner_coverage"),
            "pip_owner_mismatch_count": proof_assets.get("pip_owner_mismatch_count"),
            "pcp_ceiling_block_count": proof_assets.get("pcp_ceiling_block_count"),
            "pcp_ceiling_resolution_count": proof_assets.get("pcp_ceiling_resolution_count"),
            "pcp_ceiling_unresolved_count": proof_assets.get("pcp_ceiling_unresolved_count"),
            "pcp_ceiling_unresolved_ratio": proof_assets.get("pcp_ceiling_unresolved_ratio"),
        },
    }


def research_report_to_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    statuses = _safe_dict(report.get("statuses"))
    for name, value in sorted(statuses.items()):
        rows.append({"category": "status", "name": name, "value": value})

    for item in report.get("failed_check_details", []):
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "category": "failed_check",
                "name": item.get("rule"),
                "value": item.get("severity"),
                "message": item.get("message"),
                "issue_count": item.get("issue_count"),
                "sample_count": item.get("sample_count"),
                "sample_event_ids": "|".join(item.get("sample_event_ids", [])),
            }
        )

    quality = _safe_dict(report.get("quality"))
    for name, value in sorted(quality.items()):
        rows.append({"category": "quality", "name": name, "value": value})

    proof_assets = _safe_dict(report.get("proof_assets"))
    for name, value in sorted(proof_assets.items()):
        rows.append({"category": "proof_assets", "name": name, "value": value})

    return rows


def render_research_report_markdown(report: dict[str, Any]) -> str:
    statuses = _safe_dict(report.get("statuses"))
    quality = _safe_dict(report.get("quality"))
    proof_assets = _safe_dict(report.get("proof_assets"))
    failed_checks = [
        item
        for item in report.get("failed_check_details", [])
        if isinstance(item, dict)
    ]

    lines: list[str] = []
    lines.append("# 研究闭环评审报告")
    lines.append("")
    lines.append(f"- 生成时间：{report.get('generated_at_utc')}")
    lines.append(f"- 总体状态：**{report.get('status', 'unknown')}**")

    warnings = report.get("warnings", [])
    if isinstance(warnings, list) and warnings:
        lines.append(f"- 警告：{'; '.join(str(item) for item in warnings)}")

    lines.append("")
    lines.append("## 状态总览")
    lines.append("| 维度 | 状态 |")
    lines.append("|---|---|")
    for name in ["engineering_v1", "research_v1", "audit", "model_relations", "quality"]:
        lines.append(f"| {name} | {statuses.get(name, 'unknown')} |")

    lines.append("")
    lines.append("## 失败检查项")
    if not failed_checks:
        lines.append("- 无")
    else:
        for item in failed_checks:
            sample_ids = item.get("sample_event_ids", [])
            sample_text = ",".join(sample_ids) if isinstance(sample_ids, list) and sample_ids else "-"
            lines.append(
                "- "
                f"{item.get('rule')} ({item.get('severity')}): "
                f"{item.get('message')} | issues={item.get('issue_count')} "
                f"| samples={item.get('sample_count')} | event_ids={sample_text}"
            )

    lines.append("")
    lines.append("## 质量快照")
    lines.append(f"- pytest passed: {quality.get('pytest_passed')}")
    lines.append(f"- pytest failed: {quality.get('pytest_failed')}")
    lines.append(f"- coverage line rate: {quality.get('coverage_line_rate_display')}")

    lines.append("")
    lines.append("## 证明资产摘要")
    for key in [
        "pip_wait_edge_count",
        "pip_wait_chain_max_depth",
        "pip_wait_owner_coverage",
        "pip_owner_mismatch_count",
        "pcp_ceiling_block_count",
        "pcp_ceiling_resolution_count",
        "pcp_ceiling_unresolved_count",
        "pcp_ceiling_unresolved_ratio",
    ]:
        lines.append(f"- {key}: {proof_assets.get(key)}")

    return "\n".join(lines) + "\n"
