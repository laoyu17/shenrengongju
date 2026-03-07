from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def _extract_run_step_block(script_text: str, step_label: str) -> str:
    pattern = re.compile(
        rf"run_step\s+\d+\s+{re.escape(step_label)}\b[\s\S]*?(?=\nrun_step\s+\d+\s+|\nif\s+\[\[|\Z)"
    )
    match = pattern.search(script_text)
    assert match is not None, f"missing run_step block: {step_label}"
    return match.group(0)


def _assert_default_strict_plan_match(block: str, command_name: str) -> None:
    assert command_name in block
    assert "--plan-json" in block
    assert "--allow-plan-mismatch" not in block
    assert "--strict-plan-match" not in block


def test_i1_ci_gate_uses_default_strict_plan_match_for_wcrt_and_export() -> None:
    script = (ROOT / "review/scripts/i1_ci_gate.sh").read_text(encoding="utf-8")
    _assert_default_strict_plan_match(_extract_run_step_block(script, "wcrt_at06_strict"), "analyze-wcrt")
    _assert_default_strict_plan_match(_extract_run_step_block(script, "export_os_at06_strict"), "export-os-config")


def test_strict_plan_pipeline_uses_default_strict_plan_match_for_wcrt_and_export() -> None:
    script = (ROOT / "review/scripts/strict_plan_pipeline.sh").read_text(encoding="utf-8")
    _assert_default_strict_plan_match(_extract_run_step_block(script, "analyze_wcrt_strict"), "analyze-wcrt")
    _assert_default_strict_plan_match(_extract_run_step_block(script, "export_os_strict"), "export-os-config")
