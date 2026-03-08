from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication
import pytest

from rtos_sim.io import ConfigError
from rtos_sim.ui.app import MainWindow
from rtos_sim.ui.config_doc import ConfigDocument
from rtos_sim.ui.controllers.document_sync_controller import DocumentSyncController


APP = QApplication.instance() or QApplication([])


def _make_window() -> MainWindow:
    assert APP is not None
    return MainWindow()


def test_read_editor_payload_rejects_non_mapping_root() -> None:
    window = _make_window()
    try:
        controller = DocumentSyncController(window, lambda *_args, **_kwargs: None)
        window._editor.setPlainText("[]")

        with pytest.raises(ConfigError, match="config root must be object"):
            controller.read_editor_payload()
    finally:
        window.close()


def test_ensure_config_doc_falls_back_to_empty_payload() -> None:
    window = _make_window()
    try:
        logs: list[str] = []
        controller = DocumentSyncController(window, lambda action, *_args, **_kwargs: logs.append(action))
        window._config_doc = None
        window._editor.setPlainText("[]")

        doc = controller.ensure_config_doc()

        assert doc.list_tasks() == []
        assert doc.list_resources() == []
        assert logs == ["ensure_config_doc_fallback"]
    finally:
        window.close()


def test_populate_form_from_doc_clamps_empty_selection_state() -> None:
    window = _make_window()
    try:
        controller = DocumentSyncController(window, lambda *_args, **_kwargs: None)
        window._config_doc = ConfigDocument.from_payload({"version": "0.2", "tasks": [], "resources": []})
        window._selected_task_index = 7
        window._selected_resource_index = 5

        controller.populate_form_from_doc()

        assert window._selected_task_index == -1
        assert window._selected_resource_index == -1
    finally:
        window.close()


def test_apply_form_to_document_handles_resource_disable_and_defaults() -> None:
    window = _make_window()
    try:
        controller = DocumentSyncController(window, lambda *_args, **_kwargs: None)
        window._form_resource_enabled.setChecked(False)
        window._selected_resource_index = -1
        window._selected_task_index = -1
        window._set_combo_value(window._form_task_type, "time_deterministic")
        window._form_task_period.setText("")
        window._form_task_deadline.setText("")

        doc = ConfigDocument.from_payload(
            {
                "version": "0.2",
                "resources": [{"id": "r0", "name": "lock", "bound_core_id": "c0", "protocol": "mutex"}],
                "tasks": [],
            }
        )

        controller.apply_form_to_document(doc)

        assert doc.list_resources() == []
        assert window._selected_resource_index == -1
        assert window._selected_task_index == 0
        task = doc.get_task(0)
        assert task["task_type"] == "time_deterministic"
        assert task["period"] == pytest.approx(10.0)
        assert task["deadline"] == pytest.approx(10.0)
        assert doc.list_subtasks(0)
    finally:
        window.close()


def test_apply_form_to_document_normalizes_negative_resource_selection() -> None:
    window = _make_window()
    try:
        controller = DocumentSyncController(window, lambda *_args, **_kwargs: None)
        window._form_resource_enabled.setChecked(True)
        window._selected_resource_index = -1
        window._selected_task_index = -1
        window._set_combo_value(window._form_task_type, "dynamic_rt")
        window._form_task_deadline.setText("")

        doc = ConfigDocument.from_payload(
            {
                "version": "0.2",
                "resources": [{"id": "r0", "name": "lock", "bound_core_id": "c0", "protocol": "mutex"}],
                "tasks": [],
            }
        )

        controller.apply_form_to_document(doc)

        assert window._selected_resource_index == 0
        assert doc.get_resource(0)["id"] == window._form_resource_id.text()
        assert doc.get_task(0)["deadline"] == pytest.approx(10.0)
    finally:
        window.close()
