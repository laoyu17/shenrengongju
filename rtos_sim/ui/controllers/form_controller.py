"""Controller for structured form/text synchronization paths."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

import yaml
from PyQt6.QtWidgets import QMessageBox

from rtos_sim.io import ConfigError
from rtos_sim.ui.config_doc import ConfigDocument


class UiErrorLogger(Protocol):
    def __call__(self, action: str, exc: Exception, **context: Any) -> None: ...


if TYPE_CHECKING:
    from rtos_sim.ui.app import MainWindow


class FormController:
    """Keep form sync behavior stable while reducing MainWindow complexity."""

    def __init__(self, owner: MainWindow, error_logger: UiErrorLogger) -> None:
        self._owner = owner
        self._error_logger = error_logger

    def on_sync_text_to_form(self) -> None:
        if self.sync_text_to_form(show_message=True):
            self._owner._status_label.setText("Form synced from text")

    def on_sync_form_to_text(self) -> None:
        if self.sync_form_to_text(show_message=True):
            self._owner._status_label.setText("Text updated from form")

    def sync_form_to_text_if_dirty(self) -> bool:
        if not self._owner._form_dirty:
            return True
        return self.sync_form_to_text(show_message=False)

    def sync_text_to_form(self, *, show_message: bool) -> bool:
        try:
            payload = self._owner._read_editor_payload()
        except (ConfigError, ValueError, TypeError, yaml.YAMLError) as exc:
            self._error_logger("sync_text_to_form", exc, show_message=show_message)
            if show_message:
                QMessageBox.critical(self._owner, "Sync failed", str(exc))
            self._owner._form_hint.setText("Sync Text -> Form failed.")
            return False

        self._owner._populate_form_from_payload(payload)
        self._owner._form_dirty = False
        self._owner._form_hint.setText("Form synced from text.")
        return True

    def sync_form_to_text(self, *, show_message: bool) -> bool:
        self._owner._validate_task_table()
        self._owner._validate_resource_table()
        if self._owner._has_table_validation_errors():
            message = self._owner._first_table_validation_error()
            if show_message:
                QMessageBox.warning(
                    self._owner,
                    "Sync blocked",
                    "Table validation failed. Fix highlighted cells first.\n" + message,
                )
            self._owner._form_hint.setText("Apply blocked: table validation failed.")
            return False

        if self._owner._config_doc is not None:
            base_payload = self._owner._config_doc.to_payload()
        else:
            try:
                base_payload = self._owner._read_editor_payload()
            except (ConfigError, ValueError, TypeError, yaml.YAMLError) as exc:
                self._error_logger("sync_form_to_text_base_payload", exc)
                base_payload = {}

        try:
            payload = self._owner._apply_form_to_payload(base_payload)
            text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
        except (ConfigError, ValueError, TypeError, yaml.YAMLError) as exc:
            self._error_logger("sync_form_to_text", exc, show_message=show_message)
            if show_message:
                QMessageBox.critical(self._owner, "Sync failed", str(exc))
            self._owner._form_hint.setText("Apply Form -> Text failed.")
            return False

        self._owner._suspend_text_events = True
        try:
            self._owner._editor.setPlainText(text)
        finally:
            self._owner._suspend_text_events = False
        self._owner._config_doc = ConfigDocument.from_payload(payload)
        self._owner._populate_form_from_doc()
        self._owner._form_dirty = False
        self._owner._form_hint.setText("Form applied to text.")
        return True
