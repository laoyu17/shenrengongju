from __future__ import annotations

import json
from pathlib import Path

import pytest

from rtos_sim.analysis import build_compare_report
from rtos_sim.ui.compare_io import (
    read_metrics_json,
    write_compare_report_csv,
    write_compare_report_json,
    write_compare_report_markdown,
)


def test_read_metrics_json_requires_object_root(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")

    with pytest.raises(ValueError, match="root must be object"):
        read_metrics_json(metrics_path)


def test_read_metrics_json_success(tmp_path: Path) -> None:
    payload = {"jobs_completed": 2, "deadline_miss_count": 0}
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text(json.dumps(payload), encoding="utf-8")

    assert read_metrics_json(metrics_path) == payload


def test_write_compare_report_json_csv_and_markdown(tmp_path: Path) -> None:
    report = build_compare_report(
        {"jobs_completed": 2, "core_utilization": {"c0": 0.4}},
        {"jobs_completed": 3, "core_utilization": {"c0": 0.5}},
        left_label="baseline",
        right_label="candidate",
    )

    json_path = tmp_path / "compare.json"
    write_compare_report_json(json_path, report)
    assert json.loads(json_path.read_text(encoding="utf-8")) == report

    csv_path = tmp_path / "compare.csv"
    write_compare_report_csv(csv_path, report)
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "category,metric,left,right,delta,delta_ratio_pct,core_id" in csv_text
    assert "scalar,jobs_completed,2.0,3.0,1.0,50.0," in csv_text
    assert "core_utilization,c0,0.4,0.5,0.09999999999999998,24.999999999999993,c0" in csv_text
    assert "scalar_summary,jobs_completed" in csv_text
    assert "core_utilization_summary,c0" in csv_text

    markdown_path = tmp_path / "compare.md"
    write_compare_report_markdown(markdown_path, report)
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "# Compare 报告" in markdown
    assert "## 双方案标量差分" in markdown
    assert "## N-way 标量聚合" in markdown
