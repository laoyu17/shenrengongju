"""Controller for exporting research-facing review reports from UI state."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from PyQt6.QtWidgets import QFileDialog, QMessageBox

from rtos_sim.analysis import (
    build_audit_report,
    build_model_relations_report,
    build_research_report_payload,
    render_research_report_markdown,
    research_report_to_rows,
)


class UiErrorLogger(Protocol):
    def __call__(self, action: str, exc: Exception, **context: Any) -> None: ...


if TYPE_CHECKING:
    from rtos_sim.ui.app import MainWindow


class ResearchReportController:
    """Build and export research report artifacts from cached UI runtime state."""

    def __init__(self, owner: MainWindow, error_logger: UiErrorLogger) -> None:
        self._owner = owner
        self._error_logger = error_logger

    def _cached_quality_snapshot(self) -> dict[str, Any] | None:
        cached = getattr(self._owner, "_latest_quality_snapshot", None)
        if isinstance(cached, dict):
            return cached

        snapshot_path = Path.cwd() / "artifacts" / "quality" / "quality-snapshot.json"
        if not snapshot_path.exists():
            return None

        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"quality snapshot root must be object: {snapshot_path}")
        self._owner._latest_quality_snapshot = payload
        return payload

    def _write_rows_csv(self, path: Path, rows: list[dict[str, Any]]) -> None:
        fieldnames: list[str] = []
        for row in rows:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    def on_research_export(self) -> None:
        spec = getattr(self._owner, "_latest_run_spec", None)
        events = getattr(self._owner, "_latest_run_events", None)
        if spec is None or events is None:
            QMessageBox.information(
                self._owner,
                "Research Report",
                "Run simulation first to capture spec/events for research export.",
            )
            return

        path, _ = QFileDialog.getSaveFileName(
            self._owner,
            "Save research report markdown",
            str(Path.cwd() / "artifacts" / "research" / "research-report.md"),
            "Markdown Files (*.md)",
        )
        if not path:
            return

        markdown_path = Path(path)
        if markdown_path.suffix.lower() != ".md":
            markdown_path = markdown_path.with_suffix(".md")
        json_path = markdown_path.with_suffix(".json")
        csv_path = markdown_path.with_name(f"{markdown_path.stem}-summary.csv")

        try:
            relations_report = build_model_relations_report(spec)
            audit_report = build_audit_report(
                list(events),
                scheduler_name=getattr(getattr(spec, "scheduler", None), "name", None),
                model_relation_summary=(
                    relations_report.get("summary") if isinstance(relations_report, dict) else None
                ),
            )
            quality_snapshot = self._cached_quality_snapshot()
            research_report = build_research_report_payload(
                audit_report=audit_report,
                model_relations_report=relations_report,
                quality_snapshot=quality_snapshot,
            )
            markdown = render_research_report_markdown(research_report)
            rows = research_report_to_rows(research_report)

            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.write_text(markdown, encoding="utf-8")
            json_path.write_text(json.dumps(research_report, ensure_ascii=False, indent=2), encoding="utf-8")
            self._write_rows_csv(csv_path, rows)
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self._error_logger("research_report_export", exc, path=str(markdown_path))
            QMessageBox.critical(self._owner, "Research report export failed", str(exc))
            return

        self._owner._latest_model_relations_report = relations_report
        self._owner._latest_audit_report = audit_report
        self._owner._latest_research_report = research_report
        if quality_snapshot is not None:
            self._owner._latest_quality_snapshot = quality_snapshot
        self._owner._status_label.setText(
            f"Research report exported: {markdown_path}"
        )
