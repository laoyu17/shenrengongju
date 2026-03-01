from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from rtos_sim.ui.controllers.compare_controller import CompareController


@dataclass
class _Label:
    value: str = ""

    def setText(self, value: str) -> None:  # noqa: N802
        self.value = value


class _LineEdit:
    def __init__(self, value: str = "") -> None:
        self._value = value

    def text(self) -> str:  # noqa: N802
        return self._value

    def setText(self, value: str) -> None:  # noqa: N802
        self._value = value


class _PlainText:
    def __init__(self) -> None:
        self._text = ""

    def appendPlainText(self, value: str) -> None:  # noqa: N802
        if self._text:
            self._text += "\n"
        self._text += value

    def setPlainText(self, value: str) -> None:  # noqa: N802
        self._text = value

    def toPlainText(self) -> str:  # noqa: N802
        return self._text


class _Group:
    def __init__(self, visible: bool = False) -> None:
        self._visible = visible

    def setVisible(self, visible: bool) -> None:  # noqa: N802
        self._visible = bool(visible)

    def isVisible(self) -> bool:  # noqa: N802
        return self._visible


@dataclass
class _Button:
    text: str = ""

    def setText(self, value: str) -> None:  # noqa: N802
        self.text = value


class _Splitter:
    def __init__(self, sizes: list[int], *, height: int = 0) -> None:
        self._sizes = list(sizes)
        self._height = height

    def sizes(self) -> list[int]:  # noqa: N802
        return list(self._sizes)

    def height(self) -> int:  # noqa: N802
        return self._height

    def setSizes(self, sizes: list[int]) -> None:  # noqa: N802
        self._sizes = list(sizes)


class _Scroll:
    def __init__(self) -> None:
        self.calls: list[tuple[object, int, int]] = []

    def ensureWidgetVisible(self, widget: object, x_margin: int, y_margin: int) -> None:  # noqa: N802
        self.calls.append((widget, x_margin, y_margin))


class _Owner:
    _RIGHT_SPLITTER_LOWER_RATIO_EXPANDED = 0.9
    _RIGHT_SPLITTER_LOWER_RATIO_COLLAPSED = 0.3
    _RIGHT_SPLITTER_LOWER_MIN_EXPANDED = 40
    _RIGHT_SPLITTER_LOWER_MIN_COLLAPSED = 10

    def __init__(self) -> None:
        self._compare_group: _Group | None = _Group(visible=False)
        self._compare_toggle_button = _Button()
        self._right_splitter: _Splitter | None = _Splitter([0, 0], height=50)
        self._telemetry_scroll: _Scroll | None = _Scroll()

        self._compare_left_metrics: dict | None = None
        self._compare_right_metrics: dict | None = None
        self._latest_metrics_report: dict | None = None
        self._latest_compare_report: dict | None = None

        self._compare_left_label = _LineEdit("")
        self._compare_right_label = _LineEdit("")
        self._compare_output = _PlainText()
        self._status_label = _Label()

        self._picked_paths: list[str] = []

    def _pick_metrics_file(self) -> str:
        return self._picked_paths.pop(0) if self._picked_paths else ""


def _build_controller(owner: _Owner, errors: list[tuple[str, str | None]]) -> CompareController:
    def _logger(action: str, _exc: Exception, **context: object) -> None:
        errors.append((action, str(context.get("path") if context else None)))

    return CompareController(owner, _logger)


def test_toggle_rebalance_and_visible_scroll() -> None:
    owner = _Owner()
    errors: list[tuple[str, str | None]] = []
    controller = _build_controller(owner, errors)

    controller.on_compare_toggle(True)

    assert owner._compare_group is not None and owner._compare_group.isVisible() is True
    assert owner._compare_toggle_button.text == "Hide FR-13 Compare"
    assert owner._right_splitter is not None and owner._right_splitter.sizes() == [60, 60]
    assert owner._telemetry_scroll is not None and owner._telemetry_scroll.calls

    controller.on_compare_toggle(False)

    assert owner._compare_group is not None and owner._compare_group.isVisible() is False
    assert owner._compare_toggle_button.text == "Show FR-13 Compare"
    assert errors == []


def test_toggle_and_visibility_guards() -> None:
    owner = _Owner()
    controller = _build_controller(owner, [])

    owner._compare_group = None
    controller.on_compare_toggle(True)

    owner._right_splitter = None
    controller.rebalance_right_splitter(compare_open=True)

    owner._compare_group = _Group(visible=False)
    owner._telemetry_scroll = None
    controller.ensure_compare_visible()

    owner._telemetry_scroll = _Scroll()
    controller.ensure_compare_visible()
    assert owner._telemetry_scroll.calls == []


