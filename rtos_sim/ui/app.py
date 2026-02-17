"""PyQt6 UI app for simulation control and visualization."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import zlib

import pyqtgraph as pg
import yaml
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QBrush, QColor, QCursor
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGraphicsRectItem,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextEdit,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from rtos_sim.io import ConfigError, ConfigLoader

from .worker import SimulationWorker


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
        self.setToolTip(self._build_brief_tooltip())

    def _build_brief_tooltip(self) -> str:
        return (
            f"{self.meta.task_id}/{self.meta.subtask_id}/{self.meta.segment_id}"
            f"\ncore={self.meta.core_id} [{self.meta.start:.3f}, {self.meta.end:.3f}]"
        )


class MainWindow(QMainWindow):
    """Main window with config editor, run controls and Gantt view."""

    _SUBTASK_BRUSH_STYLES = [
        Qt.BrushStyle.SolidPattern,
        Qt.BrushStyle.Dense4Pattern,
        Qt.BrushStyle.Dense6Pattern,
        Qt.BrushStyle.BDiagPattern,
        Qt.BrushStyle.DiagCrossPattern,
        Qt.BrushStyle.CrossPattern,
    ]
    _SEGMENT_PEN_STYLES = [
        Qt.PenStyle.SolidLine,
        Qt.PenStyle.DotLine,
        Qt.PenStyle.DashDotLine,
        Qt.PenStyle.DashDotDotLine,
    ]

    def __init__(self, config_path: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("RTOS Sim UI (PyQt6)")
        self.resize(1500, 920)

        self._loader = ConfigLoader()
        self._worker: SimulationWorker | None = None

        self._core_to_y: dict[str, int] = {}
        self._active_segments: dict[str, dict[str, Any]] = {}
        self._segment_resources: dict[str, set[str]] = {}
        self._job_deadlines: dict[str, float | None] = {}

        self._legend_tasks: set[str] = set()
        self._legend_samples: list[pg.PlotDataItem] = []
        self._subtask_legend_map: dict[tuple[str, str], str] = {}
        self._segment_legend_map: dict[str, str] = {}

        self._subtask_style_cache: dict[tuple[str, str], Qt.BrushStyle] = {}
        self._segment_style_cache: dict[str, Qt.PenStyle] = {}

        self._segment_items: list[SegmentBlockItem] = []
        self._segment_labels: list[pg.TextItem] = []
        self._seen_event_ids: set[str] = set()

        self._max_time = 0.0
        self._lane_height = 0.62
        self._segment_label_min_duration = 0.85

        self._hovered_segment_key: str | None = None
        self._locked_segment_key: str | None = None

        self._editor = QPlainTextEdit()
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        self._validate_button = QPushButton("Validate")
        self._run_button = QPushButton("Run")
        self._stop_button = QPushButton("Stop")
        self._load_button = QPushButton("Load")
        self._save_button = QPushButton("Save")
        self._status_label = QLabel("Ready")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self._plot = pg.PlotWidget(title="Gantt (CPU Lanes)")
        self._plot.showGrid(x=True, y=True)
        self._plot.setLabel("bottom", "Time")
        self._plot.setLabel("left", "Core")
        self._plot.addLegend(offset=(10, 10))

        self._legend_toggle_subtask = QPushButton("Subtask Legend")
        self._legend_toggle_subtask.setCheckable(True)
        self._legend_toggle_segment = QPushButton("Segment Legend")
        self._legend_toggle_segment.setCheckable(True)

        self._legend_detail = QPlainTextEdit()
        self._legend_detail.setReadOnly(True)
        self._legend_detail.setMaximumHeight(120)
        self._legend_detail.hide()

        self._hover_hint = QLabel("Hover a segment for details. Click segment to lock/unlock.")

        self._metrics = QTextEdit()
        self._metrics.setReadOnly(True)

        self._details = QPlainTextEdit()
        self._details.setReadOnly(True)
        self._details.setMaximumHeight(200)

        self._build_layout()
        self._connect_signals()

        if config_path:
            self._load_file(config_path)

    def _build_layout(self) -> None:
        root = QWidget(self)
        root_layout = QVBoxLayout(root)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self._load_button)
        toolbar.addWidget(self._save_button)
        toolbar.addWidget(self._validate_button)
        toolbar.addWidget(self._run_button)
        toolbar.addWidget(self._stop_button)
        toolbar.addStretch(1)
        toolbar.addWidget(self._status_label)
        root_layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        editor_container = QWidget()
        editor_layout = QVBoxLayout(editor_container)
        editor_layout.addWidget(QLabel("Config Editor (YAML/JSON)"))
        editor_layout.addWidget(self._editor)
        splitter.addWidget(editor_container)

        viz_container = QWidget()
        viz_layout = QVBoxLayout(viz_container)
        viz_layout.addWidget(self._plot, stretch=3)

        legend_toolbar = QHBoxLayout()
        legend_toolbar.addWidget(QLabel("Legend"))
        legend_toolbar.addWidget(self._legend_toggle_subtask)
        legend_toolbar.addWidget(self._legend_toggle_segment)
        legend_toolbar.addStretch(1)
        viz_layout.addLayout(legend_toolbar)
        viz_layout.addWidget(self._legend_detail)
        viz_layout.addWidget(self._hover_hint)

        viz_layout.addWidget(QLabel("Metrics / Logs"))
        viz_layout.addWidget(self._metrics, stretch=2)
        viz_layout.addWidget(QLabel("Segment Details (Hover/Click lock)"))
        viz_layout.addWidget(self._details, stretch=2)

        splitter.addWidget(viz_container)
        splitter.setSizes([560, 940])

        root_layout.addWidget(splitter)
        self.setCentralWidget(root)
        self._stop_button.setEnabled(False)

    def _connect_signals(self) -> None:
        self._load_button.clicked.connect(self._pick_load_file)
        self._save_button.clicked.connect(self._pick_save_file)
        self._validate_button.clicked.connect(self._on_validate)
        self._run_button.clicked.connect(self._on_run)
        self._stop_button.clicked.connect(self._on_stop)
        self._legend_toggle_subtask.toggled.connect(self._refresh_legend_details)
        self._legend_toggle_segment.toggled.connect(self._refresh_legend_details)

        scene = self._plot.scene()
        scene.sigMouseMoved.connect(self._on_plot_mouse_moved)
        scene.sigMouseClicked.connect(self._on_plot_mouse_clicked)

    def _pick_load_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open config",
            str(Path.cwd()),
            "Config Files (*.yaml *.yml *.json)",
        )
        if path:
            self._load_file(path)

    def _load_file(self, path: str) -> None:
        content = Path(path).read_text(encoding="utf-8")
        self._editor.setPlainText(content)
        self._status_label.setText(f"Loaded: {path}")

    def _pick_save_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save config",
            str(Path.cwd() / "config.yaml"),
            "Config Files (*.yaml *.yml *.json)",
        )
        if not path:
            return
        Path(path).write_text(self._editor.toPlainText(), encoding="utf-8")
        self._status_label.setText(f"Saved: {path}")

    def _on_validate(self) -> None:
        try:
            payload = yaml.safe_load(self._editor.toPlainText())
            if not isinstance(payload, dict):
                raise ConfigError("config root must be object")
            self._loader.load_data(payload)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Validation failed", str(exc))
            self._status_label.setText("Validation failed")
            return
        self._status_label.setText("Validation passed")
        QMessageBox.information(self, "Validation", "Config validation passed.")

    def _on_run(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        self._reset_viz()
        self._metrics.clear()

        self._worker = SimulationWorker(self._editor.toPlainText())
        self._worker.events_batch.connect(self._on_event_batch)
        self._worker.finished_report.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

        self._run_button.setEnabled(False)
        self._stop_button.setEnabled(True)
        self._status_label.setText("Running")

    def _on_stop(self) -> None:
        if self._worker:
            self._worker.stop()
        self._status_label.setText("Stopping...")

    def _on_event_batch(self, events: list[dict[str, Any]]) -> None:
        for event in events:
            event_id = event.get("event_id")
            if event_id and event_id in self._seen_event_ids:
                continue
            if event_id:
                self._seen_event_ids.add(event_id)
            self._consume_event(event)

    def _consume_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type", ""))
        payload = event.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        segment_key = payload.get("segment_key")
        event_time = self._safe_float(event.get("time"), 0.0)
        self._max_time = max(self._max_time, event_time)

        if event_type == "JobReleased":
            job_id = str(event.get("job_id") or "")
            self._job_deadlines[job_id] = self._safe_optional_float(payload.get("absolute_deadline"))
            return

        if event_type == "ResourceAcquire" and isinstance(segment_key, str):
            resource_id = event.get("resource_id")
            if resource_id:
                self._segment_resources.setdefault(segment_key, set()).add(str(resource_id))
            return

        if event_type == "SegmentStart" and isinstance(segment_key, str):
            core_id = str(event.get("core_id") or "unknown")
            job_id = str(event.get("job_id") or "")
            subtask_id, parsed_segment_id = self._parse_segment_key(segment_key)
            self._active_segments[segment_key] = {
                "start": event_time,
                "core_id": core_id,
                "job_id": job_id,
                "task_id": self._task_from_job(job_id),
                "subtask_id": subtask_id,
                "segment_id": str(event.get("segment_id") or parsed_segment_id),
                "start_payload": payload,
                "start_event_id": str(event.get("event_id") or ""),
                "start_seq": self._safe_optional_int(event.get("seq")),
                "correlation_id": str(event.get("correlation_id") or ""),
                "absolute_deadline": self._job_deadlines.get(job_id),
            }
            return

        if event_type == "SegmentEnd" and isinstance(segment_key, str):
            self._close_segment(segment_key=segment_key, end_event=event, interrupted=False)
            return

        if event_type == "Preempt" and isinstance(segment_key, str):
            self._close_segment(segment_key=segment_key, end_event=event, interrupted=True)
            return

        if event_type == "DeadlineMiss":
            job_id = event.get("job_id", "")
            self._metrics.append(f"[DeadlineMiss] {job_id} at t={event_time:.3f}")

    def _close_segment(self, segment_key: str, end_event: dict[str, Any], interrupted: bool) -> None:
        start_data = self._active_segments.pop(segment_key, None)
        if not start_data:
            return

        start_time = self._safe_float(start_data.get("start"), 0.0)
        end_time = self._safe_float(end_event.get("time"), start_time)
        if end_time < start_time:
            return
        duration = max(0.0, end_time - start_time)

        start_payload = start_data.get("start_payload", {})
        if not isinstance(start_payload, dict):
            start_payload = {}

        deadline = self._safe_optional_float(start_data.get("absolute_deadline"))
        lateness = end_time - deadline if deadline is not None else None
        estimated_finish = self._safe_optional_float(start_payload.get("estimated_finish"))
        remaining_after_preempt = None
        if interrupted and estimated_finish is not None:
            remaining_after_preempt = max(0.0, estimated_finish - end_time)

        status = "Preempted" if interrupted else "Completed"
        meta = SegmentVisualMeta(
            task_id=str(start_data.get("task_id") or "unknown"),
            job_id=str(start_data.get("job_id") or ""),
            subtask_id=str(start_data.get("subtask_id") or "unknown"),
            segment_id=str(start_data.get("segment_id") or "unknown"),
            segment_key=segment_key,
            core_id=str(start_data.get("core_id") or "unknown"),
            start=start_time,
            end=end_time,
            duration=duration,
            status=status,
            resources=sorted(self._segment_resources.get(segment_key, set())),
            event_id_start=str(start_data.get("start_event_id") or ""),
            event_id_end=str(end_event.get("event_id") or ""),
            seq_start=self._safe_optional_int(start_data.get("start_seq")),
            seq_end=self._safe_optional_int(end_event.get("seq")),
            correlation_id=str(end_event.get("correlation_id") or start_data.get("correlation_id") or ""),
            deadline=deadline,
            lateness_at_end=lateness,
            remaining_after_preempt=remaining_after_preempt,
            execution_time_est=self._safe_optional_float(start_payload.get("execution_time")),
            context_overhead=self._safe_optional_float(start_payload.get("context_overhead")),
            migration_overhead=self._safe_optional_float(start_payload.get("migration_overhead")),
            estimated_finish=estimated_finish,
        )

        self._draw_gantt_segment(meta)

        self._metrics.append(
            f"[Segment] {meta.segment_key} task={meta.task_id} core={meta.core_id} "
            f"[{meta.start:.3f}, {meta.end:.3f}]"
            + (" (preempted)" if interrupted else "")
        )

        if interrupted:
            self._draw_preempt_marker(meta.end, meta.core_id)
            self._metrics.append(f"[Preempt] {meta.segment_key} at t={meta.end:.3f}")

        self._segment_resources.pop(segment_key, None)

    def _draw_gantt_segment(self, meta: SegmentVisualMeta) -> None:
        y = self._core_lane(meta.core_id)
        color = self._task_color(meta.task_id)
        brush_style = self._subtask_brush_style(meta.task_id, meta.subtask_id)
        pen_style = self._segment_pen_style(meta.segment_id, interrupted=(meta.status == "Preempted"))

        self._ensure_task_legend(meta.task_id, color)
        self._subtask_legend_map[(meta.task_id, meta.subtask_id)] = self._brush_style_name(brush_style)
        self._segment_legend_map[meta.segment_id] = self._pen_style_name(pen_style)
        self._refresh_legend_details()

        block = SegmentBlockItem(
            meta=meta,
            y=y,
            lane_height=self._lane_height,
            color=color,
            brush_style=brush_style,
            pen_style=pen_style,
        )
        self._plot.addItem(block)
        self._segment_items.append(block)

        if meta.duration >= self._segment_label_min_duration:
            label = pg.TextItem(text=meta.segment_id, anchor=(0.5, 0.5), color="#f4f4f4")
            label.setZValue(3)
            label.setPos(meta.start + meta.duration / 2.0, y)
            self._plot.addItem(label)
            self._segment_labels.append(label)

        self._plot.setXRange(0, max(1.0, self._max_time * 1.05), padding=0)

    def _draw_preempt_marker(self, event_time: float, core_id: str) -> None:
        if core_id not in self._core_to_y:
            return
        y = self._core_to_y[core_id]
        marker = pg.ScatterPlotItem(
            x=[event_time],
            y=[y],
            symbol="x",
            size=12,
            pen=pg.mkPen(color="#ffd54f", width=2),
            brush=pg.mkBrush("#ffd54f"),
        )
        marker.setZValue(4)
        self._plot.addItem(marker)

    def _core_lane(self, core_id: str) -> int:
        if core_id not in self._core_to_y:
            self._core_to_y[core_id] = len(self._core_to_y) + 1
            ticks = [(y, core) for core, y in sorted(self._core_to_y.items(), key=lambda item: item[1])]
            self._plot.getAxis("left").setTicks([ticks])
        return self._core_to_y[core_id]

    def _task_color(self, task_id: str) -> QColor:
        return pg.intColor(
            zlib.crc32(task_id.encode("utf-8")) % 24,
            hues=24,
            values=1,
            minValue=170,
            maxValue=255,
        )

    def _subtask_brush_style(self, task_id: str, subtask_id: str) -> Qt.BrushStyle:
        key = (task_id, subtask_id)
        cached = self._subtask_style_cache.get(key)
        if cached is not None:
            return cached
        idx = zlib.crc32(f"{task_id}:{subtask_id}".encode("utf-8")) % len(self._SUBTASK_BRUSH_STYLES)
        style = self._SUBTASK_BRUSH_STYLES[idx]
        self._subtask_style_cache[key] = style
        return style

    def _segment_pen_style(self, segment_id: str, interrupted: bool) -> Qt.PenStyle:
        if interrupted:
            return Qt.PenStyle.DashLine
        cached = self._segment_style_cache.get(segment_id)
        if cached is not None:
            return cached
        idx = zlib.crc32(segment_id.encode("utf-8")) % len(self._SEGMENT_PEN_STYLES)
        style = self._SEGMENT_PEN_STYLES[idx]
        self._segment_style_cache[segment_id] = style
        return style

    def _ensure_task_legend(self, task_id: str, color: QColor) -> None:
        plot_item = self._plot.getPlotItem()
        if task_id in self._legend_tasks or plot_item.legend is None:
            return
        sample = pg.PlotDataItem([0, 1], [0, 0], pen=pg.mkPen(color=color, width=6))
        plot_item.legend.addItem(sample, task_id)
        self._legend_samples.append(sample)
        self._legend_tasks.add(task_id)

    def _on_plot_mouse_moved(self, scene_pos: QPointF) -> None:
        item = self._segment_item_from_scene(scene_pos)
        if item is None:
            self._hovered_segment_key = None
            QToolTip.hideText()
            if self._locked_segment_key is None:
                self._hover_hint.setText("Hover a segment for details. Click segment to lock/unlock.")
                self._details.clear()
            return

        self._hovered_segment_key = item.meta.segment_key
        self._hover_hint.setText(
            f"Hover: {item.meta.task_id}/{item.meta.subtask_id}/{item.meta.segment_id} "
            f"core={item.meta.core_id} [{item.meta.start:.3f}, {item.meta.end:.3f}]"
        )
        QToolTip.showText(QCursor.pos(), item.toolTip())

        if self._locked_segment_key is None:
            self._details.setPlainText(self._format_segment_details(item.meta))

    def _on_plot_mouse_clicked(self, event: Any) -> None:
        scene_pos = event.scenePos() if hasattr(event, "scenePos") else QPointF()
        item = self._segment_item_from_scene(scene_pos)
        if item is None:
            self._locked_segment_key = None
            if self._hovered_segment_key is None:
                self._details.clear()
            if hasattr(event, "accept"):
                event.accept()
            return

        key = item.meta.segment_key
        if self._locked_segment_key == key:
            self._locked_segment_key = None
        else:
            self._locked_segment_key = key
            self._details.setPlainText(self._format_segment_details(item.meta))

        if hasattr(event, "accept"):
            event.accept()

    def _segment_item_from_scene(self, scene_pos: QPointF) -> SegmentBlockItem | None:
        for raw_item in self._plot.scene().items(scene_pos):
            if isinstance(raw_item, SegmentBlockItem):
                return raw_item
            parent = raw_item.parentItem() if hasattr(raw_item, "parentItem") else None
            if isinstance(parent, SegmentBlockItem):
                return parent
        return None

    def _refresh_legend_details(self) -> None:
        show_subtask = self._legend_toggle_subtask.isChecked()
        show_segment = self._legend_toggle_segment.isChecked()
        if not show_subtask and not show_segment:
            self._legend_detail.clear()
            self._legend_detail.hide()
            return

        lines: list[str] = []
        if show_subtask:
            lines.append("Subtask Legend (task/subtask -> brush pattern)")
            for (task_id, subtask_id), style_name in sorted(self._subtask_legend_map.items()):
                lines.append(f"- {task_id}/{subtask_id}: {style_name}")

        if show_segment:
            if lines:
                lines.append("")
            lines.append("Segment Legend (segment id -> border style)")
            for segment_id, style_name in sorted(self._segment_legend_map.items()):
                lines.append(f"- {segment_id}: {style_name}")

        self._legend_detail.setPlainText("\n".join(lines))
        self._legend_detail.show()

    def _format_segment_details(self, meta: SegmentVisualMeta) -> str:
        resources_text = ", ".join(meta.resources) if meta.resources else "-"
        deadline_text = self._fmt_optional_float(meta.deadline)
        lateness_text = self._fmt_optional_float(meta.lateness_at_end)
        remaining_text = self._fmt_optional_float(meta.remaining_after_preempt)
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
            f"seq_start: {self._fmt_optional_int(meta.seq_start)}\n"
            f"seq_end: {self._fmt_optional_int(meta.seq_end)}\n"
            f"correlation_id: {meta.correlation_id or '-'}\n"
            f"deadline: {deadline_text}\n"
            f"lateness_at_end: {lateness_text}\n"
            f"remaining_after_preempt: {remaining_text}\n"
            f"execution_time_est: {self._fmt_optional_float(meta.execution_time_est)}\n"
            f"context_overhead: {self._fmt_optional_float(meta.context_overhead)}\n"
            f"migration_overhead: {self._fmt_optional_float(meta.migration_overhead)}\n"
            f"estimated_finish: {self._fmt_optional_float(meta.estimated_finish)}"
        )

    @staticmethod
    def _fmt_optional_int(value: int | None) -> str:
        return "-" if value is None else str(value)

    @staticmethod
    def _fmt_optional_float(value: float | None) -> str:
        return "-" if value is None else f"{value:.3f}"

    @staticmethod
    def _safe_float(value: Any, default: float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_optional_float(value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_optional_int(value: Any) -> int | None:
        try:
            if value is None:
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _task_from_job(job_id: str) -> str:
        if not job_id:
            return "unknown"
        return job_id.split("@", 1)[0]

    @staticmethod
    def _parse_segment_key(segment_key: str) -> tuple[str, str]:
        parts = segment_key.split(":", 2)
        if len(parts) != 3:
            return ("unknown", "unknown")
        return (parts[1], parts[2])

    @staticmethod
    def _brush_style_name(style: Qt.BrushStyle) -> str:
        names = {
            Qt.BrushStyle.SolidPattern: "Solid",
            Qt.BrushStyle.Dense4Pattern: "Dense4",
            Qt.BrushStyle.Dense6Pattern: "Dense6",
            Qt.BrushStyle.BDiagPattern: "BackwardDiag",
            Qt.BrushStyle.DiagCrossPattern: "DiagCross",
            Qt.BrushStyle.CrossPattern: "Cross",
        }
        return names.get(style, style.name)

    @staticmethod
    def _pen_style_name(style: Qt.PenStyle) -> str:
        names = {
            Qt.PenStyle.SolidLine: "Solid",
            Qt.PenStyle.DashLine: "Dash",
            Qt.PenStyle.DotLine: "Dot",
            Qt.PenStyle.DashDotLine: "DashDot",
            Qt.PenStyle.DashDotDotLine: "DashDotDot",
        }
        return names.get(style, style.name)

    def _on_finished(self, report: dict[str, Any], tail_events: list[dict[str, Any]]) -> None:
        if tail_events:
            self._on_event_batch(tail_events)
        self._metrics.append("\n=== Metrics ===")
        self._metrics.append(json.dumps(report, ensure_ascii=False, indent=2))
        self._status_label.setText("Completed")
        self._run_button.setEnabled(True)
        self._stop_button.setEnabled(False)
        self._worker = None

    def _on_failed(self, error_message: str) -> None:
        self._metrics.append(f"[Error] {error_message}")
        QMessageBox.critical(self, "Simulation failed", error_message)
        self._status_label.setText("Failed")
        self._run_button.setEnabled(True)
        self._stop_button.setEnabled(False)
        self._worker = None

    def _reset_viz(self) -> None:
        self._plot.clear()
        plot_item = self._plot.getPlotItem()
        if plot_item.legend is not None:
            plot_item.legend.scene().removeItem(plot_item.legend)
            plot_item.legend = None
        self._plot.addLegend(offset=(10, 10))

        self._core_to_y.clear()
        self._active_segments.clear()
        self._segment_resources.clear()
        self._job_deadlines.clear()

        self._legend_tasks.clear()
        self._legend_samples.clear()
        self._subtask_legend_map.clear()
        self._segment_legend_map.clear()
        self._subtask_style_cache.clear()
        self._segment_style_cache.clear()

        self._segment_items.clear()
        self._segment_labels.clear()
        self._seen_event_ids.clear()

        self._max_time = 0.0
        self._hovered_segment_key = None
        self._locked_segment_key = None

        self._hover_hint.setText("Hover a segment for details. Click segment to lock/unlock.")
        self._details.clear()
        self._refresh_legend_details()
        QToolTip.hideText()


def run_ui(config_path: str | None = None) -> None:
    app = QApplication.instance() or QApplication([])
    window = MainWindow(config_path=config_path)
    window.show()
    app.exec()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rtos-sim-ui")
    parser.add_argument("-c", "--config", default=None, help="initial config path")
    args = parser.parse_args(argv)
    run_ui(args.config)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
