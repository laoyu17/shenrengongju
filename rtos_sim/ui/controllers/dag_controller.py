"""Controller for DAG editing interactions in the UI form."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QBrush, QColor, QPen
from PyQt6.QtWidgets import QGraphicsLineItem, QListWidgetItem

from rtos_sim.ui.config_doc import ConfigDocument
from rtos_sim.ui.dag_layout import compute_auto_layout_positions
from rtos_sim.ui.panel_state import (
    DagBatchOperationEntry,
    DagMultiSelectState,
    DagOverviewCanvasEntry,
    DagOverviewTaskEntry,
)

if TYPE_CHECKING:
    from rtos_sim.ui.app import MainWindow


class DagController:
    """Keep DAG edit behavior stable while reducing MainWindow method size."""

    def __init__(self, owner: MainWindow) -> None:
        self._owner = owner
        self._batch_move_in_progress = False

    def select_task(self, task_index: int, *, sync_table_selection: bool) -> bool:
        doc = self._owner._ensure_config_doc()
        tasks = doc.list_tasks()
        if not tasks:
            self._owner._selected_task_index = -1
            self._owner._selected_subtask_id = "s0"
            self._sync_single_selection_state(None)
            self.refresh_dag_widgets(doc)
            return False

        normalized_index = min(max(int(task_index), 0), len(tasks) - 1)
        task_changed = normalized_index != self._owner._selected_task_index
        self._owner._selected_task_index = normalized_index

        subtasks = doc.list_subtasks(normalized_index)
        first_subtask_id = next(
            (str(subtask.get("id") or "").strip() for subtask in subtasks if str(subtask.get("id") or "").strip()),
            None,
        )
        if task_changed:
            if first_subtask_id:
                self._owner._selected_subtask_id = first_subtask_id
                self._sync_single_selection_state(first_subtask_id)
            else:
                self._owner._selected_subtask_id = "s0"
                self._sync_single_selection_state(None)

        if sync_table_selection:
            self._owner._task_table.blockSignals(True)
            try:
                self._owner._task_table.selectRow(normalized_index)
            finally:
                self._owner._task_table.blockSignals(False)

        self._owner._suspend_form_events = True
        try:
            self._owner._refresh_selected_task_fields(doc)
        finally:
            self._owner._suspend_form_events = False
        self.refresh_dag_widgets(doc)
        return True

    def on_dag_subtask_selected(self) -> None:
        if self._owner._suspend_form_events:
            return
        item = self._owner._dag_subtasks_list.currentItem()
        if item is None:
            return
        selected = item.text().strip()
        if selected:
            self.on_dag_node_clicked(selected)

    def on_dag_add_subtask(self) -> None:
        doc = self._owner._ensure_config_doc()
        if self._owner._selected_task_index < 0:
            self._owner._selected_task_index = doc.add_task()
        new_index = doc.add_subtask(
            self._owner._selected_task_index,
            self._owner._dag_new_subtask_id.text().strip() or None,
        )
        new_subtask = doc.get_subtask(self._owner._selected_task_index, new_index)
        self._owner._selected_subtask_id = str(new_subtask.get("id") or "s0")
        self._sync_single_selection_state(self._owner._selected_subtask_id)
        self._owner._dag_new_subtask_id.clear()
        self._owner._populate_form_from_doc()
        self._owner._refresh_dag_node_selection_visuals()
        self._set_overview_canvas_entry(self._build_overview_canvas_entry(doc))
        if self._owner._dag_persist_layout.isChecked():
            self._owner._persist_current_dag_layout_to_doc()
        self._owner._mark_form_dirty()

    def on_dag_remove_subtask(self) -> None:
        doc = self._owner._ensure_config_doc()
        if self._owner._selected_task_index < 0:
            return
        subtasks = doc.list_subtasks(self._owner._selected_task_index)
        if not subtasks:
            return

        subtask_ids = [str(subtask.get("id") or "") for subtask in subtasks if str(subtask.get("id") or "")]
        selected_ids = self._selected_subtask_ids_for_task(doc, allowed=subtask_ids)
        item = self._owner._dag_subtasks_list.currentItem()
        current_row_ids = self._normalize_selected_subtask_ids(
            [item.text().strip()] if item is not None else (),
            allowed=subtask_ids,
        )
        if len(selected_ids) <= 1 and current_row_ids:
            selected_ids = current_row_ids
        if not selected_ids:
            selected_ids = self._normalize_selected_subtask_ids(
                [self._owner._selected_subtask_id],
                allowed=subtask_ids,
            )
        if not selected_ids:
            return

        removal_indices = [idx for idx, subtask_id in enumerate(subtask_ids) if subtask_id in set(selected_ids)]
        if not removal_indices:
            return

        self.open_batch_operation("delete-selected", selected_subtask_ids=selected_ids)
        if len(selected_ids) == 1:
            remaining_after_removal = [
                subtask_id for idx, subtask_id in enumerate(subtask_ids) if idx not in set(removal_indices)
            ]
            next_selected_id = remaining_after_removal[0] if remaining_after_removal else None
        else:
            next_selected_id = self._next_selected_after_removal(subtask_ids, removal_indices)
        for target_index in reversed(removal_indices):
            doc.remove_subtask(self._owner._selected_task_index, target_index)
        self._prune_manual_positions(selected_ids)

        if next_selected_id:
            self._owner._selected_subtask_id = next_selected_id
            self._sync_single_selection_state(next_selected_id)
        else:
            self._owner._selected_subtask_id = "s0"
            self._sync_single_selection_state(None)
        self._owner._populate_form_from_doc()
        self._owner._refresh_dag_node_selection_visuals()
        self._set_overview_canvas_entry(self._build_overview_canvas_entry(doc))
        if self._owner._dag_persist_layout.isChecked():
            self._owner._persist_current_dag_layout_to_doc()
        self._owner._mark_form_dirty()

    def on_dag_add_edge(self) -> None:
        src_id = self._owner._dag_edge_src.text().strip()
        dst_id = self._owner._dag_edge_dst.text().strip()
        if not src_id:
            src_id = self._owner._selected_subtask_id
        self.try_add_dag_edge(src_id, dst_id, show_feedback=True)
        self._owner._dag_edge_src.clear()
        self._owner._dag_edge_dst.clear()

    def on_dag_remove_edge(self) -> None:
        doc = self._owner._ensure_config_doc()
        if self._owner._selected_task_index < 0:
            return
        item = self._owner._dag_edges_list.currentItem()
        if item is None:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(data, tuple) or len(data) != 2:
            return
        src_id, dst_id = data
        doc.remove_edge(self._owner._selected_task_index, str(src_id), str(dst_id))
        self._owner._populate_form_from_doc()
        self._owner._refresh_dag_node_selection_visuals()
        self._set_overview_canvas_entry(self._build_overview_canvas_entry(doc))
        if self._owner._dag_persist_layout.isChecked():
            self._owner._persist_current_dag_layout_to_doc()
        self._owner._mark_form_dirty()

    def on_dag_node_clicked(
        self,
        subtask_id: str,
        *,
        toggle: bool = False,
        preserve_existing: bool = False,
    ) -> None:
        if not subtask_id:
            return
        doc = self._owner._ensure_config_doc()
        available_ids = self._available_subtask_ids(doc)
        if subtask_id not in available_ids:
            return

        current_state = self.get_multi_select_state()
        selected_ids = self._normalize_selected_subtask_ids(
            current_state.selected_subtask_ids,
            allowed=available_ids,
        )
        focus_subtask_id = subtask_id

        if toggle:
            if subtask_id in selected_ids:
                if len(selected_ids) > 1:
                    selected_ids = [item for item in selected_ids if item != subtask_id]
                    focus_subtask_id = (
                        self._owner._selected_subtask_id
                        if self._owner._selected_subtask_id in selected_ids
                        else selected_ids[-1]
                    )
                else:
                    focus_subtask_id = subtask_id
            else:
                selected_ids.append(subtask_id)
        elif preserve_existing and subtask_id in selected_ids:
            focus_subtask_id = subtask_id
        else:
            selected_ids = [subtask_id]

        anchor_subtask_id = current_state.anchor_subtask_id
        if anchor_subtask_id not in selected_ids:
            anchor_subtask_id = selected_ids[0] if selected_ids else None
        self._set_multi_selection_state(
            selected_ids,
            focus_subtask_id=focus_subtask_id,
            anchor_subtask_id=anchor_subtask_id,
            allowed=available_ids,
        )

        self._owner._dag_subtasks_list.blockSignals(True)
        try:
            for idx in range(self._owner._dag_subtasks_list.count()):
                item = self._owner._dag_subtasks_list.item(idx)
                if item is not None and item.text().strip() == subtask_id:
                    self._owner._dag_subtasks_list.setCurrentRow(idx)
                    break
        finally:
            self._owner._dag_subtasks_list.blockSignals(False)

        self._owner._suspend_form_events = True
        try:
            self._owner._refresh_selected_task_fields(doc)
        finally:
            self._owner._suspend_form_events = False
        self._owner._refresh_dag_node_selection_visuals()
        self._set_overview_canvas_entry(self._build_overview_canvas_entry(doc))

    def on_dag_node_moved(self, subtask_id: str, center: QPointF) -> None:
        if not subtask_id:
            return
        previous_center = self._owner._dag_node_centers.get(subtask_id)
        normalized_center = QPointF(center.x(), center.y())
        self._apply_node_center(subtask_id, normalized_center)

        selected_ids = self._selected_subtask_ids_for_task()
        if (
            not self._batch_move_in_progress
            and len(selected_ids) > 1
            and subtask_id in selected_ids
            and previous_center is not None
        ):
            delta_x = normalized_center.x() - previous_center.x()
            delta_y = normalized_center.y() - previous_center.y()
            if delta_x or delta_y:
                node_items = getattr(self._owner, "_dag_node_items", {})
                self._batch_move_in_progress = True
                try:
                    for peer_id in selected_ids:
                        if peer_id == subtask_id:
                            continue
                        peer_center = self._owner._dag_node_centers.get(peer_id)
                        if peer_center is None:
                            continue
                        target_center = QPointF(peer_center.x() + delta_x, peer_center.y() + delta_y)
                        self._apply_node_center(peer_id, target_center)
                        peer_item = node_items.get(peer_id) if isinstance(node_items, dict) else None
                        if peer_item is not None:
                            peer_item.setPos(target_center)
                finally:
                    self._batch_move_in_progress = False

        self._owner._dag_view.setSceneRect(
            self._owner._dag_scene.itemsBoundingRect().adjusted(-30, -30, 30, 30)
        )

        doc = self._owner._ensure_config_doc()
        self._set_overview_canvas_entry(self._build_overview_canvas_entry(doc))

    def on_dag_node_drag_finished(self, subtask_id: str) -> None:
        if not subtask_id:
            return
        selected_ids = self._selected_subtask_ids_for_task()
        if len(selected_ids) > 1 and subtask_id in selected_ids:
            for selected_subtask_id in selected_ids:
                self._owner._update_dag_edges_for_node(selected_subtask_id)
            self.open_batch_operation("move-selected", selected_subtask_ids=selected_ids)
        else:
            self._owner._update_dag_edges_for_node(subtask_id)
        if self._owner._dag_persist_layout.isChecked():
            self._owner._persist_current_dag_layout_to_doc()

    def on_dag_auto_layout(self) -> None:
        doc = self._owner._ensure_config_doc()
        if self._owner._selected_task_index < 0 or not doc.list_tasks():
            return
        subtasks = doc.list_subtasks(self._owner._selected_task_index)
        subtask_ids = [str(subtask.get("id") or "") for subtask in subtasks if str(subtask.get("id") or "")]
        edges = doc.list_edges(self._owner._selected_task_index)
        layout_key = self._owner._current_task_layout_key(doc)
        auto_positions = self._owner._compute_auto_layout_positions(subtask_ids, edges)
        if layout_key:
            self._owner._dag_manual_positions_by_task[layout_key] = {
                sub_id: QPointF(pos.x(), pos.y()) for sub_id, pos in auto_positions.items()
            }
        self._owner._render_dag_scene(subtask_ids, edges, positions=auto_positions)
        self._owner._refresh_dag_node_selection_visuals()
        self._set_overview_canvas_entry(self._build_overview_canvas_entry(doc, subtask_ids=subtask_ids, edges=edges))
        self._owner._form_hint.setText("DAG auto-layout applied.")
        if self._owner._dag_persist_layout.isChecked():
            self._owner._persist_current_dag_layout_to_doc()

    def on_dag_persist_layout_toggled(self, checked: bool) -> None:
        if checked:
            self._owner._persist_current_dag_layout_to_doc()
        else:
            self._owner._form_hint.setText("DAG layout persistence disabled.")

    def refresh_dag_widgets(self, doc: ConfigDocument) -> None:
        if self._owner._selected_task_index < 0 or not doc.list_tasks():
            self.clear_dag_drag_preview()
            self._owner._dag_scene.clear()
            self._owner._dag_subtasks_list.clear()
            self._owner._dag_edges_list.clear()
            self._owner._dag_node_centers.clear()
            self._owner._dag_node_items.clear()
            self._owner._dag_edge_items.clear()
            self._owner._dag_auto_layout_button.setEnabled(False)
            self._sync_single_selection_state(None)
            self._set_overview_canvas_entry(None)
            return

        subtasks = doc.list_subtasks(self._owner._selected_task_index)
        subtask_ids = [str(subtask.get("id") or "") for subtask in subtasks if str(subtask.get("id") or "")]
        edges = doc.list_edges(self._owner._selected_task_index)

        selected_ids = self._selected_subtask_ids_for_task(doc, allowed=subtask_ids)
        if not subtask_ids:
            self._owner._selected_subtask_id = "s0"
            self._sync_single_selection_state(None)
        else:
            focus_subtask_id = self._owner._selected_subtask_id
            if focus_subtask_id not in subtask_ids:
                focus_subtask_id = selected_ids[-1] if selected_ids else subtask_ids[0]
            if selected_ids:
                self._set_multi_selection_state(
                    selected_ids,
                    focus_subtask_id=focus_subtask_id,
                    anchor_subtask_id=self.get_multi_select_state().anchor_subtask_id,
                    allowed=subtask_ids,
                )
            else:
                self._owner._selected_subtask_id = focus_subtask_id
                self._sync_single_selection_state(focus_subtask_id)

        self._owner._dag_subtasks_list.blockSignals(True)
        self._owner._dag_edges_list.blockSignals(True)
        try:
            self._owner._dag_subtasks_list.clear()
            for sub_id in subtask_ids:
                self._owner._dag_subtasks_list.addItem(sub_id)

            self._owner._dag_edges_list.clear()
            for src_id, dst_id in edges:
                item = QListWidgetItem(f"{src_id} -> {dst_id}")
                item.setData(Qt.ItemDataRole.UserRole, (src_id, dst_id))
                self._owner._dag_edges_list.addItem(item)

            for idx, sub_id in enumerate(subtask_ids):
                if sub_id == self._owner._selected_subtask_id:
                    self._owner._dag_subtasks_list.setCurrentRow(idx)
                    break
        finally:
            self._owner._dag_subtasks_list.blockSignals(False)
            self._owner._dag_edges_list.blockSignals(False)

        self._owner._dag_remove_subtask_button.setEnabled(bool(subtask_ids))
        self._owner._dag_remove_edge_button.setEnabled(bool(edges))
        self._owner._dag_auto_layout_button.setEnabled(bool(subtask_ids))
        layout_key = self._owner._current_task_layout_key(doc)
        positions = self.resolve_dag_positions(doc, layout_key, subtask_ids, edges)
        self.render_dag_scene(subtask_ids, edges, positions=positions)
        self._set_overview_canvas_entry(self._build_overview_canvas_entry(doc, subtask_ids=subtask_ids, edges=edges))

    def resolve_dag_positions(
        self,
        doc: ConfigDocument,
        layout_key: str,
        subtask_ids: list[str],
        edges: list[tuple[str, str]],
    ) -> dict[str, QPointF]:
        return self.resolve_task_positions(
            doc,
            task_index=self._owner._selected_task_index,
            layout_key=layout_key,
            subtask_ids=subtask_ids,
            edges=edges,
        )

    def resolve_task_positions(
        self,
        doc: ConfigDocument,
        *,
        task_index: int,
        layout_key: str,
        subtask_ids: list[str],
        edges: list[tuple[str, str]],
    ) -> dict[str, QPointF]:
        auto_layout = getattr(self._owner, "_compute_auto_layout_positions", None)
        if callable(auto_layout):
            auto_positions = auto_layout(subtask_ids, edges)
        else:
            auto_positions = self.compute_auto_layout_positions(subtask_ids, edges)
        if not layout_key:
            return auto_positions

        manual_positions_by_task = getattr(self._owner, "_dag_manual_positions_by_task", None)
        if not isinstance(manual_positions_by_task, dict):
            manual_positions_by_task = {}
            setattr(self._owner, "_dag_manual_positions_by_task", manual_positions_by_task)

        task_positions = manual_positions_by_task.get(layout_key)
        if task_positions is None:
            getter = getattr(doc, "get_task_node_layout", None)
            saved_positions = getter(layout_key) if callable(getter) else {}
            if saved_positions:
                task_positions = {
                    sub_id: QPointF(float(xy[0]), float(xy[1]))
                    for sub_id, xy in saved_positions.items()
                }
                manual_positions_by_task[layout_key] = task_positions

        result: dict[str, QPointF] = {}
        for sub_id in subtask_ids:
            manual = task_positions.get(sub_id) if task_positions else None
            if manual is not None:
                result[sub_id] = QPointF(manual.x(), manual.y())
            else:
                result[sub_id] = auto_positions.get(sub_id, QPointF(80.0, 80.0))

        if task_positions is not None:
            manual_positions_by_task[layout_key] = {
                sub_id: QPointF(pos.x(), pos.y()) for sub_id, pos in result.items()
            }
        return result

    @staticmethod
    def compute_auto_layout_positions(
        subtask_ids: list[str],
        edges: list[tuple[str, str]],
    ) -> dict[str, QPointF]:
        raw_positions = compute_auto_layout_positions(subtask_ids, edges)
        return {sub_id: QPointF(pos[0], pos[1]) for sub_id, pos in raw_positions.items()}

    def render_dag_scene(
        self,
        subtask_ids: list[str],
        edges: list[tuple[str, str]],
        *,
        positions: dict[str, QPointF],
    ) -> None:
        from rtos_sim.ui.app import DagNodeItem

        self.clear_dag_drag_preview()
        self._owner._dag_scene.clear()
        self._owner._dag_node_centers = {}
        self._owner._dag_node_items = {}
        self._owner._dag_edge_items = {}
        if not subtask_ids:
            self._owner._dag_scene.addText("No subtask in selected task")
            return

        node_radius = 22.0
        self._owner._dag_node_centers = {
            sub_id: QPointF(
                positions.get(sub_id, QPointF(80.0, 80.0)).x(),
                positions.get(sub_id, QPointF(80.0, 80.0)).y(),
            )
            for sub_id in subtask_ids
        }

        edge_pen = QPen(QColor("#8ea6b8"))
        edge_pen.setWidth(2)
        for src_id, dst_id in edges:
            src = self._owner._dag_node_centers.get(src_id)
            dst = self._owner._dag_node_centers.get(dst_id)
            if src is None or dst is None:
                continue
            line = QGraphicsLineItem(src.x(), src.y(), dst.x(), dst.y())
            line.setPen(edge_pen)
            line.setZValue(1)
            self._owner._dag_scene.addItem(line)
            self._owner._dag_edge_items[(src_id, dst_id)] = line

        selected_ids = set(self._selected_subtask_ids_for_task(allowed=subtask_ids))
        for sub_id in subtask_ids:
            center = self._owner._dag_node_centers[sub_id]
            node_item = DagNodeItem(
                owner=self._owner,
                subtask_id=sub_id,
                center=center,
                radius=node_radius,
                selected=sub_id in selected_ids,
            )
            self._owner._dag_scene.addItem(node_item)
            self._owner._dag_node_items[sub_id] = node_item

            label_item = self._owner._dag_scene.addText(sub_id)
            label_item.setParentItem(node_item)
            rect = label_item.boundingRect()
            label_item.setPos(-rect.width() / 2.0, -rect.height() / 2.0)
            label_item.setDefaultTextColor(QColor("#f5f7fa"))
            label_item.setZValue(3)

        self._owner._dag_view.setSceneRect(
            self._owner._dag_scene.itemsBoundingRect().adjusted(-30, -30, 30, 30)
        )

    def start_dag_link_drag(self, src_id: str, scene_pos: QPointF) -> None:
        self.clear_dag_drag_preview()
        self._owner._dag_drag_source_id = src_id
        line = QGraphicsLineItem(scene_pos.x(), scene_pos.y(), scene_pos.x(), scene_pos.y())
        pen = QPen(QColor("#f8d26a"))
        pen.setStyle(Qt.PenStyle.DashLine)
        pen.setWidth(2)
        line.setPen(pen)
        line.setZValue(4)
        self._owner._dag_scene.addItem(line)
        self._owner._dag_drag_line = line

    def update_dag_link_drag(self, scene_pos: QPointF) -> None:
        line = self._owner._dag_drag_line
        if line is None:
            return
        segment = line.line()
        line.setLine(segment.x1(), segment.y1(), scene_pos.x(), scene_pos.y())

    def finish_dag_link_drag(self, scene_pos: QPointF) -> None:
        src_id = self._owner._dag_drag_source_id
        dst_id = self.dag_node_id_from_scene_pos(scene_pos)
        self.clear_dag_drag_preview()
        if src_id is None or dst_id is None:
            return
        self._owner._try_add_dag_edge(src_id, dst_id, show_feedback=True)

    def clear_dag_drag_preview(self) -> None:
        if self._owner._dag_drag_line is not None:
            try:
                self._owner._dag_scene.removeItem(self._owner._dag_drag_line)
            except RuntimeError as exc:
                try:
                    from rtos_sim.ui.app import _log_ui_error
                except ImportError:
                    _log_ui_error = None
                if _log_ui_error is not None:
                    _log_ui_error("dag_drag_preview_remove", exc)
        self._owner._dag_drag_line = None
        self._owner._dag_drag_source_id = None

    def dag_node_id_from_scene_pos(self, scene_pos: QPointF) -> str | None:
        from rtos_sim.ui.app import DagNodeItem

        for item in self._owner._dag_scene.items(scene_pos):
            if isinstance(item, DagNodeItem):
                return item.subtask_id
        nearest_id: str | None = None
        nearest_distance = float("inf")
        for sub_id, center in self._owner._dag_node_centers.items():
            dx = center.x() - scene_pos.x()
            dy = center.y() - scene_pos.y()
            distance = dx * dx + dy * dy
            if distance < nearest_distance:
                nearest_distance = distance
                nearest_id = sub_id
        if nearest_id is not None and nearest_distance <= 28.0 * 28.0:
            return nearest_id
        return None

    def dag_scene_pos_for_subtask(self, subtask_id: str) -> QPointF | None:
        center = self._owner._dag_node_centers.get(subtask_id)
        if center is None:
            return None
        return QPointF(center.x(), center.y())

    def refresh_dag_node_selection_visuals(self) -> None:
        selected_ids = set(self._selected_subtask_ids_for_task())
        focus_subtask_id = self._owner._selected_subtask_id
        for sub_id, node_item in self._owner._dag_node_items.items():
            if sub_id == focus_subtask_id and sub_id in selected_ids:
                color = "#2d7ff9"
            elif sub_id in selected_ids:
                color = "#6aaeff"
            else:
                color = "#47617a"
            node_item.setBrush(QBrush(QColor(color)))

    def update_dag_edges_for_node(self, subtask_id: str) -> None:
        center = self._owner._dag_node_centers.get(subtask_id)
        if center is None:
            return
        for (src_id, dst_id), line in self._owner._dag_edge_items.items():
            current = line.line()
            if src_id == subtask_id:
                line.setLine(center.x(), center.y(), current.x2(), current.y2())
            elif dst_id == subtask_id:
                line.setLine(current.x1(), current.y1(), center.x(), center.y())

    def persist_current_dag_layout_to_doc(self) -> None:
        doc = self._owner._ensure_config_doc()
        layout_key = self._owner._current_task_layout_key(doc)
        if not layout_key:
            return
        positions = {
            sub_id: (center.x(), center.y())
            for sub_id, center in self._owner._dag_node_centers.items()
        }
        doc.set_task_node_layout(layout_key, positions)
        self._owner._mark_form_dirty()
        self._owner._form_hint.setText("DAG layout changed. Apply Form -> Text to persist ui_layout.")
        self._set_overview_canvas_entry(self._build_overview_canvas_entry(doc))

    def get_multi_select_state(self) -> DagMultiSelectState:
        state = getattr(self._owner, "_dag_multi_select_state", None)
        if isinstance(state, DagMultiSelectState):
            if not state.selected_subtask_ids and self._owner._selected_subtask_id:
                self._sync_single_selection_state(self._owner._selected_subtask_id)
            return state
        selected = self._normalize_selected_subtask_ids([self._owner._selected_subtask_id])
        focus = selected[0] if selected else None
        return DagMultiSelectState(
            selected_subtask_ids=list(selected),
            anchor_subtask_id=focus,
            focus_subtask_id=focus,
        )

    def open_batch_operation(
        self,
        action_id: str,
        *,
        selected_subtask_ids: Sequence[str] | None = None,
    ) -> DagBatchOperationEntry | None:
        normalized_action = action_id.strip()
        if not normalized_action:
            return None
        doc = self._owner._ensure_config_doc()
        tasks = doc.list_tasks()
        if self._owner._selected_task_index < 0 or not tasks:
            return None
        task_index = min(self._owner._selected_task_index, len(tasks) - 1)
        available_ids = [
            str(subtask.get("id") or "")
            for subtask in doc.list_subtasks(task_index)
            if str(subtask.get("id") or "")
        ]
        selected = self._normalize_selected_subtask_ids(
            selected_subtask_ids or self.get_multi_select_state().selected_subtask_ids,
            allowed=available_ids,
        )
        request = DagBatchOperationEntry(
            action_id=normalized_action,
            task_index=task_index,
            selected_subtask_ids=tuple(selected),
            focus_subtask_id=self._owner._selected_subtask_id or None,
        )
        self._set_last_batch_operation(request)
        return request

    def get_overview_canvas_entry(self) -> DagOverviewCanvasEntry | None:
        doc = self._owner._ensure_config_doc()
        entry = self._build_overview_canvas_entry(doc)
        self._set_overview_canvas_entry(entry)
        return entry

    def try_add_dag_edge(self, src_id: str, dst_id: str, *, show_feedback: bool) -> bool:
        doc = self._owner._ensure_config_doc()
        if self._owner._selected_task_index < 0:
            self._owner._form_hint.setText("DAG edge rejected: no selected task.")
            return False

        src = src_id.strip()
        dst = dst_id.strip()
        if not src or not dst:
            self._owner._form_hint.setText("DAG edge rejected: src/dst can not be empty.")
            return False
        if src == dst:
            self._owner._form_hint.setText("DAG edge rejected: self-loop is not allowed.")
            return False

        subtask_ids = {
            str(subtask.get("id") or "")
            for subtask in doc.list_subtasks(self._owner._selected_task_index)
            if str(subtask.get("id") or "")
        }
        if src not in subtask_ids or dst not in subtask_ids:
            self._owner._form_hint.setText("DAG edge rejected: src/dst node does not exist.")
            return False

        if (src, dst) in set(doc.list_edges(self._owner._selected_task_index)):
            self._owner._form_hint.setText(f"DAG edge ignored: {src}->{dst} already exists.")
            return False

        if self.would_create_cycle(doc, self._owner._selected_task_index, src, dst):
            self._owner._form_hint.setText(f"DAG edge rejected: {src}->{dst} creates a cycle.")
            return False

        doc.add_edge(self._owner._selected_task_index, src, dst)
        self._owner._populate_form_from_doc()
        self._owner._refresh_dag_node_selection_visuals()
        self._set_overview_canvas_entry(self._build_overview_canvas_entry(doc))
        self._owner._mark_form_dirty()
        if show_feedback:
            self._owner._form_hint.setText(f"DAG edge added: {src}->{dst}")
        return True

    @staticmethod
    def would_create_cycle(doc: ConfigDocument, task_index: int, src_id: str, dst_id: str) -> bool:
        adjacency: dict[str, set[str]] = {}
        for src, dst in doc.list_edges(task_index):
            adjacency.setdefault(src, set()).add(dst)
        adjacency.setdefault(src_id, set()).add(dst_id)

        stack = [dst_id]
        visited: set[str] = set()
        while stack:
            node = stack.pop()
            if node == src_id:
                return True
            if node in visited:
                continue
            visited.add(node)
            for nxt in adjacency.get(node, set()):
                if nxt not in visited:
                    stack.append(nxt)
        return False

    def _sync_single_selection_state(self, subtask_id: str | None) -> None:
        self._set_multi_selection_state(
            [subtask_id] if subtask_id else (),
            focus_subtask_id=subtask_id,
            anchor_subtask_id=subtask_id,
        )

    def _set_multi_selection_state(
        self,
        subtask_ids: Sequence[str] | None,
        *,
        focus_subtask_id: str | None,
        anchor_subtask_id: str | None = None,
        allowed: Sequence[str] | None = None,
    ) -> None:
        state = getattr(self._owner, "_dag_multi_select_state", None)
        normalized = self._normalize_selected_subtask_ids(subtask_ids, allowed=allowed)
        focus = str(focus_subtask_id).strip() if focus_subtask_id else None
        if focus not in normalized:
            focus = normalized[-1] if normalized else None
        anchor = str(anchor_subtask_id).strip() if anchor_subtask_id else None
        if anchor not in normalized:
            anchor = normalized[0] if normalized else None
        if isinstance(state, DagMultiSelectState):
            state.selected_subtask_ids = list(normalized)
            state.anchor_subtask_id = anchor
            state.focus_subtask_id = focus
        if focus is not None:
            self._owner._selected_subtask_id = focus

    def _apply_node_center(self, subtask_id: str, center: QPointF) -> None:
        self._owner._dag_node_centers[subtask_id] = QPointF(center.x(), center.y())
        self._owner._update_dag_edges_for_node(subtask_id)

        doc = self._owner._ensure_config_doc()
        layout_key = self._owner._current_task_layout_key(doc)
        if layout_key:
            task_positions = self._owner._dag_manual_positions_by_task.setdefault(layout_key, {})
            task_positions[subtask_id] = QPointF(center.x(), center.y())

    def _available_subtask_ids(self, doc: ConfigDocument) -> list[str]:
        tasks = doc.list_tasks()
        if self._owner._selected_task_index < 0 or not tasks:
            return []
        task_index = min(self._owner._selected_task_index, len(tasks) - 1)
        return [
            str(subtask.get("id") or "")
            for subtask in doc.list_subtasks(task_index)
            if str(subtask.get("id") or "")
        ]

    def _selected_subtask_ids_for_task(
        self,
        doc: ConfigDocument | None = None,
        *,
        allowed: Sequence[str] | None = None,
    ) -> list[str]:
        doc = doc or self._owner._ensure_config_doc()
        return self._normalize_selected_subtask_ids(
            self.get_multi_select_state().selected_subtask_ids,
            allowed=allowed if allowed is not None else self._available_subtask_ids(doc),
        )

    @staticmethod
    def _next_selected_after_removal(subtask_ids: Sequence[str], removal_indices: Sequence[int]) -> str | None:
        if not subtask_ids or not removal_indices:
            return None
        removed = set(removal_indices)
        remaining_ids = [subtask_id for idx, subtask_id in enumerate(subtask_ids) if idx not in removed]
        if not remaining_ids:
            return None
        next_index = min(removal_indices)
        if next_index >= len(remaining_ids):
            next_index = len(remaining_ids) - 1
        return remaining_ids[next_index]

    def _prune_manual_positions(self, removed_subtask_ids: Sequence[str]) -> None:
        removed = set(self._normalize_selected_subtask_ids(removed_subtask_ids))
        if not removed:
            return
        doc = self._owner._ensure_config_doc()
        layout_key = self._owner._current_task_layout_key(doc)
        if not layout_key:
            return
        task_positions = self._owner._dag_manual_positions_by_task.get(layout_key)
        if not task_positions:
            return
        self._owner._dag_manual_positions_by_task[layout_key] = {
            subtask_id: center
            for subtask_id, center in task_positions.items()
            if subtask_id not in removed
        }

    def _set_last_batch_operation(self, entry: DagBatchOperationEntry | None) -> None:
        if hasattr(self._owner, "_dag_last_batch_operation"):
            self._owner._dag_last_batch_operation = entry
        else:
            setattr(self._owner, "_dag_last_batch_operation", entry)

    def _set_overview_canvas_entry(self, entry: DagOverviewCanvasEntry | None) -> None:
        if hasattr(self._owner, "_dag_overview_canvas_entry"):
            self._owner._dag_overview_canvas_entry = entry
        else:
            setattr(self._owner, "_dag_overview_canvas_entry", entry)
        refresh = getattr(self._owner, "_refresh_dag_overview_canvas", None)
        if callable(refresh):
            refresh(entry)

    def _build_overview_canvas_entry(
        self,
        doc: ConfigDocument,
        *,
        subtask_ids: list[str] | None = None,
        edges: list[tuple[str, str]] | None = None,
    ) -> DagOverviewCanvasEntry | None:
        tasks = doc.list_tasks()
        if self._owner._selected_task_index < 0 or not tasks:
            return None
        task_index = min(self._owner._selected_task_index, len(tasks) - 1)
        task = doc.get_task(task_index)
        task_id = str(task.get("id") or "").strip() or f"task_{task_index}"
        if subtask_ids is None:
            subtask_ids = [
                str(subtask.get("id") or "")
                for subtask in doc.list_subtasks(task_index)
                if str(subtask.get("id") or "")
            ]
        if edges is None:
            edges = list(doc.list_edges(task_index))
        selected = self._normalize_selected_subtask_ids(
            self.get_multi_select_state().selected_subtask_ids,
            allowed=subtask_ids,
        )
        task_entries: list[DagOverviewTaskEntry] = []
        for overview_task_index, task_view in enumerate(tasks):
            task_payload = task_view.task if hasattr(task_view, "task") else task_view
            current_task_id = str(task_payload.get("id") or "").strip() or f"task_{overview_task_index}"
            overview_subtask_ids = [
                str(subtask.get("id") or "")
                for subtask in doc.list_subtasks(overview_task_index)
                if str(subtask.get("id") or "")
            ]
            overview_edges = list(doc.list_edges(overview_task_index))
            overview_selected = selected if overview_task_index == task_index else []
            overview_positions = self.resolve_task_positions(
                doc,
                task_index=overview_task_index,
                layout_key=self._task_layout_key(doc, overview_task_index),
                subtask_ids=overview_subtask_ids,
                edges=overview_edges,
            )
            task_entries.append(
                DagOverviewTaskEntry(
                    task_index=overview_task_index,
                    task_id=current_task_id,
                    task_name=str(task_payload.get("name") or "").strip(),
                    task_type=str(task_payload.get("task_type") or "").strip(),
                    subtask_count=len(overview_subtask_ids),
                    edge_count=len(overview_edges),
                    selected_subtask_ids=tuple(overview_selected),
                    subtask_ids=tuple(overview_subtask_ids),
                    edges=tuple((str(src), str(dst)) for src, dst in overview_edges),
                    node_positions=tuple(
                        (sub_id, (float(pos.x()), float(pos.y())))
                        for sub_id, pos in overview_positions.items()
                    ),
                )
            )
        return DagOverviewCanvasEntry(
            task_index=task_index,
            task_id=task_id,
            selected_subtask_ids=tuple(selected),
            subtask_ids=tuple(subtask_ids),
            edges=tuple((str(src), str(dst)) for src, dst in edges),
            tasks=tuple(task_entries),
        )

    def _task_layout_key(self, doc: ConfigDocument, task_index: int) -> str:
        tasks = doc.list_tasks()
        if task_index < 0 or task_index >= len(tasks):
            return ""
        task_view = tasks[task_index]
        task_payload = task_view.task if hasattr(task_view, "task") else task_view
        task_id = str(task_payload.get("id") or "").strip()
        if task_id:
            return task_id
        return f"task_{task_index}"

    @staticmethod
    def _normalize_selected_subtask_ids(
        subtask_ids: Sequence[str] | None,
        *,
        allowed: Sequence[str] | None = None,
    ) -> list[str]:
        allowed_set = {item for item in allowed or () if item}
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in subtask_ids or ():
            subtask_id = str(raw).strip()
            if not subtask_id or subtask_id in seen:
                continue
            if allowed_set and subtask_id not in allowed_set:
                continue
            normalized.append(subtask_id)
            seen.add(subtask_id)
        return normalized
