from __future__ import annotations

import json
from pathlib import Path

import pytest

from rtos_sim.ui.compare_io import (
    read_metrics_json,
    write_compare_report_csv,
    write_compare_report_json,
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


def test_write_compare_report_json_and_csv(tmp_path: Path) -> None:
    report = {
        "scalar_metrics": [
            {
                "metric": "jobs_completed",
                "left": 2,
                "right": 3,
                "delta": 1,
            }
        ],
        "core_utilization": [
            {
                "core_id": "c0",
                "left": 0.4,
                "right": 0.5,
                "delta": 0.1,
            }
        ],
    }

    json_path = tmp_path / "compare.json"
    write_compare_report_json(json_path, report)
    assert json.loads(json_path.read_text(encoding="utf-8")) == report

    csv_path = tmp_path / "compare.csv"
    write_compare_report_csv(csv_path, report)
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "category,metric,left,right,delta,core_id" in csv_text
    assert "scalar,jobs_completed,2,3,1," in csv_text
    assert "core_utilization,c0,0.4,0.5,0.1,c0" in csv_text
