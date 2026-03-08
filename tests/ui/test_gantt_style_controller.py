from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

from rtos_sim.ui.controllers.gantt_style_controller import GanttStyleController


class _Legend:
    def __init__(self) -> None:
        self.items: list[tuple[object, str]] = []

    def addItem(self, sample: object, label: str) -> None:  # noqa: N802
        self.items.append((sample, label))


class _PlotItem:
    def __init__(self, legend: _Legend | None) -> None:
        self.legend = legend


class _Plot:
    def __init__(self, legend: _Legend | None) -> None:
        self._plot_item = _PlotItem(legend)

    def getPlotItem(self) -> _PlotItem:  # noqa: N802
        return self._plot_item


class _Owner:
    _SUBTASK_BRUSH_STYLES = [
        Qt.BrushStyle.SolidPattern,
        Qt.BrushStyle.Dense4Pattern,
        Qt.BrushStyle.Dense6Pattern,
    ]
    _SEGMENT_PEN_STYLES = [Qt.PenStyle.SolidLine, Qt.PenStyle.DotLine]

    def __init__(self, legend: _Legend | None) -> None:
        self._plot = _Plot(legend)
        self._subtask_style_cache: dict[tuple[str, str], Qt.BrushStyle] = {}
        self._segment_style_cache: dict[str, Qt.PenStyle] = {}
        self._legend_samples: list[object] = []
        self._legend_tasks: set[str] = set()


def test_task_color_is_stable_for_same_task_id() -> None:
    owner = _Owner(_Legend())
    controller = GanttStyleController(owner)

    first = controller.task_color("t0")
    second = controller.task_color("t0")
    other = controller.task_color("t1")

    assert isinstance(first, QColor)
    assert first == second
    assert first != other


def test_subtask_brush_style_caches_per_task_subtask() -> None:
    owner = _Owner(_Legend())
    controller = GanttStyleController(owner)

    style = controller.subtask_brush_style("t0", "s0")

    assert owner._subtask_style_cache[("t0", "s0")] == style
    assert controller.subtask_brush_style("t0", "s0") == style


def test_segment_pen_style_keeps_interrupted_path_out_of_cache() -> None:
    owner = _Owner(_Legend())
    controller = GanttStyleController(owner)

    interrupted = controller.segment_pen_style("seg0", interrupted=True)
    stable = controller.segment_pen_style("seg0", interrupted=False)

    assert interrupted == Qt.PenStyle.DashLine
    assert owner._segment_style_cache["seg0"] == stable
    assert controller.segment_pen_style("seg0", interrupted=False) == stable


def test_ensure_task_legend_is_idempotent_and_safe_without_legend() -> None:
    legend = _Legend()
    owner = _Owner(legend)
    controller = GanttStyleController(owner)

    controller.ensure_task_legend("t0", QColor("#123456"))
    controller.ensure_task_legend("t0", QColor("#123456"))

    assert len(legend.items) == 1
    assert legend.items[0][1] == "t0"
    assert len(owner._legend_samples) == 1
    assert owner._legend_tasks == {"t0"}

    no_legend_owner = _Owner(None)
    no_legend_controller = GanttStyleController(no_legend_owner)
    no_legend_controller.ensure_task_legend("t1", QColor("#abcdef"))
    assert no_legend_owner._legend_samples == []
    assert no_legend_owner._legend_tasks == set()

