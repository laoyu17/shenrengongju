from __future__ import annotations

from dataclasses import dataclass

import pytest

from rtos_sim.io import ConfigError
from rtos_sim.ui.config_doc import ConfigDocument
from rtos_sim.ui.controllers.form_controller import FormController


@dataclass
class _Label:
    text: str = ""

    def setText(self, value: str) -> None:  # noqa: N802
        self.text = value


@dataclass
class _Editor:
    text: str = ""

    def setPlainText(self, value: str) -> None:  # noqa: N802
        self.text = value


class _Owner:
    def __init__(self) -> None:
        self._status_label = _Label()
        self._form_hint = _Label()
        self._form_dirty = True
        self._config_doc: ConfigDocument | None = None
        self._suspend_text_events = False
        self._editor = _Editor()

        self._table_error: str | None = None
        self._populate_payload_calls: list[dict] = []
        self._populate_doc_calls = 0
        self._apply_payload_calls: list[dict] = []

    def _read_editor_payload(self) -> dict:
        return {"version": "0.2", "tasks": []}

    def _populate_form_from_payload(self, payload: dict) -> None:
        self._populate_payload_calls.append(payload)

    def _validate_task_table(self) -> None:
        return None

    def _validate_resource_table(self) -> None:
        return None

    def _has_table_validation_errors(self) -> bool:
        return self._table_error is not None

    def _first_table_validation_error(self) -> str:
        return self._table_error or ""

    def _apply_form_to_payload(self, payload: dict) -> dict:
        self._apply_payload_calls.append(payload)
        updated = dict(payload)
        updated["tasks"] = [{"id": "t0"}]
        return updated

    def _populate_form_from_doc(self) -> None:
        self._populate_doc_calls += 1


def test_sync_text_to_form_success_updates_owner_state() -> None:
    owner = _Owner()
    logs: list[tuple[str, Exception]] = []
    controller = FormController(owner, lambda action, exc, **_: logs.append((action, exc)))

    assert controller.sync_text_to_form(show_message=False) is True
    assert owner._form_dirty is False
    assert owner._form_hint.text == "Form synced from text."
    assert owner._populate_payload_calls == [{"version": "0.2", "tasks": []}]
    assert logs == []


def test_sync_text_to_form_failure_sets_hint_and_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _Owner()
    errors: list[tuple[str, Exception]] = []
    dialogs: list[str] = []

    def _raise_config_error() -> dict:
        raise ConfigError("bad payload")

    owner._read_editor_payload = _raise_config_error  # type: ignore[method-assign]
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.form_controller.QMessageBox.critical",
        lambda *_args: dialogs.append("critical"),
    )

    controller = FormController(owner, lambda action, exc, **_: errors.append((action, exc)))
    assert controller.sync_text_to_form(show_message=True) is False

    assert owner._form_hint.text == "Sync Text -> Form failed."
    assert errors and errors[0][0] == "sync_text_to_form"
    assert dialogs == ["critical"]


def test_sync_form_to_text_blocks_on_table_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _Owner()
    owner._table_error = "row 1 invalid"
    warnings: list[str] = []
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.form_controller.QMessageBox.warning",
        lambda *_args: warnings.append("warning"),
    )

    controller = FormController(owner, lambda *_args, **_kwargs: None)

    assert controller.sync_form_to_text(show_message=True) is False
    assert owner._form_hint.text == "Apply blocked: table validation failed."
    assert warnings == ["warning"]


def test_sync_form_to_text_success_refreshes_editor_and_document() -> None:
    owner = _Owner()
    owner._config_doc = ConfigDocument.from_payload({"version": "0.2", "tasks": []})
    controller = FormController(owner, lambda *_args, **_kwargs: None)

    assert controller.sync_form_to_text(show_message=False) is True
    assert "tasks:" in owner._editor.text
    assert owner._config_doc is not None
    assert owner._config_doc.to_payload()["tasks"][0]["id"] == "t0"
    assert owner._populate_doc_calls == 1
    assert owner._form_dirty is False
    assert owner._form_hint.text == "Form applied to text."


def test_sync_form_to_text_blank_editor_avoids_startup_noise() -> None:
    owner = _Owner()
    owner._editor.text = ""
    owner._read_editor_payload = lambda: (_ for _ in ()).throw(ConfigError("blank editor"))  # type: ignore[method-assign]
    errors: list[tuple[str, Exception]] = []
    controller = FormController(owner, lambda action, exc, **_: errors.append((action, exc)))

    assert controller.sync_form_to_text(show_message=False) is True
    assert owner._apply_payload_calls == [{}]
    assert owner._form_hint.text == "Form applied to text."
    assert errors == []
