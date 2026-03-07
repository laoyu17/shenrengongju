"""I/O helpers for FR-13 compare panel data."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from rtos_sim.analysis import compare_report_to_rows, render_compare_report_markdown


def read_metrics_json(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("metrics json root must be object")
    return payload


def write_compare_report_json(path: str | Path, report: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_compare_report_csv(path: str | Path, report: dict[str, Any]) -> None:
    rows = compare_report_to_rows(report)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_compare_report_markdown(path: str | Path, report: dict[str, Any]) -> None:
    Path(path).write_text(render_compare_report_markdown(report), encoding="utf-8")
