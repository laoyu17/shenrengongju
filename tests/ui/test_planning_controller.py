from __future__ import annotations

from types import SimpleNamespace

import pytest

from rtos_sim.io import ConfigError
from rtos_sim.ui.controllers.planning_controller import PlanningController


class _Combo:
    def __init__(self, value: str) -> None:
        self._value = value

    def currentText(self) -> str:  # noqa: N802
        return self._value


class _CheckBox:
    def __init__(self, checked: bool = False) -> None:
        self._checked = checked

    def isChecked(self) -> bool:  # noqa: N802
        return self._checked


class _Number:
    def __init__(self, value: int | float) -> None:
        self._value = value

    def value(self) -> int | float:  # noqa: N802
        return self._value


class _Label:
    def __init__(self) -> None:
        self.value = ""

    def setText(self, value: str) -> None:  # noqa: N802
        self.value = value


class _PlainText:
    def __init__(self) -> None:
        self._text = ""

    def appendPlainText(self, value: str) -> None:  # noqa: N802
        if self._text:
            self._text += "\n"
        self._text += value

    def toPlainText(self) -> str:  # noqa: N802
        return self._text


class _Table:
    def __init__(self) -> None:
        self.row_count = 0
        self.items: dict[tuple[int, int], str] = {}
        self.blocked: list[bool] = []

    def blockSignals(self, value: bool) -> None:  # noqa: N802
        self.blocked.append(bool(value))

    def setRowCount(self, value: int) -> None:  # noqa: N802
        self.row_count = value

    def rowCount(self) -> int:  # noqa: N802
        return self.row_count

    def setItem(self, row: int, col: int, item: object) -> None:  # noqa: N802
        self.items[(row, col)] = item.text()


class _Loader:
    def __init__(self, spec: object | None = None, exc: Exception | None = None) -> None:
        self._spec = spec if spec is not None else object()
        self._exc = exc

    def load_data(self, payload: dict) -> object:
        if self._exc is not None:
            raise self._exc
        return self._spec


class _Owner:
    def __init__(self) -> None:
        self._planning_output = _PlainText()
        self._planning_horizon = _Number(0.0)
        self._planning_planner = _Combo("np_edf")
        self._planning_lp_objective = _Combo("response_time")
        self._planning_task_scope = _Combo("sync_only")
        self._planning_include_non_rt = _CheckBox(False)
        self._planning_time_limit = _Number(3.0)
        self._planning_wcrt_max_iterations = _Number(8)
        self._planning_wcrt_epsilon = _Number(1e-6)
        self._planning_windows_table = _Table()
        self._planning_wcrt_table = _Table()
        self._planning_os_table = _Table()
        self._status_label = _Label()

        self._loader = _Loader()
        self._payload = {"version": "0.2", "tasks": []}
        self._sync_ok = True

        self._latest_plan_result = None
        self._latest_plan_payload = None
        self._latest_plan_spec_fingerprint = None
        self._latest_plan_semantic_fingerprint = None
        self._latest_planning_wcrt_report = None
        self._latest_planning_os_payload = None

    def _sync_form_to_text_if_dirty(self) -> bool:
        return self._sync_ok

    def _read_editor_payload(self) -> dict:
        return dict(self._payload)


def _build_controller(owner: _Owner, errors: list[tuple[str, Exception]]) -> PlanningController:
    return PlanningController(owner, lambda action, exc, **_ctx: errors.append((action, exc)))


def test_prepare_spec_invalid_config_sets_status_and_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _Owner()
    owner._loader = _Loader(exc=ConfigError("bad payload"))
    errors: list[tuple[str, Exception]] = []
    dialogs: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.planning_controller.QMessageBox.critical",
        lambda _parent, title, message: dialogs.append((title, message)),
    )
    controller = _build_controller(owner, errors)

    assert controller._prepare_spec() is None
    assert owner._status_label.value == "Planning blocked by invalid config"
    assert errors and errors[0][0] == "planning_prepare_spec"
    assert dialogs == [("Planning failed", "Invalid config: bad payload")]


def test_set_table_rows_renders_none_as_blank() -> None:
    table = _Table()

    PlanningController._set_table_rows(table, [["t0", None, 3.5]])

    assert table.blocked == [True, False]
    assert table.rowCount() == 1
    assert table.items[(0, 0)] == "t0"
    assert table.items[(0, 1)] == ""
    assert table.items[(0, 2)] == "3.5"


def test_on_plan_analyze_wcrt_reports_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _Owner()
    owner._latest_plan_result = SimpleNamespace(schedule_table=object())
    errors: list[tuple[str, Exception]] = []
    dialogs: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.planning_controller.QMessageBox.critical",
        lambda _parent, title, message: dialogs.append((title, message)),
    )
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.planning_controller.sim_api.analyze_wcrt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("wcrt boom")),
    )
    controller = _build_controller(owner, errors)
    controller._prepare_spec = lambda: (object(), {})  # type: ignore[method-assign]
    controller._require_matching_latest_plan = lambda **_kwargs: True  # type: ignore[method-assign]

    controller.on_plan_analyze_wcrt()

    assert owner._status_label.value == "WCRT failed"
    assert dialogs == [("WCRT failed", "wcrt boom")]
    assert errors and errors[0][0] == "planning_analyze_wcrt"


def test_on_plan_export_os_config_renders_threads_and_logs_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = _Owner()
    errors: list[tuple[str, Exception]] = []
    controller = _build_controller(owner, errors)
    controller._prepare_spec = lambda: (object(), {})  # type: ignore[method-assign]
    controller._run_plan = lambda _spec, *, options: SimpleNamespace(schedule_table=object())  # type: ignore[method-assign]

    monkeypatch.setattr(
        "rtos_sim.ui.controllers.planning_controller.sim_api.export_os_config",
        lambda *_args, **_kwargs: {
            "threads": [
                {
                    "task_id": "t0",
                    "priority": 5,
                    "core_binding": ["c0", "c1"],
                    "primary_core": "c0",
                    "window_count": 2,
                    "deadline": 10.0,
                    "total_wcet": 4.0,
                },
                "ignored",
            ],
            "schedule_windows": [],
        },
    )

    controller.on_plan_export_os_config()

    assert errors == []
    assert owner._status_label.value == "OS config done"
    assert owner._planning_os_table.rowCount() == 1
    assert owner._planning_os_table.items[(0, 0)] == "t0"
    assert owner._planning_os_table.items[(0, 2)] == "c0,c1"
    assert owner._latest_planning_os_payload == {
        "threads": [
            {
                "task_id": "t0",
                "priority": 5,
                "core_binding": ["c0", "c1"],
                "primary_core": "c0",
                "window_count": 2,
                "deadline": 10.0,
                "total_wcet": 4.0,
            },
            "ignored",
        ],
        "schedule_windows": [],
    }
    assert "export-os-config done" in owner._planning_output.toPlainText()


def test_render_os_table_ignores_empty_or_invalid_threads() -> None:
    owner = _Owner()
    controller = _build_controller(owner, [])

    controller._render_os_table({"threads": [None, "bad", {}]})

    assert owner._planning_os_table.rowCount() == 1
    assert owner._planning_os_table.items[(0, 0)] == ""
