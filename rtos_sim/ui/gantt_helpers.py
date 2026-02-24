"""Gantt visualization primitives and formatting helpers for the UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import QGraphicsRectItem


@dataclass(slots=True)
class SegmentVisualMeta:
    task_id: str
    job_id: str
    subtask_id: str
    segment_id: str
    segment_key: str
    core_id: str
    start: float
    end: float
    duration: float
    status: str
    resources: list[str]
    event_id_start: str
    event_id_end: str
    seq_start: int | None
    seq_end: int | None
    correlation_id: str
    deadline: float | None
    lateness_at_end: float | None
    remaining_after_preempt: float | None
    execution_time_est: float | None
    context_overhead: float | None
    migration_overhead: float | None
    estimated_finish: float | None


class SegmentBlockItem(QGraphicsRectItem):
    """Rect block in gantt with hover metadata."""

    def __init__(
        self,
        *,
        meta: SegmentVisualMeta,
        y: float,
        lane_height: float,
        color: QColor,
        brush_style: Qt.BrushStyle,
        pen_style: Qt.PenStyle,
    ) -> None:
        super().__init__(meta.start, y - lane_height / 2.0, max(meta.duration, 1e-6), lane_height)
        self.meta = meta

        brush = QBrush(color)
        brush.setStyle(brush_style)
        self.setBrush(brush)
        self.setPen(pg.mkPen(color="#f0f0f0", width=1.2, style=pen_style))
        self.setAcceptHoverEvents(True)
        self.setZValue(2)
        self.setToolTip(_build_brief_tooltip(meta))


def _build_brief_tooltip(meta: SegmentVisualMeta) -> str:
    return (
        f"{meta.task_id}/{meta.subtask_id}/{meta.segment_id}"
        f"\ncore={meta.core_id} [{meta.start:.3f}, {meta.end:.3f}]"
    )


def fmt_optional_int(value: int | None) -> str:
    return "-" if value is None else str(value)


def fmt_optional_float(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_optional_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_optional_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def task_from_job(job_id: str) -> str:
    if not job_id:
        return "unknown"
    return job_id.rsplit("@", 1)[0]


def parse_segment_key(segment_key: str) -> tuple[str, str]:
    parts = segment_key.rsplit(":", 2)
    if len(parts) != 3:
        return ("unknown", "unknown")
    return (parts[1], parts[2])


def brush_style_name(style: Qt.BrushStyle) -> str:
    names = {
        Qt.BrushStyle.SolidPattern: "Solid",
        Qt.BrushStyle.Dense4Pattern: "Dense4",
        Qt.BrushStyle.Dense6Pattern: "Dense6",
        Qt.BrushStyle.BDiagPattern: "BackwardDiag",
        Qt.BrushStyle.DiagCrossPattern: "DiagCross",
        Qt.BrushStyle.CrossPattern: "Cross",
    }
    return names.get(style, style.name)


def pen_style_name(style: Qt.PenStyle) -> str:
    names = {
        Qt.PenStyle.SolidLine: "Solid",
        Qt.PenStyle.DashLine: "Dash",
        Qt.PenStyle.DotLine: "Dot",
        Qt.PenStyle.DashDotLine: "DashDot",
        Qt.PenStyle.DashDotDotLine: "DashDotDot",
    }
    return names.get(style, style.name)


def format_segment_details(meta: SegmentVisualMeta) -> str:
    resources_text = ", ".join(meta.resources) if meta.resources else "-"
    return (
        f"task_id: {meta.task_id}\n"
        f"job_id: {meta.job_id}\n"
        f"subtask_id: {meta.subtask_id}\n"
        f"segment_id: {meta.segment_id}\n"
        f"segment_key: {meta.segment_key}\n"
        f"core_id: {meta.core_id}\n"
        f"start_time: {meta.start:.3f}\n"
        f"end_time: {meta.end:.3f}\n"
        f"duration: {meta.duration:.3f}\n"
        f"status: {meta.status}\n"
        f"resources: {resources_text}\n"
        f"event_id_start: {meta.event_id_start or '-'}\n"
        f"event_id_end: {meta.event_id_end or '-'}\n"
        f"seq_start: {fmt_optional_int(meta.seq_start)}\n"
        f"seq_end: {fmt_optional_int(meta.seq_end)}\n"
        f"correlation_id: {meta.correlation_id or '-'}\n"
        f"deadline: {fmt_optional_float(meta.deadline)}\n"
        f"lateness_at_end: {fmt_optional_float(meta.lateness_at_end)}\n"
        f"remaining_after_preempt: {fmt_optional_float(meta.remaining_after_preempt)}\n"
        f"execution_time_est: {fmt_optional_float(meta.execution_time_est)}\n"
        f"context_overhead: {fmt_optional_float(meta.context_overhead)}\n"
        f"migration_overhead: {fmt_optional_float(meta.migration_overhead)}\n"
        f"estimated_finish: {fmt_optional_float(meta.estimated_finish)}"
    )


__all__ = [
    "SegmentBlockItem",
    "SegmentVisualMeta",
    "brush_style_name",
    "format_segment_details",
    "parse_segment_key",
    "pen_style_name",
    "safe_float",
    "safe_optional_float",
    "safe_optional_int",
    "task_from_job",
]
