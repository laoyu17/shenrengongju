"""Controller for FR-13 compare panel interactions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from PyQt6.QtWidgets import QFileDialog, QMessageBox

from rtos_sim.analysis import build_compare_report
from rtos_sim.ui.compare_io import (
    read_metrics_json,
    write_compare_report_csv,
    write_compare_report_json,
    write_compare_report_markdown,
)


class UiErrorLogger(Protocol):
    def __call__(self, action: str, exc: Exception, **context: Any) -> None: ...


if TYPE_CHECKING:
    from rtos_sim.ui.app import MainWindow


class CompareController:
    """Keep compare behavior stable while moving logic out of MainWindow."""

    def __init__(self, owner: MainWindow, error_logger: UiErrorLogger) -> None:
        self._owner = owner
        self._error_logger = error_logger

    def _get_left_metrics(self) -> dict[str, Any] | None:
        state = getattr(self._owner, "_compare_panel_state", None)
        if state is not None:
            return state.left_metrics
        return getattr(self._owner, "_compare_left_metrics", None)

    def _set_left_metrics(self, value: dict[str, Any] | None) -> None:
        state = getattr(self._owner, "_compare_panel_state", None)
        if state is not None:
            state.left_metrics = value
            return
        self._owner._compare_left_metrics = value

    def _get_right_metrics(self) -> dict[str, Any] | None:
        state = getattr(self._owner, "_compare_panel_state", None)
        if state is not None:
            return state.right_metrics
        return getattr(self._owner, "_compare_right_metrics", None)

    def _set_right_metrics(self, value: dict[str, Any] | None) -> None:
        state = getattr(self._owner, "_compare_panel_state", None)
        if state is not None:
            state.right_metrics = value
            return
        self._owner._compare_right_metrics = value

    def _get_latest_compare_report(self) -> dict[str, Any] | None:
        state = getattr(self._owner, "_compare_panel_state", None)
        if state is not None:
            return state.latest_report
        return getattr(self._owner, "_latest_compare_report", None)

    def _set_latest_compare_report(self, value: dict[str, Any] | None) -> None:
        state = getattr(self._owner, "_compare_panel_state", None)
        if state is not None:
            state.latest_report = value
            return
        self._owner._latest_compare_report = value

    def on_compare_toggle(self, checked: bool) -> None:
        if self._owner._compare_group is None:
            return
        self._owner._compare_group.setVisible(checked)
        self._owner._compare_toggle_button.setText("Hide FR-13 Compare" if checked else "Show FR-13 Compare")
        self.rebalance_right_splitter(compare_open=checked)
        if checked:
            self.ensure_compare_visible()

    def rebalance_right_splitter(self, *, compare_open: bool) -> None:
        if self._owner._right_splitter is None:
            return
        sizes = self._owner._right_splitter.sizes()
        total = sum(size for size in sizes if size > 0)
        if total <= 0:
            total = max(self._owner._right_splitter.height(), 1)
        lower_ratio = (
            self._owner._RIGHT_SPLITTER_LOWER_RATIO_EXPANDED
            if compare_open
            else self._owner._RIGHT_SPLITTER_LOWER_RATIO_COLLAPSED
        )
        lower_min = (
            self._owner._RIGHT_SPLITTER_LOWER_MIN_EXPANDED
            if compare_open
            else self._owner._RIGHT_SPLITTER_LOWER_MIN_COLLAPSED
        )
        lower_target = max(lower_min, int(total * lower_ratio))
        if lower_target >= total - 60:
            lower_target = max(60, total - 60)
        upper_target = max(60, total - lower_target)
        self._owner._right_splitter.setSizes([upper_target, lower_target])

    def ensure_compare_visible(self) -> None:
        if self._owner._telemetry_scroll is None or self._owner._compare_group is None:
            return
        if not self._owner._compare_group.isVisible():
            return
        self._owner._telemetry_scroll.ensureWidgetVisible(self._owner._compare_group, 0, 24)

    def on_compare_load_left(self) -> None:
        path = self._owner._pick_metrics_file()
        if not path:
            return
        try:
            self._set_left_metrics(read_metrics_json(path))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._error_logger("compare_load_left", exc, path=path)
            QMessageBox.critical(self._owner, "Compare load failed", str(exc))
            return
        self._owner._compare_output.appendPlainText(f"[Compare] left metrics loaded: {path}")

    def on_compare_load_right(self) -> None:
        path = self._owner._pick_metrics_file()
        if not path:
            return
        try:
            self._set_right_metrics(read_metrics_json(path))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._error_logger("compare_load_right", exc, path=path)
            QMessageBox.critical(self._owner, "Compare load failed", str(exc))
            return
        self._owner._compare_output.appendPlainText(f"[Compare] right metrics loaded: {path}")

    def on_compare_use_latest_left(self) -> None:
        if not self._owner._latest_metrics_report:
            QMessageBox.information(self._owner, "Compare", "No latest run metrics available.")
            return
        self._set_left_metrics(dict(self._owner._latest_metrics_report))
        self._owner._compare_output.appendPlainText("[Compare] left metrics set from latest run")

    def on_compare_use_latest_right(self) -> None:
        if not self._owner._latest_metrics_report:
            QMessageBox.information(self._owner, "Compare", "No latest run metrics available.")
            return
        self._set_right_metrics(dict(self._owner._latest_metrics_report))
        self._owner._compare_output.appendPlainText("[Compare] right metrics set from latest run")

    def on_compare_build(self) -> None:
        left_metrics = self._get_left_metrics()
        right_metrics = self._get_right_metrics()
        if left_metrics is None or right_metrics is None:
            QMessageBox.information(
                self._owner,
                "Compare",
                "Please load/set both left and right metrics first.",
            )
            return
        report = build_compare_report(
            left_metrics,
            right_metrics,
            left_label=self._owner._compare_left_label.text().strip() or "left",
            right_label=self._owner._compare_right_label.text().strip() or "right",
        )
        self._set_latest_compare_report(report)
        self._owner._compare_output.setPlainText(json.dumps(report, ensure_ascii=False, indent=2))

    def on_compare_export_json(self) -> None:
        latest_report = self._get_latest_compare_report()
        if latest_report is None:
            QMessageBox.information(self._owner, "Compare", "Build compare report first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self._owner,
            "Save compare report json",
            str(Path.cwd() / "compare_report.json"),
            "JSON Files (*.json)",
        )
        if not path:
            return
        try:
            write_compare_report_json(path, latest_report)
        except OSError as exc:
            QMessageBox.critical(self._owner, "Export failed", str(exc))
            return
        self._owner._status_label.setText(f"Compare JSON exported: {path}")

    def on_compare_export_csv(self) -> None:
        latest_report = self._get_latest_compare_report()
        if latest_report is None:
            QMessageBox.information(self._owner, "Compare", "Build compare report first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self._owner,
            "Save compare report csv",
            str(Path.cwd() / "compare_report.csv"),
            "CSV Files (*.csv)",
        )
        if not path:
            return
        try:
            write_compare_report_csv(path, latest_report)
        except OSError as exc:
            QMessageBox.critical(self._owner, "Export failed", str(exc))
            return
        self._owner._status_label.setText(f"Compare CSV exported: {path}")

    def on_compare_export_markdown(self) -> None:
        latest_report = self._get_latest_compare_report()
        if latest_report is None:
            QMessageBox.information(self._owner, "Compare", "Build compare report first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self._owner,
            "Save compare report markdown",
            str(Path.cwd() / "compare_report.md"),
            "Markdown Files (*.md)",
        )
        if not path:
            return
        try:
            write_compare_report_markdown(path, latest_report)
        except OSError as exc:
            QMessageBox.critical(self._owner, "Export failed", str(exc))
            return
        self._owner._status_label.setText(f"Compare Markdown exported: {path}")
