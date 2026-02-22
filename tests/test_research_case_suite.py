from __future__ import annotations

from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "research_case_suite.py"
SPEC = spec_from_file_location("research_case_suite", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
research_case_suite = module_from_spec(SPEC)
SPEC.loader.exec_module(research_case_suite)


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_research_case_suite_matches_counterexample_manifest(tmp_path: Path) -> None:
    manifest = json.loads((EXAMPLES / "research_counterexamples.json").read_text(encoding="utf-8"))

    summary = research_case_suite.run_research_case_suite(
        manifest=manifest,
        audit_dir=tmp_path / "audits",
    )

    assert summary["status"] == "pass"
    assert summary["total_cases"] == 12
    assert summary["mismatched_cases"] == 0

    groups = {row["group"] for row in summary["cases"]}
    assert groups == {
        "abort_cancel_release_visibility",
        "pip_owner_hold_consistency",
        "pcp_ceiling_transition_consistency",
        "wait_for_deadlock",
        "resource_partial_hold_on_block",
        "pcp_priority_domain_alignment",
    }


def test_research_case_suite_main_returns_non_zero_when_mismatch(tmp_path: Path) -> None:
    manifest = json.loads((EXAMPLES / "research_counterexamples.json").read_text(encoding="utf-8"))
    bad_manifest = deepcopy(manifest)
    bad_manifest["cases"][0]["expected"]["status"] = "pass"

    case_path = tmp_path / "bad_cases.json"
    case_path.write_text(json.dumps(bad_manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    code = research_case_suite.main(
        [
            "--cases",
            str(case_path),
            "--out-json",
            str(tmp_path / "summary.json"),
            "--out-csv",
            str(tmp_path / "summary.csv"),
            "--audit-dir",
            str(tmp_path / "audits"),
        ]
    )
    assert code == 2

    code_allow = research_case_suite.main(
        [
            "--cases",
            str(case_path),
            "--out-json",
            str(tmp_path / "summary_allow.json"),
            "--out-csv",
            str(tmp_path / "summary_allow.csv"),
            "--audit-dir",
            str(tmp_path / "audits_allow"),
            "--allow-mismatch",
        ]
    )
    assert code_allow == 0


def test_research_case_suite_requires_exact_failed_check_match(tmp_path: Path) -> None:
    manifest = {
        "version": "0.1",
        "cases": [
            {
                "id": "strict_failed_checks",
                "group": "strictness",
                "scheduler_name": "edf",
                "expected": {
                    "status": "fail",
                    "failed_checks": ["pcp_priority_domain_alignment"],
                },
                "events": [
                    {
                        "event_id": "e1",
                        "type": "SegmentBlocked",
                        "job_id": "pcp@0",
                        "resource_id": "r0",
                        "payload": {
                            "segment_key": "pcp@0:s0:seg0",
                            "reason": "system_ceiling_block",
                            "priority_domain": "fixed_priority",
                            "system_ceiling": 3.0,
                        },
                    }
                ],
            }
        ],
    }

    summary = research_case_suite.run_research_case_suite(
        manifest=manifest,
        audit_dir=tmp_path / "audits",
    )
    assert summary["status"] == "fail"
    assert summary["mismatched_cases"] == 1

    case = summary["cases"][0]
    assert case["matched"] is False
    assert case["missing_expected_checks"] == []
    assert "pcp_ceiling_numeric_domain" in case["unexpected_actual_checks"]
