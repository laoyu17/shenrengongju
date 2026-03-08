"""PyQt6 UI app for simulation control and visualization."""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any

import yaml
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QBrush, QColor, QCloseEvent, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsLineItem,
    QMainWindow,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
)

from rtos_sim.core import SimEngine
from rtos_sim.io import ConfigError

from .config_doc import ConfigDocument
from .controllers import DagController
from .gantt_helpers import (
    SegmentBlockItem,
    SegmentVisualMeta,
    format_segment_details,
)
from .panel_state import (
    DagBatchOperationEntry,
    DagMultiSelectState,
    DagOverviewCanvasEntry,
)
from .window_bootstrap import (
    bootstrap_main_window,
    build_main_window_layout,
    connect_main_window_signals,
    register_form_change_signals,
)

_LOGGER = logging.getLogger(__name__)


def _log_ui_error(action: str, exc: Exception, **context: Any) -> None:
    """Emit structured UI error logs for diagnostics."""

    payload: dict[str, Any] = {
        "event": "ui_error",
        "action": action,
        "error_type": type(exc).__name__,
        "error_message": str(exc),
    }
    payload.update({key: value for key, value in context.items() if value is not None})
    _LOGGER.error(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str), exc_info=exc)


class DagNodeItem(QGraphicsEllipseItem):
    """Interactive DAG node supporting move and drag-to-connect."""

    def __init__(
        self,
        *,
        owner: "MainWindow",
        subtask_id: str,
        center: QPointF,
        radius: float,
        selected: bool,
    ) -> None:
        super().__init__(-radius, -radius, radius * 2, radius * 2)
        self._owner = owner
        self.subtask_id = subtask_id
        self._link_dragging = False
        self.setPos(center)
        self.setBrush(QBrush(QColor("#2d7ff9" if selected else "#47617a")))
        self.setPen(QPen(QColor("#f5f7fa")))
        self.setZValue(2)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def mousePressEvent(self, event: Any) -> None:  # noqa: ANN401
        modifiers = event.modifiers() if hasattr(event, "modifiers") else Qt.KeyboardModifier.NoModifier
        start_link = event.button() == Qt.MouseButton.RightButton or (
            event.button() == Qt.MouseButton.LeftButton
            and bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        )
        toggle_selection = not start_link and (
            bool(modifiers & Qt.KeyboardModifier.ControlModifier)
            or bool(modifiers & Qt.KeyboardModifier.MetaModifier)
        )
        self._owner._on_dag_node_clicked(
            self.subtask_id,
            toggle=toggle_selection,
            preserve_existing=not toggle_selection,
        )
        if start_link:
            self._owner._start_dag_link_drag(self.subtask_id, event.scenePos())
            self._link_dragging = True
            self.setCursor(Qt.CursorShape.CrossCursor)
            event.accept()
            return
        if toggle_selection:
            self._link_dragging = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        self._link_dragging = False
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: Any) -> None:  # noqa: ANN401
        if self._link_dragging:
            self._owner._update_dag_link_drag(event.scenePos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: ANN401
        if self._link_dragging:
            self._owner._finish_dag_link_drag(event.scenePos())
            self._link_dragging = False
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._owner._on_dag_node_drag_finished(self.subtask_id)

    def itemChange(self, change: QGraphicsItem.GraphicsItemChange, value: Any) -> Any:
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and isinstance(value, QPointF):
            self._owner._on_dag_node_moved(self.subtask_id, value)
        return super().itemChange(change, value)


class MainWindow(QMainWindow):
    """Main window with config editor, run controls and Gantt view."""

    _SUBTASK_BRUSH_STYLES = [
        Qt.BrushStyle.SolidPattern,
        Qt.BrushStyle.Dense4Pattern,
        Qt.BrushStyle.Dense6Pattern,
        Qt.BrushStyle.BDiagPattern,
        Qt.BrushStyle.DiagCrossPattern,
        Qt.BrushStyle.CrossPattern,
    ]
    _SEGMENT_PEN_STYLES = [
        Qt.PenStyle.SolidLine,
        Qt.PenStyle.DotLine,
        Qt.PenStyle.DashDotLine,
        Qt.PenStyle.DashDotDotLine,
    ]
    _TASK_TYPE_OPTIONS = {"dynamic_rt", "time_deterministic", "non_rt"}
    _RESOURCE_PROTOCOL_OPTIONS = {"mutex", "pip", "pcp"}
    _RIGHT_SPLITTER_LOWER_RATIO_COLLAPSED = 0.36
    _RIGHT_SPLITTER_LOWER_RATIO_EXPANDED = 0.42
    _RIGHT_SPLITTER_LOWER_MIN_COLLAPSED = 180
    _RIGHT_SPLITTER_LOWER_MIN_EXPANDED = 260

    def __init__(self, config_path: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("RTOS Sim UI (PyQt6)")
        self.resize(1500, 920)
        bootstrap_main_window(self, _log_ui_error)

        if config_path:
            self._load_file(config_path)
        else:
            self._sync_form_to_text(show_message=False)

    @property
    def _compare_left_metrics(self) -> dict[str, Any] | None:
        return self._compare_controller.get_scenario_metrics(0)

    @_compare_left_metrics.setter
    def _compare_left_metrics(self, value: dict[str, Any] | None) -> None:
        self._compare_controller.set_scenario_metrics(0, value, default_label="baseline")

    @property
    def _compare_right_metrics(self) -> dict[str, Any] | None:
        return self._compare_controller.get_scenario_metrics(1)

    @_compare_right_metrics.setter
    def _compare_right_metrics(self, value: dict[str, Any] | None) -> None:
        self._compare_controller.set_scenario_metrics(1, value, default_label="focus")

    @property
    def _latest_compare_report(self) -> dict[str, Any] | None:
        return self._compare_panel_state.latest_report

    @_latest_compare_report.setter
    def _latest_compare_report(self, value: dict[str, Any] | None) -> None:
        self._compare_panel_state.latest_report = value

    @property
    def _state_transitions(self) -> list[str]:
        return self._telemetry_panel_state.state_transitions

    @_state_transitions.setter
    def _state_transitions(self, value: list[str]) -> None:
        self._telemetry_panel_state.state_transitions = list(value)

    @property
    def _hovered_segment_key(self) -> str | None:
        return self._telemetry_panel_state.hovered_segment_key

    @_hovered_segment_key.setter
    def _hovered_segment_key(self, value: str | None) -> None:
        self._telemetry_panel_state.hovered_segment_key = value

    @property
    def _locked_segment_key(self) -> str | None:
        return self._telemetry_panel_state.locked_segment_key

    @_locked_segment_key.setter
    def _locked_segment_key(self, value: str | None) -> None:
        self._telemetry_panel_state.locked_segment_key = value

    @property
    def _dag_node_centers(self) -> dict[str, QPointF]:
        return self._dag_workbench_state.node_centers

    @_dag_node_centers.setter
    def _dag_node_centers(self, value: dict[str, QPointF]) -> None:
        self._dag_workbench_state.node_centers = dict(value)

    @property
    def _dag_node_items(self) -> dict[str, DagNodeItem]:
        return self._dag_workbench_state.node_items

    @_dag_node_items.setter
    def _dag_node_items(self, value: dict[str, DagNodeItem]) -> None:
        self._dag_workbench_state.node_items = dict(value)

    @property
    def _dag_edge_items(self) -> dict[tuple[str, str], QGraphicsLineItem]:
        return self._dag_workbench_state.edge_items

    @_dag_edge_items.setter
    def _dag_edge_items(self, value: dict[tuple[str, str], QGraphicsLineItem]) -> None:
        self._dag_workbench_state.edge_items = dict(value)

    @property
    def _dag_manual_positions_by_task(self) -> dict[str, dict[str, QPointF]]:
        return self._dag_workbench_state.manual_positions_by_task

    @_dag_manual_positions_by_task.setter
    def _dag_manual_positions_by_task(self, value: dict[str, dict[str, QPointF]]) -> None:
        self._dag_workbench_state.manual_positions_by_task = {
            key: dict(positions) for key, positions in value.items()
        }

    @property
    def _dag_drag_source_id(self) -> str | None:
        return self._dag_workbench_state.drag_source_id

    @_dag_drag_source_id.setter
    def _dag_drag_source_id(self, value: str | None) -> None:
        self._dag_workbench_state.drag_source_id = value

    @property
    def _dag_drag_line(self) -> QGraphicsLineItem | None:
        return self._dag_workbench_state.drag_line

    @_dag_drag_line.setter
    def _dag_drag_line(self, value: QGraphicsLineItem | None) -> None:
        self._dag_workbench_state.drag_line = value

    @property
    def _dag_multi_select_state(self) -> DagMultiSelectState:
        return self._dag_workbench_state.multi_selection

    @property
    def _dag_last_batch_operation(self) -> DagBatchOperationEntry | None:
        return self._dag_workbench_state.last_batch_operation

    @_dag_last_batch_operation.setter
    def _dag_last_batch_operation(self, value: DagBatchOperationEntry | None) -> None:
        self._dag_workbench_state.last_batch_operation = value

    @property
    def _dag_overview_canvas_entry(self) -> DagOverviewCanvasEntry | None:
        return self._dag_workbench_state.overview_canvas_entry

    @_dag_overview_canvas_entry.setter
    def _dag_overview_canvas_entry(self, value: DagOverviewCanvasEntry | None) -> None:
        self._dag_workbench_state.overview_canvas_entry = value

    @property
    def _dag_canvas_mode(self) -> str:
        return self._dag_workbench_state.canvas_mode

    @_dag_canvas_mode.setter
    def _dag_canvas_mode(self, value: str) -> None:
        self._dag_workbench_state.canvas_mode = value

    def _build_layout(self) -> None:
        build_main_window_layout(self)

    def _connect_signals(self) -> None:
        connect_main_window_signals(self)

    def _register_form_change_signals(self) -> None:
        register_form_change_signals(self)

    def _on_text_edited(self) -> None:
        if self._suspend_text_events:
            return
        self._config_doc = None
        self._dag_manual_positions_by_task.clear()
        self._invalidate_planning_cache()
        if self._editor_tabs.currentIndex() == 1:
            self._form_hint.setText("Text changed. Use 'Sync Text -> Form' to refresh form.")

    def _invalidate_planning_cache(self) -> None:
        self._latest_plan_result = None
        self._latest_plan_payload = None
        self._latest_plan_spec_fingerprint = None
        self._latest_plan_semantic_fingerprint = None
        self._latest_planning_wcrt_report = None
        self._latest_planning_os_payload = None

    def _mark_form_dirty(self, *args: Any) -> None:  # noqa: ARG002
        if self._suspend_form_events:
            return
        self._form_dirty = True
        self._form_hint.setText("Form changed. Use 'Apply Form -> Text' before run/save.")

    def _on_sync_text_to_form(self) -> None:
        self._form_controller.on_sync_text_to_form()

    def _on_sync_form_to_text(self) -> None:
        self._form_controller.on_sync_form_to_text()

    def _sync_form_to_text_if_dirty(self) -> bool:
        return self._form_controller.sync_form_to_text_if_dirty()

    def _sync_text_to_form(self, *, show_message: bool) -> bool:
        return self._form_controller.sync_text_to_form(show_message=show_message)

    def _sync_form_to_text(self, *, show_message: bool) -> bool:
        return self._form_controller.sync_form_to_text(show_message=show_message)

    def _read_editor_payload(self) -> dict[str, Any]:
        return self._document_sync_controller.read_editor_payload()

    def _populate_form_from_payload(self, payload: dict[str, Any]) -> None:
        self._document_sync_controller.populate_form_from_payload(payload)

    def _populate_form_from_doc(self) -> None:
        self._document_sync_controller.populate_form_from_doc()

    def _ensure_config_doc(self) -> ConfigDocument:
        if self._config_doc is not None:
            return self._config_doc
        try:
            payload = self._read_editor_payload()
        except (ConfigError, ValueError, TypeError, yaml.YAMLError) as exc:
            _log_ui_error("ensure_config_doc_fallback", exc)
            payload = {}
        self._config_doc = ConfigDocument.from_payload(payload)
        return self._config_doc

    def _refresh_task_table(self, doc: ConfigDocument) -> None:
        self._table_editor_controller.refresh_task_table(doc)

    def _refresh_resource_table(self, doc: ConfigDocument) -> None:
        self._table_editor_controller.refresh_resource_table(doc)

    def _refresh_selected_resource_fields(self, doc: ConfigDocument) -> None:
        self._table_editor_controller.refresh_selected_resource_fields(doc)

    def _refresh_selected_task_fields(self, doc: ConfigDocument) -> None:
        self._table_editor_controller.refresh_selected_task_fields(doc)

    def _refresh_dag_widgets(self, doc: ConfigDocument) -> None:
        self._dag_controller.refresh_dag_widgets(doc)

    def _current_task_layout_key(self, doc: ConfigDocument) -> str:
        tasks = doc.list_tasks()
        if not tasks or self._selected_task_index < 0:
            return ""
        self._selected_task_index = min(self._selected_task_index, len(tasks) - 1)
        task = doc.get_task(self._selected_task_index)
        task_id = str(task.get("id") or "").strip()
        if task_id:
            return task_id
        return f"task_{self._selected_task_index}"

    def _resolve_dag_positions(
        self,
        doc: ConfigDocument,
        layout_key: str,
        subtask_ids: list[str],
        edges: list[tuple[str, str]],
    ) -> dict[str, QPointF]:
        return self._dag_controller.resolve_dag_positions(doc, layout_key, subtask_ids, edges)

    @staticmethod
    def _compute_auto_layout_positions(
        subtask_ids: list[str],
        edges: list[tuple[str, str]],
    ) -> dict[str, QPointF]:
        return DagController.compute_auto_layout_positions(subtask_ids, edges)

    def _render_dag_scene(
        self,
        subtask_ids: list[str],
        edges: list[tuple[str, str]],
        *,
        positions: dict[str, QPointF],
    ) -> None:
        self._dag_controller.render_dag_scene(subtask_ids, edges, positions=positions)

    def _start_dag_link_drag(self, src_id: str, scene_pos: QPointF) -> None:
        self._dag_controller.start_dag_link_drag(src_id, scene_pos)

    def _update_dag_link_drag(self, scene_pos: QPointF) -> None:
        self._dag_controller.update_dag_link_drag(scene_pos)

    def _finish_dag_link_drag(self, scene_pos: QPointF) -> None:
        self._dag_controller.finish_dag_link_drag(scene_pos)

    def _clear_dag_drag_preview(self) -> None:
        self._dag_controller.clear_dag_drag_preview()

    def _dag_node_id_from_scene_pos(self, scene_pos: QPointF) -> str | None:
        return self._dag_controller.dag_node_id_from_scene_pos(scene_pos)

    def _dag_scene_pos_for_subtask(self, subtask_id: str) -> QPointF | None:
        return self._dag_controller.dag_scene_pos_for_subtask(subtask_id)

    def _on_dag_node_clicked(
        self,
        subtask_id: str,
        *,
        toggle: bool = False,
        preserve_existing: bool = False,
    ) -> None:
        self._dag_controller.on_dag_node_clicked(
            subtask_id,
            toggle=toggle,
            preserve_existing=preserve_existing,
        )

    def _refresh_dag_node_selection_visuals(self) -> None:
        self._dag_controller.refresh_dag_node_selection_visuals()

    def _on_dag_node_moved(self, subtask_id: str, center: QPointF) -> None:
        self._dag_controller.on_dag_node_moved(subtask_id, center)

    def _on_dag_node_drag_finished(self, subtask_id: str) -> None:
        self._dag_controller.on_dag_node_drag_finished(subtask_id)

    def _update_dag_edges_for_node(self, subtask_id: str) -> None:
        self._dag_controller.update_dag_edges_for_node(subtask_id)

    def _persist_current_dag_layout_to_doc(self) -> None:
        self._dag_controller.persist_current_dag_layout_to_doc()

    def _refresh_dag_overview_canvas(self, entry: DagOverviewCanvasEntry | None) -> None:
        self._dag_overview_controller.refresh_overview_canvas(entry)

    def _on_dag_canvas_tab_changed(self, index: int) -> None:
        self._dag_overview_controller.on_canvas_tab_changed(index)

    def _open_dag_overview_canvas(self) -> None:
        self._dag_overview_controller.show_overview_canvas()

    def _open_dag_overview_task_detail(self, task_ref: int | str) -> bool:
        return self._dag_overview_controller.open_task_detail(task_ref)

    def _on_dag_auto_layout(self) -> None:
        self._dag_controller.on_dag_auto_layout()

    def _on_dag_persist_layout_toggled(self, checked: bool) -> None:
        self._dag_controller.on_dag_persist_layout_toggled(checked)

    def _try_add_dag_edge(self, src_id: str, dst_id: str, *, show_feedback: bool) -> bool:
        return self._dag_controller.try_add_dag_edge(src_id, dst_id, show_feedback=show_feedback)

    @staticmethod
    def _would_create_cycle(doc: ConfigDocument, task_index: int, src_id: str, dst_id: str) -> bool:
        return DagController.would_create_cycle(doc, task_index, src_id, dst_id)

    def _apply_form_to_payload(self, base_payload: dict[str, Any]) -> dict[str, Any]:
        return self._document_sync_controller.apply_form_to_payload(base_payload)

    def _apply_form_to_document(self, doc: ConfigDocument) -> None:
        self._document_sync_controller.apply_form_to_document(doc)

    @staticmethod
    def _set_table_item(table: QTableWidget, row: int, col: int, text: str) -> None:
        table.setItem(row, col, QTableWidgetItem(text))

    @staticmethod
    def _table_cell_text(table: QTableWidget, row: int, col: int) -> str:
        item = table.item(row, col)
        return item.text().strip() if item is not None else ""

    def _clear_table_error_bucket(self, table_key: str) -> None:
        self._table_editor_controller._clear_table_error_bucket(table_key)

    def _set_table_cell_error(
        self,
        *,
        table_key: str,
        table: QTableWidget,
        row: int,
        col: int,
        error: str | None,
    ) -> None:
        self._table_editor_controller._set_table_cell_error(
            table_key=table_key,
            table=table,
            row=row,
            col=col,
            error=error,
        )

    def _validate_task_table(self) -> None:
        self._table_editor_controller.validate_task_table()

    def _validate_resource_table(self) -> None:
        self._table_editor_controller.validate_resource_table()

    def _has_table_validation_errors(self) -> bool:
        return self._table_editor_controller.has_table_validation_errors()

    def _first_table_validation_error(self) -> str:
        return self._table_editor_controller.first_table_validation_error()

    def _patch_task_row_from_table(self, doc: ConfigDocument, row: int) -> None:
        self._table_editor_controller._patch_task_row_from_table(doc, row)

    def _patch_resource_row_from_table(self, doc: ConfigDocument, row: int) -> None:
        self._table_editor_controller._patch_resource_row_from_table(doc, row)

    def _on_add_task(self) -> None:
        self._table_editor_controller.on_add_task()

    def _on_remove_task(self) -> None:
        self._table_editor_controller.on_remove_task()

    def _on_add_resource(self) -> None:
        self._table_editor_controller.on_add_resource()

    def _on_remove_resource(self) -> None:
        self._table_editor_controller.on_remove_resource()

    def _on_task_selection_changed(self) -> None:
        self._table_editor_controller.on_task_selection_changed()

    def _on_resource_selection_changed(self) -> None:
        self._table_editor_controller.on_resource_selection_changed()

    def _on_task_table_cell_changed(self, row: int, col: int) -> None:
        self._table_editor_controller.on_task_table_cell_changed(row, col)

    def _on_resource_table_cell_changed(self, row: int, col: int) -> None:
        self._table_editor_controller.on_resource_table_cell_changed(row, col)

    def _on_dag_subtask_selected(self) -> None:
        self._dag_controller.on_dag_subtask_selected()

    def _on_dag_add_subtask(self) -> None:
        self._dag_controller.on_dag_add_subtask()

    def _on_dag_remove_subtask(self) -> None:
        self._dag_controller.on_dag_remove_subtask()

    def _on_dag_add_edge(self) -> None:
        self._dag_controller.on_dag_add_edge()

    def _on_dag_remove_edge(self) -> None:
        self._dag_controller.on_dag_remove_edge()

    def _get_dag_multi_select_state(self) -> DagMultiSelectState:
        return self._dag_controller.get_multi_select_state()

    def _open_dag_batch_operation(
        self,
        action_id: str,
        *,
        selected_subtask_ids: list[str] | tuple[str, ...] | None = None,
    ) -> DagBatchOperationEntry | None:
        return self._dag_controller.open_batch_operation(
            action_id,
            selected_subtask_ids=selected_subtask_ids,
        )

    def _get_dag_overview_canvas_entry(self) -> DagOverviewCanvasEntry | None:
        return self._dag_controller.get_overview_canvas_entry()

    @staticmethod
    def _parse_optional_float(raw: str, field_name: str) -> float | None:
        text = raw.strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError as exc:  # pragma: no cover - UI guard
            raise ConfigError(f"{field_name} must be number") from exc

    @staticmethod
    def _stringify_optional_number(value: Any) -> str:
        if value is None:
            return ""
        try:
            return str(float(value)).rstrip("0").rstrip(".")
        except (TypeError, ValueError):
            return ""

    @staticmethod
    def _to_bool(value: Any, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return default

    @staticmethod
    def _set_combo_value(widget: QComboBox, value: str) -> None:
        idx = widget.findText(value)
        if idx >= 0:
            widget.setCurrentIndex(idx)

    def _pick_load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open config",
            str(Path.cwd()),
            "Config Files (*.yaml *.yml *.json)",
        )
        if path:
            self._load_file(path)

    def _load_file(self, path: str) -> None:
        try:
            content = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Load failed", str(exc))
            self._status_label.setText("Load failed")
            return
        self._suspend_text_events = True
        try:
            self._editor.setPlainText(content)
        finally:
            self._suspend_text_events = False
        self._config_doc = None
        self._invalidate_planning_cache()
        if self._sync_text_to_form(show_message=False):
            self._status_label.setText(f"Loaded: {path}")
            return
        self._status_label.setText(f"Loaded text only: {path}")

    def _pick_save_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save config",
            str(Path.cwd() / "config.yaml"),
            "Config Files (*.yaml *.yml *.json)",
        )
        if not path:
            return
        if not self._sync_form_to_text_if_dirty():
            return
        payload = self._read_editor_payload()
        if Path(path).suffix.lower() == ".json":
            content = json.dumps(payload, ensure_ascii=False, indent=2)
        else:
            content = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
        try:
            Path(path).write_text(content, encoding="utf-8")
        except OSError as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            self._status_label.setText("Save failed")
            return
        self._status_label.setText(f"Saved: {path}")

    def _pick_metrics_file(self) -> str | None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open metrics json",
            str(Path.cwd()),
            "JSON Files (*.json)",
        )
        return path or None

    def _on_compare_toggle(self, checked: bool) -> None:
        self._compare_controller.on_compare_toggle(checked)

    def _on_compare_add_metrics(self) -> None:
        self._compare_controller.on_compare_add_metrics()

    def _on_compare_add_latest(self) -> None:
        self._compare_controller.on_compare_add_latest()

    def _on_compare_remove_selected(self) -> None:
        self._compare_controller.on_compare_remove_selected()

    def _on_compare_move_up(self) -> None:
        self._compare_controller.on_compare_move_selected_up()

    def _on_compare_move_down(self) -> None:
        self._compare_controller.on_compare_move_selected_down()

    def _rebalance_right_splitter(self, *, compare_open: bool) -> None:
        self._compare_controller.rebalance_right_splitter(compare_open=compare_open)

    def _ensure_compare_visible(self) -> None:
        self._compare_controller.ensure_compare_visible()

    def _on_compare_load_left(self) -> None:
        self._compare_controller.on_compare_load_left()

    def _on_compare_load_right(self) -> None:
        self._compare_controller.on_compare_load_right()

    def _on_compare_use_latest_left(self) -> None:
        self._compare_controller.on_compare_use_latest_left()

    def _on_compare_use_latest_right(self) -> None:
        self._compare_controller.on_compare_use_latest_right()

    def _on_compare_build(self) -> None:
        self._compare_controller.on_compare_build()

    def _on_compare_export_json(self) -> None:
        self._compare_controller.on_compare_export_json()

    def _on_compare_export_csv(self) -> None:
        self._compare_controller.on_compare_export_csv()

    def _on_compare_export_markdown(self) -> None:
        self._compare_controller.on_compare_export_markdown()

    def _on_plan_static(self) -> None:
        self._planning_controller.on_plan_static()

    def _on_plan_analyze_wcrt(self) -> None:
        self._planning_controller.on_plan_analyze_wcrt()

    def _on_plan_export_os_config(self) -> None:
        self._planning_controller.on_plan_export_os_config()

    def _on_plan_generate_random_tasks(self) -> None:
        self._planning_controller.on_generate_random_tasks()

    def _append_state_transition(self, *, event_time: float, state: str, label: str) -> None:
        self._telemetry_controller.append_state_transition(event_time=event_time, state=state, label=label)

    def _set_worker_controls(self, *, running: bool, paused: bool) -> None:
        self._run_controller.set_worker_controls(running=running, paused=paused)

    def _step_delta_value(self) -> float | None:
        return self._run_controller.step_delta_value()

    def _on_validate(self) -> None:
        if not self._sync_form_to_text_if_dirty():
            return
        try:
            payload = self._read_editor_payload()
            spec = self._loader.load_data(payload)
            SimEngine().build(spec)
        except (ConfigError, ValueError, TypeError, yaml.YAMLError) as exc:
            _log_ui_error("validate", exc)
            QMessageBox.critical(self, "Validation failed", str(exc))
            self._status_label.setText("Validation failed")
            return
        self._status_label.setText("Validation passed")
        QMessageBox.information(self, "Validation", "Config validation passed.")

    def _on_run(self) -> None:
        self._run_controller.on_run()

    def _on_stop(self) -> None:
        self._run_controller.on_stop()

    def _on_pause(self) -> None:
        self._run_controller.on_pause()

    def _on_resume(self) -> None:
        self._run_controller.on_resume()

    def _on_step(self) -> None:
        self._run_controller.on_step()

    def _on_reset(self) -> None:
        self._run_controller.on_reset()

    def _on_research_export(self) -> None:
        self._research_report_controller.on_research_export()

    def _on_event_batch(self, events: list[dict[str, Any]]) -> None:
        self._timeline_controller.on_event_batch(events)

    def _consume_event(self, event: dict[str, Any]) -> None:
        self._timeline_controller.consume_event(event)

    def _close_segment(self, segment_key: str, end_event: dict[str, Any], interrupted: bool) -> None:
        self._timeline_controller.close_segment(segment_key, end_event, interrupted)

    def _draw_gantt_segment(self, meta: SegmentVisualMeta) -> None:
        self._timeline_controller.draw_gantt_segment(meta)

    def _draw_preempt_marker(self, event_time: float, core_id: str) -> None:
        self._timeline_controller.draw_preempt_marker(event_time, core_id)

    def _core_lane(self, core_id: str) -> int:
        if core_id not in self._core_to_y:
            self._core_to_y[core_id] = len(self._core_to_y) + 1
            ticks = [(y, core) for core, y in sorted(self._core_to_y.items(), key=lambda item: item[1])]
            self._plot.getAxis("left").setTicks([ticks])
        return self._core_to_y[core_id]

    def _task_color(self, task_id: str) -> QColor:
        return self._gantt_style_controller.task_color(task_id)

    def _subtask_brush_style(self, task_id: str, subtask_id: str) -> Qt.BrushStyle:
        return self._gantt_style_controller.subtask_brush_style(task_id, subtask_id)

    def _segment_pen_style(self, segment_id: str, interrupted: bool) -> Qt.PenStyle:
        return self._gantt_style_controller.segment_pen_style(segment_id, interrupted)

    def _ensure_task_legend(self, task_id: str, color: QColor) -> None:
        self._gantt_style_controller.ensure_task_legend(task_id, color)

    def _on_plot_mouse_moved(self, scene_pos: QPointF) -> None:
        self._telemetry_controller.on_plot_mouse_moved(scene_pos)

    def _on_plot_mouse_clicked(self, event: Any) -> None:
        self._telemetry_controller.on_plot_mouse_clicked(event)

    def _segment_item_from_scene(self, scene_pos: QPointF) -> SegmentBlockItem | None:
        return self._telemetry_controller.segment_item_from_scene(scene_pos)

    def _refresh_legend_details(self) -> None:
        self._telemetry_controller.refresh_legend_details()

    def _format_segment_details(self, meta: SegmentVisualMeta) -> str:
        return format_segment_details(meta)

    def _on_finished(self, report: dict[str, Any], all_events: list[dict[str, Any]]) -> None:
        self._run_controller.on_finished(report, all_events)

    def _on_failed(self, error_message: str) -> None:
        self._run_controller.on_failed(error_message)

    def _reset_viz(self) -> None:
        self._plot.clear()
        plot_item = self._plot.getPlotItem()
        if plot_item.legend is not None:
            plot_item.legend.scene().removeItem(plot_item.legend)
            plot_item.legend = None
        self._plot.addLegend(offset=(10, 10))

        self._core_to_y.clear()
        self._active_segments.clear()
        self._segment_resources.clear()
        self._job_deadlines.clear()

        self._legend_tasks.clear()
        self._legend_samples.clear()
        self._subtask_legend_map.clear()
        self._segment_legend_map.clear()
        self._subtask_style_cache.clear()
        self._segment_style_cache.clear()

        self._segment_items.clear()
        self._segment_labels.clear()
        self._seen_event_ids.clear()

        self._max_time = 0.0
        self._telemetry_controller.reset_panel_state()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self._run_controller.teardown_worker(wait_ms=2000):
            self._status_label.setText("Stopping...")
            event.ignore()
            return
        super().closeEvent(event)


def run_ui(config_path: str | None = None) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(config_path=config_path)
    window.show()
    app.exec()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rtos-sim-ui")
    parser.add_argument("-c", "--config", default=None, help="initial config path")
    args = parser.parse_args(argv)
    run_ui(args.config)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
