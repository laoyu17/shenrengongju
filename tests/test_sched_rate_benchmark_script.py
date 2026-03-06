from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "benchmark_sched_rate.py"


def _load_script_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("benchmark_sched_rate_script", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_benchmark_sched_rate_script_generates_stratified_report(tmp_path: Path) -> None:
    script = _load_script_module()
    out_dir = tmp_path / "sched-rate"
    code = script.main(
        [
            "--output-dir",
            str(out_dir),
            "--cases-per-tier",
            "1",
            "--seed",
            "20260304",
            "--target-uplift",
            "0.30",
        ]
    )

    assert code == 0
    report_path = out_dir / "sched-rate-benchmark.json"
    csv_path = out_dir / "sched-rate-benchmark.csv"
    config_list_path = out_dir / "config-list.txt"
    assert report_path.exists()
    assert csv_path.exists()
    assert config_list_path.exists()

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["gate_pass"] is True
    assert "profiles" in report
    assert report["profiles"]["standard_seeded"]["overall"]["total_cases"] == 3
    assert len(report["profiles"]["standard_seeded"]["tiers"]) == 3
    assert report["macro_uplift"] >= 0.3
    assert report["gate_metric"] == "macro_uplift"
    assert "macro_best_candidate_uplift" in report
    assert "candidate_only_uplift" in report["profiles"]["standard_seeded"]["tiers"][0]
    assert report["profiles"]["standard_seeded"]["overall"]["non_empty_case_count"] > 0
    assert report["profiles"]["docx_mixed"]["overall"]["non_empty_case_count"] > 0


def test_benchmark_sched_rate_script_strict_gate_failure_returns_nonzero(tmp_path: Path) -> None:
    script = _load_script_module()
    out_dir = tmp_path / "sched-rate-fail"
    code = script.main(
        [
            "--output-dir",
            str(out_dir),
            "--cases-per-tier",
            "1",
            "--seed",
            "20260304",
            "--target-uplift",
            "2.0",
            "--strict",
        ]
    )

    assert code == 2
