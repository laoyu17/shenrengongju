"""Controller for gantt style selection and legend cache handling."""

from __future__ import annotations

import zlib
from typing import TYPE_CHECKING

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

if TYPE_CHECKING:
    from rtos_sim.ui.app import MainWindow


class GanttStyleController:
    """Encapsulate gantt style cache and legend assembly logic."""

    def __init__(self, owner: MainWindow) -> None:
        self._owner = owner

    def task_color(self, task_id: str) -> QColor:
        return pg.intColor(
            zlib.crc32(task_id.encode("utf-8")) % 24,
            hues=24,
            values=1,
            minValue=170,
            maxValue=255,
        )

    def subtask_brush_style(self, task_id: str, subtask_id: str) -> Qt.BrushStyle:
        key = (task_id, subtask_id)
        cached = self._owner._subtask_style_cache.get(key)
        if cached is not None:
            return cached
        idx = zlib.crc32(f"{task_id}:{subtask_id}".encode("utf-8")) % len(self._owner._SUBTASK_BRUSH_STYLES)
        style = self._owner._SUBTASK_BRUSH_STYLES[idx]
        self._owner._subtask_style_cache[key] = style
        return style

    def segment_pen_style(self, segment_id: str, interrupted: bool) -> Qt.PenStyle:
        if interrupted:
            return Qt.PenStyle.DashLine
        cached = self._owner._segment_style_cache.get(segment_id)
        if cached is not None:
            return cached
        idx = zlib.crc32(segment_id.encode("utf-8")) % len(self._owner._SEGMENT_PEN_STYLES)
        style = self._owner._SEGMENT_PEN_STYLES[idx]
        self._owner._segment_style_cache[segment_id] = style
        return style

    def ensure_task_legend(self, task_id: str, color: QColor) -> None:
        plot_item = self._owner._plot.getPlotItem()
        if task_id in self._owner._legend_tasks or plot_item.legend is None:
            return
        sample = pg.PlotDataItem([0, 1], [0, 0], pen=pg.mkPen(color=color, width=6))
        plot_item.legend.addItem(sample, task_id)
        self._owner._legend_samples.append(sample)
        self._owner._legend_tasks.add(task_id)
