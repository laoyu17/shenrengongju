"""Controller for telemetry panel interactions and hover/legend rendering."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QPointF
from PyQt6.QtWidgets import QToolTip

from rtos_sim.ui.gantt_helpers import SegmentBlockItem

if TYPE_CHECKING:
    from rtos_sim.ui.app import MainWindow


class TelemetryController:
    """Encapsulate telemetry panel state transitions and plot interactions."""

    def __init__(self, owner: MainWindow) -> None:
        self._owner = owner

    def append_state_transition(self, *, event_time: float, state: str, label: str) -> None:
        row = f"t={event_time:.3f} [{state}] {label}"
        self._owner._state_transitions.append(row)
        self._owner._state_view.setPlainText("\n".join(self._owner._state_transitions[-256:]))

    def on_plot_mouse_moved(self, scene_pos: QPointF) -> None:
        item = self.segment_item_from_scene(scene_pos)
        if item is None:
            self._owner._hovered_segment_key = None
            QToolTip.hideText()
            if self._owner._locked_segment_key is None:
                self._owner._hover_hint.setText("Hover a segment for details. Click segment to lock/unlock.")
                self._owner._details.clear()
            return

        self._owner._hovered_segment_key = item.meta.segment_key
        self._owner._hover_hint.setText(
            f"Hover: {item.meta.task_id}/{item.meta.subtask_id}/{item.meta.segment_id} "
            f"core={item.meta.core_id} [{item.meta.start:.3f}, {item.meta.end:.3f}]"
        )
        # Wayland requires tooltip popups to have a transient parent.
        view_pos = self._owner._plot.mapFromScene(scene_pos)
        viewport = self._owner._plot.viewport()
        global_pos = viewport.mapToGlobal(view_pos)
        QToolTip.showText(global_pos, item.toolTip(), viewport)

        if self._owner._locked_segment_key is None:
            self._owner._details.setPlainText(self._owner._format_segment_details(item.meta))

    def on_plot_mouse_clicked(self, event: Any) -> None:
        scene_pos = event.scenePos() if hasattr(event, "scenePos") else QPointF()
        item = self.segment_item_from_scene(scene_pos)
        if item is None:
            self._owner._locked_segment_key = None
            if self._owner._hovered_segment_key is None:
                self._owner._details.clear()
            if hasattr(event, "accept"):
                event.accept()
            return

        key = item.meta.segment_key
        if self._owner._locked_segment_key == key:
            self._owner._locked_segment_key = None
        else:
            self._owner._locked_segment_key = key
            self._owner._details.setPlainText(self._owner._format_segment_details(item.meta))

        if hasattr(event, "accept"):
            event.accept()

    def segment_item_from_scene(self, scene_pos: QPointF) -> SegmentBlockItem | None:
        for raw_item in self._owner._plot.scene().items(scene_pos):
            if isinstance(raw_item, SegmentBlockItem):
                return raw_item
            parent = raw_item.parentItem() if hasattr(raw_item, "parentItem") else None
            if isinstance(parent, SegmentBlockItem):
                return parent
        return None

    def refresh_legend_details(self) -> None:
        show_subtask = self._owner._legend_toggle_subtask.isChecked()
        show_segment = self._owner._legend_toggle_segment.isChecked()
        if not show_subtask and not show_segment:
            self._owner._legend_detail.clear()
            self._owner._legend_detail.hide()
            return

        lines: list[str] = []
        if show_subtask:
            lines.append("Subtask Legend (task/subtask -> brush pattern)")
            for (task_id, subtask_id), style_name in sorted(self._owner._subtask_legend_map.items()):
                lines.append(f"- {task_id}/{subtask_id}: {style_name}")

        if show_segment:
            if lines:
                lines.append("")
            lines.append("Segment Legend (segment id -> border style)")
            for segment_id, style_name in sorted(self._owner._segment_legend_map.items()):
                lines.append(f"- {segment_id}: {style_name}")

        self._owner._legend_detail.setPlainText("\n".join(lines))
        self._owner._legend_detail.show()

    def reset_panel_state(self) -> None:
        self._owner._hovered_segment_key = None
        self._owner._locked_segment_key = None
        self._owner._hover_hint.setText("Hover a segment for details. Click segment to lock/unlock.")
        self._owner._details.clear()
        self._owner._state_transitions.clear()
        self._owner._state_view.clear()
        self.refresh_legend_details()
        QToolTip.hideText()