def test_load_metrics_and_error_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _Owner()
    errors: list[tuple[str, str | None]] = []
    controller = _build_controller(owner, errors)

    critical_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.compare_controller.QMessageBox.critical",
        lambda _parent, title, message: critical_calls.append((title, message)),
    )

    left_path = tmp_path / "left.json"
    left_path.write_text(json.dumps({"jobs_completed": 2}), encoding="utf-8")
    owner._picked_paths = [str(left_path)]
    controller.on_compare_load_left()

    assert owner._compare_left_metrics == {"jobs_completed": 2}
    assert "left metrics loaded" in owner._compare_output.toPlainText()

    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("[]", encoding="utf-8")
    owner._picked_paths = [str(invalid_path)]
    controller.on_compare_load_right()

    assert owner._compare_right_metrics is None
    assert critical_calls and critical_calls[-1][0] == "Compare load failed"
    assert errors and errors[-1][0] == "compare_load_right"

    owner._picked_paths = [""]
    controller.on_compare_load_left()


def test_use_latest_and_build_report(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _Owner()
    controller = _build_controller(owner, [])

    info_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.compare_controller.QMessageBox.information",
        lambda _parent, title, message: info_calls.append((title, message)),
    )

    owner._latest_metrics_report = None
    controller.on_compare_use_latest_left()
    controller.on_compare_use_latest_right()
    assert len(info_calls) == 2

    owner._latest_metrics_report = {"jobs_completed": 3, "core_utilization": {"c0": 0.5}}
    controller.on_compare_use_latest_left()
    controller.on_compare_use_latest_right()
    assert owner._compare_left_metrics == owner._latest_metrics_report
    assert owner._compare_right_metrics == owner._latest_metrics_report

    owner._compare_left_metrics = None
    controller.on_compare_build()
    assert info_calls[-1][1].startswith("Please load/set both")

    owner._compare_left_metrics = {"jobs_completed": 2, "core_utilization": {"c0": 0.2}}
    owner._compare_right_metrics = {"jobs_completed": 5, "core_utilization": {"c0": 0.7}}
    owner._compare_left_label.setText("  ")
    owner._compare_right_label.setText("")
    controller.on_compare_build()

    assert owner._latest_compare_report is not None
    output = owner._compare_output.toPlainText()
    assert '"left_label": "left"' in output
    assert '"right_label": "right"' in output


def test_export_json_and_csv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _Owner()
    controller = _build_controller(owner, [])

    info_calls: list[tuple[str, str]] = []
    critical_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.compare_controller.QMessageBox.information",
        lambda _parent, title, message: info_calls.append((title, message)),
    )
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.compare_controller.QMessageBox.critical",
        lambda _parent, title, message: critical_calls.append((title, message)),
    )

    controller.on_compare_export_json()
    controller.on_compare_export_csv()
    assert [title for title, _ in info_calls] == ["Compare", "Compare"]

    owner._latest_compare_report = {
        "left_label": "l",
        "right_label": "r",
        "scalar_metrics": [],
        "core_utilization": [],
    }

    json_path = tmp_path / "report.json"
    csv_path = tmp_path / "report.csv"
    chooser = iter([(str(json_path), "JSON Files (*.json)"), (str(csv_path), "CSV Files (*.csv)")])
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.compare_controller.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: next(chooser),
    )

    controller.on_compare_export_json()
    controller.on_compare_export_csv()

    assert json_path.exists()
    assert csv_path.exists()
    assert owner._status_label.value == f"Compare CSV exported: {csv_path}"

    monkeypatch.setattr(
        "rtos_sim.ui.controllers.compare_controller.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: ("", ""),
    )
    controller.on_compare_export_json()
    controller.on_compare_export_csv()

    monkeypatch.setattr(
        "rtos_sim.ui.controllers.compare_controller.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: (str(json_path), "JSON Files (*.json)"),
    )
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.compare_controller.write_compare_report_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    controller.on_compare_export_json()

    monkeypatch.setattr(
        "rtos_sim.ui.controllers.compare_controller.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: (str(csv_path), "CSV Files (*.csv)"),
    )
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.compare_controller.write_compare_report_csv",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    controller.on_compare_export_csv()

    assert len(critical_calls) >= 2
