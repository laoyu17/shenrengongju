"""Controller for FR-13 compare panel interactions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from PyQt6.QtWidgets import QFileDialog, QMessageBox

from rtos_sim.analysis import build_multi_compare_report
from rtos_sim.ui.compare_io import (
    read_metrics_json,
    write_compare_report_csv,
    write_compare_report_json,
    write_compare_report_markdown,
)
from rtos_sim.ui.panel_state import ComparePanelState, CompareScenarioState


class UiErrorLogger(Protocol):
    def __call__(self, action: str, exc: Exception, **context: Any) -> None: ...


if TYPE_CHECKING:
    from rtos_sim.ui.app import MainWindow


class CompareController:
    """Keep compare behavior stable while moving logic out of MainWindow."""

    def __init__(self, owner: MainWindow, error_logger: UiErrorLogger) -> None:
        self._owner = owner
        self._error_logger = error_logger

    def _get_compare_state(self) -> ComparePanelState | None:
        state = getattr(self._owner, "_compare_panel_state", None)
        return state if state is not None else None

    def _get_scenarios(self) -> list[CompareScenarioState]:
        state = self._get_compare_state()
        if state is None:
            return []
        return state.scenarios

    def _get_latest_compare_report(self) -> dict[str, Any] | None:
        state = self._get_compare_state()
        if state is not None:
            return state.latest_report
        return getattr(self._owner, "_latest_compare_report", None)

    def _set_latest_compare_report(self, value: dict[str, Any] | None) -> None:
        state = self._get_compare_state()
        if state is not None:
            state.latest_report = value
            return
        self._owner._latest_compare_report = value

    def _default_label(self, index: int) -> str:
        if index == 0:
            return "baseline"
        if index == 1:
            return "focus"
        return f"scenario_{index + 1}"

    def _pending_label_widget_text(self) -> str:
        widget = getattr(self._owner, "_compare_scenario_label", None)
        if widget is None:
            return ""
        return widget.text().strip()

    def _consume_pending_label(self, fallback: str) -> str:
        widget = getattr(self._owner, "_compare_scenario_label", None)
        text = widget.text().strip() if widget is not None else ""
        if widget is not None:
            widget.setText("")
        return text or fallback

    def _legacy_label_override(self, index: int) -> str:
        if index == 0:
            widget = getattr(self._owner, "_compare_left_label", None)
        elif index == 1:
            widget = getattr(self._owner, "_compare_right_label", None)
        else:
            widget = None
        if widget is None:
            return ""
        return widget.text().strip()

    def _normalize_label(self, index: int, label: str) -> str:
        return label.strip() or self._default_label(index)

    def _clear_latest_report(self) -> None:
        self._set_latest_compare_report(None)

    def _append_output(self, message: str) -> None:
        output = getattr(self._owner, "_compare_output", None)
        if output is not None:
            output.appendPlainText(message)

    def _current_selected_row(self) -> int:
        list_widget = getattr(self._owner, "_compare_scenarios_list", None)
        if list_widget is None:
            return -1
        return int(list_widget.currentRow())

    def _refresh_scenarios_view(self, *, selected_index: int | None = None) -> None:
        list_widget = getattr(self._owner, "_compare_scenarios_list", None)
        if list_widget is None:
            return
        scenarios = self._get_scenarios()
        current_row = self._current_selected_row() if selected_index is None else selected_index
        list_widget.clear()
        for index, scenario in enumerate(scenarios):
            role = "baseline" if index == 0 else "focus" if index == 1 else f"scenario {index + 1}"
            source = f" — {scenario.source}" if scenario.source else ""
            list_widget.addItem(f"{index + 1}. [{role}] {scenario.label}{source}")
        if not scenarios:
            return
        if current_row < 0:
            current_row = 0
        if current_row >= len(scenarios):
            current_row = len(scenarios) - 1
        list_widget.setCurrentRow(current_row)

    def get_scenario_metrics(self, index: int) -> dict[str, Any] | None:
        scenarios = self._get_scenarios()
        if 0 <= index < len(scenarios):
            return scenarios[index].metrics
        return None

    def set_scenario_metrics(
        self,
        index: int,
        value: dict[str, Any] | None,
        *,
        default_label: str | None = None,
        source: str = "legacy",
    ) -> None:
        scenarios = self._get_scenarios()
        if value is None:
            if 0 <= index < len(scenarios):
                del scenarios[index]
                self._clear_latest_report()
                self._refresh_scenarios_view(selected_index=index)
            return
        fallback_label = default_label or self._default_label(index)
        if index < len(scenarios):
            label_source = self._legacy_label_override(index) or (default_label or scenarios[index].label)
            label = self._normalize_label(index, label_source)
            scenarios[index] = CompareScenarioState(label=label, metrics=dict(value), source=source)
        elif index == len(scenarios):
            label = self._normalize_label(index, self._legacy_label_override(index) or fallback_label)
            scenarios.append(CompareScenarioState(label=label, metrics=dict(value), source=source))
        else:
            label = self._normalize_label(index, fallback_label)
            scenarios.append(CompareScenarioState(label=label, metrics=dict(value), source=source))
        self._clear_latest_report()
        self._refresh_scenarios_view(selected_index=min(index, len(scenarios) - 1))

    def _append_scenario(self, metrics: dict[str, Any], *, label: str, source: str) -> None:
        scenarios = self._get_scenarios()
        scenarios.append(
            CompareScenarioState(
                label=self._normalize_label(len(scenarios), label),
                metrics=dict(metrics),
                source=source,
            )
        )
        self._clear_latest_report()
        self._refresh_scenarios_view(selected_index=len(scenarios) - 1)

    def _load_metrics_from_picker(self, *, error_action: str) -> tuple[str, dict[str, Any]] | None:
        path = self._owner._pick_metrics_file()
        if not path:
            return None
        try:
            metrics = read_metrics_json(path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self._error_logger(error_action, exc, path=path)
            QMessageBox.critical(self._owner, "Compare load failed", str(exc))
            return None
        return path, metrics

    def _selected_scenario_index(self) -> int | None:
        scenarios = self._get_scenarios()
        row = self._current_selected_row()
        if 0 <= row < len(scenarios):
            return row
        return None

    def _build_report_scenarios(self) -> list[tuple[str, dict[str, Any]]]:
        normalized: list[tuple[str, dict[str, Any]]] = []
        scenarios = self._get_scenarios()
        label_changed = False
        for index, scenario in enumerate(scenarios):
            label = self._normalize_label(index, scenario.label)
            legacy_override = self._legacy_label_override(index)
            if legacy_override:
                label = legacy_override
            if label != scenario.label:
                scenario.label = label
                label_changed = True
            normalized.append((label, dict(scenario.metrics)))
        if label_changed:
            self._refresh_scenarios_view(selected_index=self._current_selected_row())
        return normalized

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

    def on_compare_add_metrics(self) -> None:
        loaded = self._load_metrics_from_picker(error_action="compare_add_metrics")
        if loaded is None:
            return
        path, metrics = loaded
        fallback_label = Path(path).stem or self._default_label(len(self._get_scenarios()))
        label = self._consume_pending_label(fallback_label)
        self._append_scenario(metrics, label=label, source=Path(path).name)
        self._append_output(f"[Compare] scenario added from metrics file: {label} ({path})")

    def on_compare_add_latest(self) -> None:
        if not self._owner._latest_metrics_report:
            QMessageBox.information(self._owner, "Compare", "No latest run metrics available.")
            return
        scenario_index = len(self._get_scenarios())
        fallback_label = self._default_label(scenario_index) if scenario_index < 2 else f"latest_{scenario_index + 1}"
        label = self._consume_pending_label(fallback_label)
        self._append_scenario(dict(self._owner._latest_metrics_report), label=label, source="latest run")
        self._append_output(f"[Compare] scenario added from latest run: {label}")

    def on_compare_remove_selected(self) -> None:
        selected_index = self._selected_scenario_index()
        if selected_index is None:
            QMessageBox.information(self._owner, "Compare", "Select a scenario first.")
            return
        scenarios = self._get_scenarios()
        removed = scenarios.pop(selected_index)
        self._clear_latest_report()
        self._refresh_scenarios_view(selected_index=selected_index)
        self._append_output(f"[Compare] scenario removed: {removed.label}")

    def _move_selected(self, *, delta: int) -> None:
        selected_index = self._selected_scenario_index()
        if selected_index is None:
            QMessageBox.information(self._owner, "Compare", "Select a scenario first.")
            return
        target_index = selected_index + delta
        scenarios = self._get_scenarios()
        if not (0 <= target_index < len(scenarios)):
            return
        scenarios[selected_index], scenarios[target_index] = scenarios[target_index], scenarios[selected_index]
        self._clear_latest_report()
        self._refresh_scenarios_view(selected_index=target_index)
        self._append_output(f"[Compare] scenario moved to position {target_index + 1}")

    def on_compare_move_selected_up(self) -> None:
        self._move_selected(delta=-1)

    def on_compare_move_selected_down(self) -> None:
        self._move_selected(delta=1)

    def on_compare_load_left(self) -> None:
        loaded = self._load_metrics_from_picker(error_action="compare_load_left")
        if loaded is None:
            return
        path, metrics = loaded
        self.set_scenario_metrics(0, metrics, default_label="baseline", source=Path(path).name)
        self._append_output(f"[Compare] baseline metrics loaded: {path}")

    def on_compare_load_right(self) -> None:
        loaded = self._load_metrics_from_picker(error_action="compare_load_right")
        if loaded is None:
            return
        path, metrics = loaded
        self.set_scenario_metrics(1, metrics, default_label="focus", source=Path(path).name)
        self._append_output(f"[Compare] focus metrics loaded: {path}")

    def on_compare_use_latest_left(self) -> None:
        if not self._owner._latest_metrics_report:
            QMessageBox.information(self._owner, "Compare", "No latest run metrics available.")
            return
        self.set_scenario_metrics(0, dict(self._owner._latest_metrics_report), default_label="baseline", source="latest run")
        self._append_output("[Compare] baseline metrics set from latest run")

    def on_compare_use_latest_right(self) -> None:
        if not self._owner._latest_metrics_report:
            QMessageBox.information(self._owner, "Compare", "No latest run metrics available.")
            return
        self.set_scenario_metrics(1, dict(self._owner._latest_metrics_report), default_label="focus", source="latest run")
        self._append_output("[Compare] focus metrics set from latest run")

    def on_compare_build(self) -> None:
        scenarios = self._build_report_scenarios()
        if len(scenarios) < 2:
            QMessageBox.information(
                self._owner,
                "Compare",
                "Please add at least two compare scenarios first.",
            )
            return
        report = build_multi_compare_report(scenarios)
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
