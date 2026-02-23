from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path

from rtos_sim.analysis.research_report import (
    build_research_report_payload,
    render_research_report_markdown,
    research_report_to_rows,
)


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "research_report.py"
SPEC = spec_from_file_location("research_report_script", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
research_report_script = module_from_spec(SPEC)
SPEC.loader.exec_module(research_report_script)


def _pass_audit() -> dict:
    return {
        "status": "pass",
        "checks": {
            "resource_release_balance": {"passed": True},
            "wait_for_deadlock": {"passed": True},
        },
        "issues": [],
        "protocol_proof_assets": {
            "pip_wait_edge_count": 1,
            "pip_wait_chain_max_depth": 1,
            "pip_wait_owner_coverage": 1.0,
            "pip_owner_mismatch_count": 0,
            "pcp_ceiling_block_count": 1,
            "pcp_ceiling_resolution_count": 1,
            "pcp_ceiling_unresolved_count": 0,
            "pcp_ceiling_unresolved_ratio": 0.0,
        },
        "compliance_profiles": {
            "profiles": {
                "engineering_v1": {
                    "status": "pass",
                    "failed_checks": [],
                    "missing_checks": [],
                    "pass_rate": 1.0,
                },
                "research_v1": {
                    "status": "pass",
                    "failed_checks": [],
                    "missing_checks": [],
                    "pass_rate": 1.0,
                },
            }
        },
    }


def _fail_audit() -> dict:
    payload = _pass_audit()
    payload["status"] = "fail"
    payload["issues"] = [
        {
            "rule": "wait_for_deadlock",
            "severity": "error",
            "message": "cycle detected",
            "samples": [{"event_id": "e4"}],
        }
    ]
    payload["checks"]["wait_for_deadlock"] = {"passed": False, "sample_event_ids": ["e4"]}
    payload["compliance_profiles"]["profiles"]["research_v1"]["status"] = "fail"
    payload["compliance_profiles"]["profiles"]["research_v1"]["failed_checks"] = ["wait_for_deadlock"]
    return payload


def _relations(status: str = "pass") -> dict:
    return {"status": status}


def _quality(status: str = "pass") -> dict:
    return {
        "status": status,
        "pytest": {"passed": 216, "failed": 0},
        "coverage": {"line_rate": 87.0, "line_rate_display": "87"},
    }


def test_build_research_report_payload_pass() -> None:
    report = build_research_report_payload(
        audit_report=_pass_audit(),
        model_relations_report=_relations("pass"),
        quality_snapshot=_quality("pass"),
    )

    assert report["status"] == "pass"
    assert report["statuses"]["research_v1"] == "pass"
    assert report["failed_check_details"] == []


def test_build_research_report_payload_fail_and_markdown_render() -> None:
    report = build_research_report_payload(
        audit_report=_fail_audit(),
        model_relations_report=_relations("pass"),
        quality_snapshot=_quality("pass"),
    )

    assert report["status"] == "fail"
    assert report["failed_check_details"][0]["rule"] == "wait_for_deadlock"

    md = render_research_report_markdown(report)
    assert "总体状态" in md
    assert "wait_for_deadlock" in md

    rows = research_report_to_rows(report)
    assert any(row["category"] == "failed_check" for row in rows)


def test_build_research_report_payload_includes_non_audit_fail_reasons() -> None:
    relations = {
        "status": "warn",
        "checks": {
            "segment_core_binding_coverage": {"passed": False},
            "resource_bound_core_consistency": {"passed": True},
        },
        "compliance_profiles": {
            "profiles": {
                "engineering_v1": {"status": "warn"},
                "research_v1": {"status": "warn"},
            }
        },
    }

    report = build_research_report_payload(
        audit_report=_pass_audit(),
        model_relations_report=relations,
        quality_snapshot=_quality("pass"),
    )

    assert report["status"] == "fail"
    assert report["failed_check_details"] == []
    assert report["non_audit_fail_details"][0]["source"] == "model_relations"
    assert report["non_audit_fail_details"][0]["status"] == "warn"
    assert report["non_audit_fail_details"][0]["failed_rules"] == ["segment_core_binding_coverage"]

    rows = research_report_to_rows(report)
    assert any(row["category"] == "non_audit_failure" for row in rows)

    md = render_research_report_markdown(report)
    assert "非审计失败原因" in md
    assert "segment_core_binding_coverage" in md


def test_research_report_script_outputs_files_and_strict_mode(tmp_path: Path) -> None:
    audit_path = tmp_path / "audit.json"
    rel_path = tmp_path / "relations.json"
    quality_path = tmp_path / "quality.json"
    audit_path.write_text(json.dumps(_fail_audit(), ensure_ascii=False, indent=2), encoding="utf-8")
    rel_path.write_text(json.dumps(_relations("pass"), ensure_ascii=False, indent=2), encoding="utf-8")
    quality_path.write_text(json.dumps(_quality("pass"), ensure_ascii=False, indent=2), encoding="utf-8")

    out_md = tmp_path / "report.md"
    out_csv = tmp_path / "report.csv"
    out_json = tmp_path / "report.json"

    code = research_report_script.main(
        [
            "--audit",
            str(audit_path),
            "--relations",
            str(rel_path),
            "--quality",
            str(quality_path),
            "--out-markdown",
            str(out_md),
            "--out-csv",
            str(out_csv),
            "--out-json",
            str(out_json),
        ]
    )
    assert code == 0
    assert out_md.exists()
    assert out_csv.exists()
    assert out_json.exists()

    strict_code = research_report_script.main(
        [
            "--audit",
            str(audit_path),
            "--relations",
            str(rel_path),
            "--quality",
            str(quality_path),
            "--out-markdown",
            str(tmp_path / "report_strict.md"),
            "--out-csv",
            str(tmp_path / "report_strict.csv"),
            "--out-json",
            str(tmp_path / "report_strict.json"),
            "--strict",
        ]
    )
    assert strict_code == 2


def test_build_research_report_payload_aggregates_multiple_issues_per_rule() -> None:
    audit = _pass_audit()
    audit["status"] = "fail"
    audit["checks"]["wait_for_deadlock"] = {"passed": False, "sample_event_ids": ["e1", "e2", "e3"]}
    audit["issues"] = [
        {
            "rule": "wait_for_deadlock",
            "severity": "error",
            "message": "cycle A",
            "samples": [{"event_id": "e1"}],
        },
        {
            "rule": "wait_for_deadlock",
            "severity": "error",
            "message": "cycle B",
            "samples": [{"event_id": "e2"}, {"event_id": "e3"}],
        },
    ]
    audit["compliance_profiles"]["profiles"]["engineering_v1"]["status"] = "fail"
    audit["compliance_profiles"]["profiles"]["engineering_v1"]["failed_checks"] = ["wait_for_deadlock"]
    audit["compliance_profiles"]["profiles"]["research_v1"]["status"] = "fail"
    audit["compliance_profiles"]["profiles"]["research_v1"]["failed_checks"] = ["wait_for_deadlock"]

    report = build_research_report_payload(
        audit_report=audit,
        model_relations_report=_relations("pass"),
        quality_snapshot=_quality("pass"),
    )
    detail = report["failed_check_details"][0]

    assert detail["rule"] == "wait_for_deadlock"
    assert detail["issue_count"] == 2
    assert detail["sample_count"] == 3
    assert detail["sample_event_ids"] == ["e1", "e2", "e3"]
    assert "cycle A" in detail["message"]
    assert "cycle B" in detail["message"]
