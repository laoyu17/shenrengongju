from __future__ import annotations

import json
import logging

from rtos_sim.ui.app import _log_ui_error


def test_log_ui_error_emits_structured_payload(caplog) -> None:
    caplog.set_level(logging.ERROR)
    try:
        raise ValueError("bad payload")
    except ValueError as exc:
        _log_ui_error("unit_test", exc, path="artifacts/x.json", show_message=False)

    assert caplog.records
    payload = json.loads(caplog.records[-1].message)
    assert payload["event"] == "ui_error"
    assert payload["action"] == "unit_test"
    assert payload["error_type"] == "ValueError"
    assert payload["error_message"] == "bad payload"
    assert payload["path"] == "artifacts/x.json"
    assert payload["show_message"] is False
