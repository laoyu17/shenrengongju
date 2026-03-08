from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QTableWidget

from rtos_sim.ui.app import MainWindow
from rtos_sim.ui.config_doc import ConfigDocument
from rtos_sim.ui.controllers.table_editor_controller import TableEditorController


APP = QApplication.instance() or QApplication([])


def _make_window() -> MainWindow:
    assert APP is not None
    return MainWindow()


def test_refresh_tables_clear_selection_when_index_out_of_range() -> None:
    window = _make_window()
    try:
        doc = ConfigDocument.from_payload({"version": "0.2", "tasks": [], "resources": []})
        window._selected_task_index = 99
        window._selected_resource_index = 99

        window._table_editor_controller.refresh_task_table(doc)
        window._table_editor_controller.refresh_resource_table(doc)

        assert window._task_table.currentRow() == -1
        assert window._resource_table.currentRow() == -1
    finally:
        window.close()


def test_refresh_selected_fields_normalize_indices_and_missing_subtask() -> None:
    window = _make_window()
    try:
        doc = ConfigDocument.from_payload(
            {
                "version": "0.2",
                "resources": [{"id": "r0", "name": "lock", "bound_core_id": "c0", "protocol": "mutex"}],
                "tasks": [
                    {
                        "id": "t0",
                        "name": "task",
                        "task_type": "dynamic_rt",
                        "arrival": 0.0,
                        "subtasks": [{"id": "s0", "segments": [{"id": "seg0", "wcet": 1.0}]}],
                    }
                ],
            }
        )
        window._selected_resource_index = -1
        window._selected_task_index = -1
        window._selected_subtask_id = "missing"

        window._table_editor_controller.refresh_selected_resource_fields(doc)
        window._table_editor_controller.refresh_selected_task_fields(doc)

        assert window._selected_resource_index == 0
        assert window._selected_task_index == 0
        assert window._selected_subtask_id == "s0"
    finally:
        window.close()


def test_set_table_cell_error_creates_item_and_empty_error_message_is_blank() -> None:
    class _Owner:
        def __init__(self) -> None:
            self._table_validation_errors = {}

    owner = _Owner()
    table = QTableWidget(1, 1)
    controller = TableEditorController(owner)  # type: ignore[arg-type]
    try:
        assert controller.first_table_validation_error() == ""

        controller._set_table_cell_error(
            table_key="task",
            table=table,
            row=0,
            col=0,
            error="bad id",
        )

        item = table.item(0, 0)
        assert item is not None
        index = table.model().index(0, 0)
        assert owner._table_validation_errors[("task", 0, 0)] == "bad id"
        assert table.model().data(index, Qt.ItemDataRole.BackgroundRole) is not None
    finally:
        table.deleteLater()


def test_table_editor_short_circuit_paths_keep_state_stable() -> None:
    window = _make_window()
    try:
        controller = window._table_editor_controller
        window._config_doc = ConfigDocument.from_payload({"version": "0.2", "tasks": [], "resources": []})

        window._selected_task_index = -1
        controller.on_remove_task()
        assert window._selected_task_index == -1

        window._selected_resource_index = -1
        controller.on_remove_resource()
        assert window._selected_resource_index == -1

        window._suspend_form_events = True
        controller.on_task_selection_changed()
        controller.on_resource_selection_changed()
        controller.on_task_table_cell_changed(0, 0)
        controller.on_resource_table_cell_changed(0, 0)
        window._suspend_form_events = False

        controller.on_task_table_cell_changed(-1, 0)
        controller.on_resource_table_cell_changed(-1, 0)
    finally:
        window.close()
