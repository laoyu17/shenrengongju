"""Controller for simulation event consumption and timeline drawing."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pyqtgraph as pg
from rtos_sim.ui.gantt_helpers import (
    SegmentBlockItem,
    SegmentVisualMeta,
    brush_style_name,
    parse_segment_key,
    pen_style_name,
    safe_float,
    safe_optional_float,
    safe_optional_int,
    task_from_job,
)

if TYPE_CHECKING:
    from rtos_sim.ui.app import MainWindow


class TimelineController:
    """Preserve timeline behavior while reducing MainWindow method size."""

    def __init__(self, owner: MainWindow) -> None:
        self._owner = owner

    def on_event_batch(self, events: list[dict[str, Any]]) -> None:
        for event in events:
            event_id = event.get("event_id")
            if event_id and event_id in self._owner._seen_event_ids:
                continue
            if event_id:
                self._owner._seen_event_ids.add(event_id)
            self.consume_event(event)

    def consume_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type", ""))
        payload = event.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        segment_key = payload.get("segment_key")
        event_time = safe_float(event.get("time"), 0.0)
        self._owner._max_time = max(self._owner._max_time, event_time)

        if event_type == "JobReleased":
            job_id = str(event.get("job_id") or "")
            self._owner._job_deadlines[job_id] = safe_optional_float(payload.get("absolute_deadline"))
            return

        if event_type == "ResourceAcquire" and isinstance(segment_key, str):
            resource_id = event.get("resource_id")
            if resource_id:
                self._owner._segment_resources.setdefault(segment_key, set()).add(str(resource_id))
            return

        if event_type == "SegmentStart" and isinstance(segment_key, str):
            core_id = str(event.get("core_id") or "unknown")
            job_id = str(event.get("job_id") or "")
            subtask_id, parsed_segment_id = parse_segment_key(segment_key)
            self._owner._active_segments[segment_key] = {
                "start": event_time,
                "core_id": core_id,
                "job_id": job_id,
                "task_id": task_from_job(job_id),
                "subtask_id": subtask_id,
                "segment_id": str(event.get("segment_id") or parsed_segment_id),
                "start_payload": payload,
                "start_event_id": str(event.get("event_id") or ""),
                "start_seq": safe_optional_int(event.get("seq")),
                "correlation_id": str(event.get("correlation_id") or ""),
                "absolute_deadline": self._owner._job_deadlines.get(job_id),
            }
            return

        if event_type == "SegmentEnd" and isinstance(segment_key, str):
            self.close_segment(segment_key=segment_key, end_event=event, interrupted=False)
            return

        if event_type == "Preempt" and isinstance(segment_key, str):
            self.close_segment(segment_key=segment_key, end_event=event, interrupted=True)
            return

        if event_type == "DeadlineMiss":
            job_id = event.get("job_id", "")
            self._owner._metrics.append(f"[DeadlineMiss] {job_id} at t={event_time:.3f}")

    def close_segment(self, segment_key: str, end_event: dict[str, Any], interrupted: bool) -> None:
        start_data = self._owner._active_segments.pop(segment_key, None)
        if not start_data:
            return

        start_time = safe_float(start_data.get("start"), 0.0)
        end_time = safe_float(end_event.get("time"), start_time)
        if end_time < start_time:
            return
        duration = max(0.0, end_time - start_time)

        start_payload = start_data.get("start_payload", {})
        if not isinstance(start_payload, dict):
            start_payload = {}

        deadline = safe_optional_float(start_data.get("absolute_deadline"))
        lateness = end_time - deadline if deadline is not None else None
        estimated_finish = safe_optional_float(start_payload.get("estimated_finish"))
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
            resources=sorted(self._owner._segment_resources.get(segment_key, set())),
            event_id_start=str(start_data.get("start_event_id") or ""),
            event_id_end=str(end_event.get("event_id") or ""),
            seq_start=safe_optional_int(start_data.get("start_seq")),
            seq_end=safe_optional_int(end_event.get("seq")),
            correlation_id=str(end_event.get("correlation_id") or start_data.get("correlation_id") or ""),
            deadline=deadline,
            lateness_at_end=lateness,
            remaining_after_preempt=remaining_after_preempt,
            execution_time_est=safe_optional_float(start_payload.get("execution_time")),
            context_overhead=safe_optional_float(start_payload.get("context_overhead")),
            migration_overhead=safe_optional_float(start_payload.get("migration_overhead")),
            estimated_finish=estimated_finish,
        )

        self.draw_gantt_segment(meta)

        self._owner._metrics.append(
            f"[Segment] {meta.segment_key} task={meta.task_id} core={meta.core_id} "
            f"[{meta.start:.3f}, {meta.end:.3f}]"
            + (" (preempted)" if interrupted else "")
        )

        if interrupted:
            self.draw_preempt_marker(meta.end, meta.core_id)
            self._owner._metrics.append(f"[Preempt] {meta.segment_key} at t={meta.end:.3f}")

        self._owner._segment_resources.pop(segment_key, None)

    def draw_gantt_segment(self, meta: SegmentVisualMeta) -> None:
        y = self._owner._core_lane(meta.core_id)
        color = self._owner._task_color(meta.task_id)
        brush_style = self._owner._subtask_brush_style(meta.task_id, meta.subtask_id)
        pen_style = self._owner._segment_pen_style(meta.segment_id, interrupted=(meta.status == "Preempted"))

        self._owner._ensure_task_legend(meta.task_id, color)
        self._owner._subtask_legend_map[(meta.task_id, meta.subtask_id)] = brush_style_name(brush_style)
        self._owner._segment_legend_map[meta.segment_id] = pen_style_name(pen_style)
        self._owner._refresh_legend_details()

        block = SegmentBlockItem(
            meta=meta,
            y=y,
            lane_height=self._owner._lane_height,
            color=color,
            brush_style=brush_style,
            pen_style=pen_style,
        )
        self._owner._plot.addItem(block)
        self._owner._segment_items.append(block)

        if meta.duration >= self._owner._segment_label_min_duration:
            label = pg.TextItem(text=meta.segment_id, anchor=(0.5, 0.5), color="#f4f4f4")
            label.setZValue(3)
            label.setPos(meta.start + meta.duration / 2.0, y)
            self._owner._plot.addItem(label)
            self._owner._segment_labels.append(label)

        self._owner._plot.setXRange(0, max(1.0, self._owner._max_time * 1.05), padding=0)

    def draw_preempt_marker(self, event_time: float, core_id: str) -> None:
        if core_id not in self._owner._core_to_y:
            return
        y = self._owner._core_to_y[core_id]
        marker = pg.ScatterPlotItem(
            x=[event_time],
            y=[y],
            symbol="x",
            size=12,
            pen=pg.mkPen(color="#ffd54f", width=2),
            brush=pg.mkBrush("#ffd54f"),
        )
        marker.setZValue(4)
        self._owner._plot.addItem(marker)
