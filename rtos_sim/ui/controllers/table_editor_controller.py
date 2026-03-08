"""Controller for task/resource table editing and validation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QTableWidget, QTableWidgetItem

from rtos_sim.ui.config_doc import ConfigDocument
from rtos_sim.ui.gantt_helpers import safe_float, safe_optional_float
from rtos_sim.ui.table_validation import build_resource_table_errors, build_task_table_errors

if TYPE_CHECKING:
    from rtos_sim.ui.app import MainWindow


class TableEditorController:
    """Encapsulate table refresh, validation, and patch-back behavior."""

    def __init__(self, owner: MainWindow) -> None:
        self._owner = owner

    @staticmethod
    def _set_table_item(table: QTableWidget, row: int, col: int, text: str) -> None:
        item = QTableWidgetItem(text)
        table.setItem(row, col, item)

    @staticmethod
    def _table_cell_text(table: QTableWidget, row: int, col: int) -> str:
        item = table.item(row, col)
        return item.text().strip() if item is not None else ""

    def refresh_task_table(self, doc: ConfigDocument) -> None:
        tasks = doc.list_tasks()
        table = self._owner._task_table
        table.blockSignals(True)
        try:
            table.setRowCount(len(tasks))
            for view in tasks:
                task = view.task
                row = view.index
                self._set_table_item(table, row, 0, str(task.get("id", "")))
                self._set_table_item(table, row, 1, str(task.get("name", "")))
                self._set_table_item(table, row, 2, str(task.get("task_type", "")))
                self._set_table_item(
                    table,
                    row,
                    3,
                    self._owner._stringify_optional_number(task.get("arrival")),
                )
                self._set_table_item(
                    table,
                    row,
                    4,
                    self._owner._stringify_optional_number(task.get("deadline")),
                )
            if 0 <= self._owner._selected_task_index < len(tasks):
                table.selectRow(self._owner._selected_task_index)
            else:
                table.clearSelection()
        finally:
            table.blockSignals(False)
        self._owner._task_remove_button.setEnabled(len(tasks) > 0)
        self.validate_task_table()

    def refresh_resource_table(self, doc: ConfigDocument) -> None:
        resources = doc.list_resources()
        table = self._owner._resource_table
        table.blockSignals(True)
        try:
            table.setRowCount(len(resources))
            for view in resources:
                resource = view.resource
                row = view.index
                self._set_table_item(table, row, 0, str(resource.get("id", "")))
                self._set_table_item(table, row, 1, str(resource.get("name", "")))
                self._set_table_item(table, row, 2, str(resource.get("bound_core_id", "")))
                self._set_table_item(table, row, 3, str(resource.get("protocol", "")))
            if 0 <= self._owner._selected_resource_index < len(resources):
                table.selectRow(self._owner._selected_resource_index)
            else:
                table.clearSelection()
        finally:
            table.blockSignals(False)
        self._owner._resource_remove_button.setEnabled(len(resources) > 0)
        self.validate_resource_table()

    def refresh_selected_resource_fields(self, doc: ConfigDocument) -> None:
        resources = doc.list_resources()
        selected: dict[str, Any] = {}
        if resources:
            if self._owner._selected_resource_index < 0:
                self._owner._selected_resource_index = 0
            self._owner._selected_resource_index = min(
                self._owner._selected_resource_index,
                len(resources) - 1,
            )
            selected = doc.get_resource(self._owner._selected_resource_index)

        self._owner._form_resource_enabled.setChecked(bool(resources))
        self._owner._form_resource_id.setText(str(selected.get("id", "r0")))
        self._owner._form_resource_name.setText(str(selected.get("name", "lock")))
        self._owner._form_resource_bound_core.setText(
            str(selected.get("bound_core_id", self._owner._form_core_id.text()))
        )
        self._owner._set_combo_value(
            self._owner._form_resource_protocol,
            str(selected.get("protocol", "mutex")),
        )

    def refresh_selected_task_fields(self, doc: ConfigDocument) -> None:
        tasks = doc.list_tasks()
        if tasks:
            if self._owner._selected_task_index < 0:
                self._owner._selected_task_index = 0
            self._owner._selected_task_index = min(self._owner._selected_task_index, len(tasks) - 1)
            task = doc.get_task(self._owner._selected_task_index)
        else:
            task = {}

        self._owner._form_task_id.setText(str(task.get("id", "t0")))
        self._owner._form_task_name.setText(str(task.get("name", "task")))
        self._owner._set_combo_value(self._owner._form_task_type, str(task.get("task_type", "dynamic_rt")))
        self._owner._form_task_arrival.setValue(safe_float(task.get("arrival"), 0.0))
        self._owner._form_task_period.setText(self._owner._stringify_optional_number(task.get("period")))
        self._owner._form_task_deadline.setText(self._owner._stringify_optional_number(task.get("deadline")))
        self._owner._form_task_abort_on_miss.setChecked(bool(task.get("abort_on_miss", False)))

        subtask: dict[str, Any] = {}
        segment: dict[str, Any] = {}
        if tasks and self._owner._selected_task_index >= 0:
            subtasks = doc.list_subtasks(self._owner._selected_task_index)
            if subtasks:
                by_id = {
                    str(item.get("id") or ""): (idx, item)
                    for idx, item in enumerate(subtasks)
                    if isinstance(item, dict)
                }
                lookup = by_id.get(self._owner._selected_subtask_id)
                if lookup is None:
                    idx = 0
                    subtask = subtasks[idx]
                    self._owner._selected_subtask_id = str(subtask.get("id") or "s0")
                else:
                    idx, subtask = lookup
                segment = doc.get_segment(self._owner._selected_task_index, idx, 0)
            else:
                self._owner._selected_subtask_id = "s0"
        else:
            self._owner._selected_subtask_id = "s0"

        self._owner._form_subtask_id.setText(str(subtask.get("id", "s0")))
        self._owner._form_segment_id.setText(str(segment.get("id", "seg0")))
        self._owner._form_segment_wcet.setValue(safe_float(segment.get("wcet"), 1.0))
        mapping_hint = segment.get("mapping_hint")
        self._owner._form_segment_mapping_hint.setText("" if mapping_hint is None else str(mapping_hint))
        required_resources = segment.get("required_resources")
        if isinstance(required_resources, list):
            self._owner._form_segment_required_resources.setText(",".join(str(item) for item in required_resources))
        else:
            self._owner._form_segment_required_resources.setText("")
        self._owner._form_segment_preemptible.setChecked(bool(segment.get("preemptible", True)))

    def _clear_table_error_bucket(self, table_key: str) -> None:
        for key in list(self._owner._table_validation_errors):
            if key[0] == table_key:
                self._owner._table_validation_errors.pop(key, None)

    def _set_table_cell_error(
        self,
        *,
        table_key: str,
        table: QTableWidget,
        row: int,
        col: int,
        error: str | None,
    ) -> None:
        if table.item(row, col) is None:
            table.setItem(row, col, QTableWidgetItem(""))
        index = table.model().index(row, col)
        if not index.isValid():
            return

        key = (table_key, row, col)
        if error:
            self._owner._table_validation_errors[key] = error
            table.model().setData(index, QColor("#6f2f2f"), Qt.ItemDataRole.BackgroundRole)
            table.model().setData(index, QColor("#ffecec"), Qt.ItemDataRole.ForegroundRole)
            table.model().setData(index, error, Qt.ItemDataRole.ToolTipRole)
        else:
            self._owner._table_validation_errors.pop(key, None)
            table.model().setData(index, None, Qt.ItemDataRole.BackgroundRole)
            table.model().setData(index, None, Qt.ItemDataRole.ForegroundRole)
            table.model().setData(index, "", Qt.ItemDataRole.ToolTipRole)

    def validate_task_table(self) -> None:
        table = self._owner._task_table
        row_count = table.rowCount()
        rows = [
            {
                "id": self._table_cell_text(table, row, 0),
                "name": self._table_cell_text(table, row, 1),
                "task_type": self._table_cell_text(table, row, 2),
                "arrival": self._table_cell_text(table, row, 3),
                "deadline": self._table_cell_text(table, row, 4),
            }
            for row in range(row_count)
        ]
        errors = build_task_table_errors(rows=rows, valid_task_types=self._owner._TASK_TYPE_OPTIONS)

        self._clear_table_error_bucket("task")
        table.blockSignals(True)
        try:
            for row in range(row_count):
                for col in range(5):
                    self._set_table_cell_error(
                        table_key="task",
                        table=table,
                        row=row,
                        col=col,
                        error=errors.get((row, col)),
                    )
        finally:
            table.blockSignals(False)

    def validate_resource_table(self) -> None:
        table = self._owner._resource_table
        row_count = table.rowCount()
        rows = [
            {
                "id": self._table_cell_text(table, row, 0),
                "name": self._table_cell_text(table, row, 1),
                "bound_core_id": self._table_cell_text(table, row, 2),
                "protocol": self._table_cell_text(table, row, 3),
            }
            for row in range(row_count)
        ]
        errors = build_resource_table_errors(rows=rows, valid_protocols=self._owner._RESOURCE_PROTOCOL_OPTIONS)

        self._clear_table_error_bucket("resource")
        table.blockSignals(True)
        try:
            for row in range(row_count):
                for col in range(4):
                    self._set_table_cell_error(
                        table_key="resource",
                        table=table,
                        row=row,
                        col=col,
                        error=errors.get((row, col)),
                    )
        finally:
            table.blockSignals(False)

    def has_table_validation_errors(self) -> bool:
        return bool(self._owner._table_validation_errors)

    def first_table_validation_error(self) -> str:
        if not self._owner._table_validation_errors:
            return ""
        key = sorted(self._owner._table_validation_errors.keys())[0]
        table_name = "task_table" if key[0] == "task" else "resource_table"
        row = key[1] + 1
        col = key[2] + 1
        return f"{table_name} row={row} col={col}: {self._owner._table_validation_errors[key]}"

    def _patch_task_row_from_table(self, doc: ConfigDocument, row: int) -> None:
        task_type = self._table_cell_text(self._owner._task_table, row, 2) or "dynamic_rt"
        deadline_text = self._table_cell_text(self._owner._task_table, row, 4)
        deadline = safe_optional_float(deadline_text) if deadline_text else None
        doc.patch_task(
            row,
            {
                "id": self._table_cell_text(self._owner._task_table, row, 0) or f"t{row}",
                "name": self._table_cell_text(self._owner._task_table, row, 1) or "task",
                "task_type": task_type,
                "arrival": float(
                    safe_optional_float(self._table_cell_text(self._owner._task_table, row, 3)) or 0.0
                ),
                "deadline": deadline,
            },
        )

    def _patch_resource_row_from_table(self, doc: ConfigDocument, row: int) -> None:
        doc.patch_resource(
            row,
            {
                "id": self._table_cell_text(self._owner._resource_table, row, 0) or f"r{row}",
                "name": self._table_cell_text(self._owner._resource_table, row, 1) or "lock",
                "bound_core_id": self._table_cell_text(self._owner._resource_table, row, 2) or "c0",
                "protocol": self._table_cell_text(self._owner._resource_table, row, 3) or "mutex",
            },
        )

    def on_add_task(self) -> None:
        doc = self._owner._ensure_config_doc()
        self._owner._selected_task_index = doc.add_task()
        subtasks = doc.list_subtasks(self._owner._selected_task_index)
        if subtasks:
            self._owner._selected_subtask_id = str(subtasks[0].get("id") or "s0")
        self._owner._populate_form_from_doc()
        self._owner._mark_form_dirty()

    def on_remove_task(self) -> None:
        doc = self._owner._ensure_config_doc()
        if self._owner._selected_task_index < 0:
            return
        doc.remove_task(self._owner._selected_task_index)
        remaining = len(doc.list_tasks())
        if remaining <= 0:
            self._owner._selected_task_index = -1
            self._owner._selected_subtask_id = "s0"
        else:
            self._owner._selected_task_index = min(self._owner._selected_task_index, remaining - 1)
            subtasks = doc.list_subtasks(self._owner._selected_task_index)
            self._owner._selected_subtask_id = (
                str(subtasks[0].get("id") or "s0") if subtasks else "s0"
            )
        self._owner._populate_form_from_doc()
        self._owner._mark_form_dirty()

    def on_add_resource(self) -> None:
        doc = self._owner._ensure_config_doc()
        self._owner._selected_resource_index = doc.add_resource()
        self._owner._form_resource_enabled.setChecked(True)
        self._owner._populate_form_from_doc()
        self._owner._mark_form_dirty()

    def on_remove_resource(self) -> None:
        doc = self._owner._ensure_config_doc()
        if self._owner._selected_resource_index < 0:
            return
        doc.remove_resource(self._owner._selected_resource_index)
        remaining = len(doc.list_resources())
        if remaining <= 0:
            self._owner._selected_resource_index = -1
            self._owner._form_resource_enabled.setChecked(False)
        else:
            self._owner._selected_resource_index = min(self._owner._selected_resource_index, remaining - 1)
        self._owner._populate_form_from_doc()
        self._owner._mark_form_dirty()

    def on_task_selection_changed(self) -> None:
        if self._owner._suspend_form_events:
            return
        row = self._owner._task_table.currentRow()
        if row < 0:
            self._owner._selected_task_index = -1
            self._owner._selected_subtask_id = "s0"
            self._owner._dag_controller.refresh_dag_widgets(self._owner._ensure_config_doc())
            return
        self._owner._dag_controller.select_task(row, sync_table_selection=False)

    def on_resource_selection_changed(self) -> None:
        if self._owner._suspend_form_events:
            return
        row = self._owner._resource_table.currentRow()
        self._owner._selected_resource_index = row if row >= 0 else -1
        doc = self._owner._ensure_config_doc()
        self._owner._suspend_form_events = True
        try:
            self.refresh_selected_resource_fields(doc)
        finally:
            self._owner._suspend_form_events = False

    def on_task_table_cell_changed(self, row: int, col: int) -> None:
        if self._owner._suspend_form_events:
            return
        doc = self._owner._ensure_config_doc()
        if row < 0 or row >= len(doc.list_tasks()):
            return
        if col < 0 or col > 4:
            return

        self.validate_task_table()
        if self.has_table_validation_errors():
            self._owner._mark_form_dirty()
            self._owner._form_hint.setText(
                "Task table has validation errors. Fix highlighted cells before apply."
            )
            return

        self._patch_task_row_from_table(doc, row)
        self._owner._selected_task_index = row
        self._owner._populate_form_from_doc()
        self._owner._mark_form_dirty()

    def on_resource_table_cell_changed(self, row: int, col: int) -> None:
        if self._owner._suspend_form_events:
            return
        doc = self._owner._ensure_config_doc()
        if row < 0 or row >= len(doc.list_resources()):
            return
        if col < 0 or col > 3:
            return

        self.validate_resource_table()
        if self.has_table_validation_errors():
            self._owner._mark_form_dirty()
            self._owner._form_hint.setText(
                "Resource table has validation errors. Fix highlighted cells before apply."
            )
            return

        self._patch_resource_row_from_table(doc, row)
        self._owner._selected_resource_index = row
        self._owner._populate_form_from_doc()
        self._owner._mark_form_dirty()
