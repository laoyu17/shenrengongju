from __future__ import annotations

from dataclasses import dataclass, field

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor

from rtos_sim.ui.controllers.telemetry_controller import TelemetryController
from rtos_sim.ui.gantt_helpers import SegmentBlockItem, SegmentVisualMeta


class _Label:
    def __init__(self) -> None:
        self.value = ""

    def setText(self, value: str) -> None:  # noqa: N802
        self.value = value


class _PlainText:
    def __init__(self) -> None:
        self.value = ""
        self.visible = True

    def setPlainText(self, value: str) -> None:  # noqa: N802
        self.value = value

    def clear(self) -> None:
        self.value = ""

    def toPlainText(self) -> str:  # noqa: N802
        return self.value

    def hide(self) -> None:
        self.visible = False

    def show(self) -> None:
        self.visible = True


class _Toggle:
    def __init__(self, checked: bool = False) -> None:
        self.checked = checked

    def isChecked(self) -> bool:  # noqa: N802
        return self.checked


class _Viewport:
    def mapToGlobal(self, pos: QPointF) -> QPointF:  # noqa: N802
        return pos


class _Scene:
    def __init__(self, items: list[object] | None = None) -> None:
        self._items = items or []

    def items(self, _scene_pos: QPointF) -> list[object]:  # noqa: N802
        return list(self._items)


class _Plot:
    def __init__(self, scene: _Scene) -> None:
        self._scene = scene
        self._viewport = _Viewport()

    def scene(self) -> _Scene:
        return self._scene

    def mapFromScene(self, scene_pos: QPointF) -> QPointF:  # noqa: N802
        return scene_pos

    def viewport(self) -> _Viewport:
        return self._viewport


class _RawItem:
    def __init__(self, parent: object | None = None) -> None:
        self._parent = parent

    def parentItem(self) -> object | None:  # noqa: N802
        return self._parent


@dataclass
class _ClickEvent:
    accepted: bool = False
    scene_pos: QPointF = field(default_factory=QPointF)

    def scenePos(self) -> QPointF:  # noqa: N802
        return self.scene_pos

    def accept(self) -> None:
        self.accepted = True


class _Owner:
    def __init__(self, scene_items: list[object] | None = None) -> None:
        self._state_transitions: list[str] = []
        self._state_view = _PlainText()
        self._plot = _Plot(_Scene(scene_items))
        self._hovered_segment_key = "hovered"
        self._locked_segment_key: str | None = None
        self._hover_hint = _Label()
        self._details = _PlainText()
        self._legend_toggle_subtask = _Toggle(False)
        self._legend_toggle_segment = _Toggle(False)
        self._subtask_legend_map = {("t0", "s0"): "solid"}
        self._segment_legend_map = {"seg0": "dash"}
        self._legend_detail = _PlainText()

    def _format_segment_details(self, meta: SegmentVisualMeta) -> str:
        return f"segment_key: {meta.segment_key}"


def _segment_item(segment_key: str = "seg-key") -> SegmentBlockItem:
    meta = SegmentVisualMeta(
        task_id="t0",
        job_id="t0@0",
        subtask_id="s0",
        segment_id="seg0",
        segment_key=segment_key,
        core_id="c0",
        start=1.0,
        end=3.0,
        duration=2.0,
        status="Running",
        resources=[],
        event_id_start="e1",
        event_id_end="e2",
        seq_start=1,
        seq_end=2,
        correlation_id="corr",
        deadline=4.0,
        lateness_at_end=None,
        remaining_after_preempt=None,
        execution_time_est=None,
        context_overhead=None,
        migration_overhead=None,
        estimated_finish=None,
    )
    return SegmentBlockItem(
        meta=meta,
        y=0.0,
        lane_height=10.0,
        color=QColor("#4477aa"),
        brush_style=Qt.BrushStyle.SolidPattern,
        pen_style=Qt.PenStyle.SolidLine,
    )


def test_on_plot_mouse_moved_clears_hover_details_when_empty(monkeypatch) -> None:
    owner = _Owner(scene_items=[])
    owner._details.setPlainText("stale")
    hidden = {"count": 0}
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.telemetry_controller.QToolTip.hideText",
        lambda: hidden.__setitem__("count", hidden["count"] + 1),
    )
    controller = TelemetryController(owner)

    controller.on_plot_mouse_moved(QPointF())

    assert owner._hovered_segment_key is None
    assert owner._details.toPlainText() == ""
    assert owner._hover_hint.value == "Hover a segment for details. Click segment to lock/unlock."
    assert hidden["count"] == 1


def test_on_plot_mouse_clicked_clears_lock_on_blank_area() -> None:
    owner = _Owner(scene_items=[])
    owner._locked_segment_key = "seg-key"
    controller = TelemetryController(owner)
    event = _ClickEvent(scene_pos=QPointF())

    controller.on_plot_mouse_clicked(event)

    assert owner._locked_segment_key is None
    assert event.accepted is True


def test_segment_item_from_scene_supports_parent_fallback() -> None:
    parent = _segment_item()
    owner = _Owner(scene_items=[_RawItem(parent=parent)])
    controller = TelemetryController(owner)

    result = controller.segment_item_from_scene(QPointF())

    assert result is parent


def test_reset_panel_state_clears_all_transient_state(monkeypatch) -> None:
    owner = _Owner(scene_items=[])
    owner._hovered_segment_key = "seg-key"
    owner._locked_segment_key = "seg-key"
    owner._details.setPlainText("locked")
    owner._state_transitions = ["t=1.0 [Running] demo"]
    owner._state_view.setPlainText("demo")
    owner._legend_toggle_subtask.checked = True
    hidden = {"count": 0}
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.telemetry_controller.QToolTip.hideText",
        lambda: hidden.__setitem__("count", hidden["count"] + 1),
    )
    controller = TelemetryController(owner)

    controller.reset_panel_state()

    assert owner._hovered_segment_key is None
    assert owner._locked_segment_key is None
    assert owner._details.toPlainText() == ""
    assert owner._state_transitions == []
    assert owner._state_view.toPlainText() == ""
    assert "Subtask Legend" in owner._legend_detail.toPlainText()
    assert hidden["count"] == 1

