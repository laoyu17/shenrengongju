"""Controller for DAG editing interactions in the UI form."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QPointF, Qt

from rtos_sim.ui.config_doc import ConfigDocument

if TYPE_CHECKING:
    from rtos_sim.ui.app import MainWindow


class DagController:
    """Keep DAG edit behavior stable while reducing MainWindow method size."""

    def __init__(self, owner: MainWindow) -> None:
        self._owner = owner

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
        self._owner._dag_new_subtask_id.clear()
        self._owner._populate_form_from_doc()
        self._owner._refresh_dag_node_selection_visuals()
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

        target_index = 0
        item = self._owner._dag_subtasks_list.currentItem()
        selected_id = item.text().strip() if item is not None else self._owner._selected_subtask_id
        for idx, subtask in enumerate(subtasks):
            if str(subtask.get("id") or "") == selected_id:
                target_index = idx
                break
        doc.remove_subtask(self._owner._selected_task_index, target_index)

        remaining = doc.list_subtasks(self._owner._selected_task_index)
        self._owner._selected_subtask_id = str(remaining[0].get("id") or "s0") if remaining else "s0"
        self._owner._populate_form_from_doc()
        self._owner._refresh_dag_node_selection_visuals()
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
        if self._owner._dag_persist_layout.isChecked():
            self._owner._persist_current_dag_layout_to_doc()
        self._owner._mark_form_dirty()

    def on_dag_node_clicked(self, subtask_id: str) -> None:
        if not subtask_id:
            return
        self._owner._selected_subtask_id = subtask_id

        self._owner._dag_subtasks_list.blockSignals(True)
        try:
            for idx in range(self._owner._dag_subtasks_list.count()):
                item = self._owner._dag_subtasks_list.item(idx)
                if item is not None and item.text().strip() == subtask_id:
                    self._owner._dag_subtasks_list.setCurrentRow(idx)
                    break
        finally:
            self._owner._dag_subtasks_list.blockSignals(False)

        doc = self._owner._ensure_config_doc()
        self._owner._suspend_form_events = True
        try:
            self._owner._refresh_selected_task_fields(doc)
        finally:
            self._owner._suspend_form_events = False
        self._owner._refresh_dag_node_selection_visuals()

    def on_dag_node_moved(self, subtask_id: str, center: QPointF) -> None:
        if not subtask_id:
            return
        self._owner._dag_node_centers[subtask_id] = QPointF(center.x(), center.y())
        self._owner._update_dag_edges_for_node(subtask_id)
        self._owner._dag_view.setSceneRect(self._owner._dag_scene.itemsBoundingRect().adjusted(-30, -30, 30, 30))

        doc = self._owner._ensure_config_doc()
        layout_key = self._owner._current_task_layout_key(doc)
        if layout_key:
            task_positions = self._owner._dag_manual_positions_by_task.setdefault(layout_key, {})
            task_positions[subtask_id] = QPointF(center.x(), center.y())

    def on_dag_node_drag_finished(self, subtask_id: str) -> None:
        if not subtask_id:
            return
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
        self._owner._form_hint.setText("DAG auto-layout applied.")
        if self._owner._dag_persist_layout.isChecked():
            self._owner._persist_current_dag_layout_to_doc()

    def on_dag_persist_layout_toggled(self, checked: bool) -> None:
        if checked:
            self._owner._persist_current_dag_layout_to_doc()
        else:
            self._owner._form_hint.setText("DAG layout persistence disabled.")

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
