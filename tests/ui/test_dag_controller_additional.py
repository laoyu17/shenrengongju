from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import QPointF
from PyQt6.QtCore import Qt

from rtos_sim.ui.controllers.dag_controller import DagController


class _LineEdit:
    def __init__(self, value: str = "") -> None:
        self._value = value

    def text(self) -> str:  # noqa: N802
        return self._value

    def setText(self, value: str) -> None:  # noqa: N802
        self._value = value

    def clear(self) -> None:
        self._value = ""


@dataclass
class _Label:
    value: str = ""

    def setText(self, value: str) -> None:  # noqa: N802
        self.value = value


@dataclass
class _CheckBox:
    checked: bool = False

    def isChecked(self) -> bool:  # noqa: N802
        return self.checked

    def setChecked(self, checked: bool) -> None:  # noqa: N802
        self.checked = bool(checked)


class _Rect:
    def adjusted(self, *_args: int) -> "_Rect":
        return self


class _Scene:
    def itemsBoundingRect(self) -> _Rect:  # noqa: N802
        return _Rect()


class _View:
    def __init__(self) -> None:
        self.last_scene_rect: _Rect | None = None

    def setSceneRect(self, rect: _Rect) -> None:  # noqa: N802
        self.last_scene_rect = rect


class _Item:
    def __init__(self, text: str, user_data: object | None = None) -> None:
        self._text = text
        self._user_data = user_data

    def text(self) -> str:  # noqa: N802
        return self._text

    def data(self, _role: Qt.ItemDataRole) -> object | None:  # noqa: N802
        return self._user_data


class _ListWidget:
    def __init__(self, items: list[_Item] | None = None) -> None:
        self._items = list(items or [])
        self._current_row = -1 if not self._items else 0
        self.signal_blocked = False

    def count(self) -> int:  # noqa: N802
        return len(self._items)

    def item(self, index: int) -> _Item | None:  # noqa: N802
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def currentItem(self) -> _Item | None:  # noqa: N802
        return self.item(self._current_row)

    def setCurrentRow(self, index: int) -> None:  # noqa: N802
        self._current_row = index

    def blockSignals(self, blocked: bool) -> None:  # noqa: N802
        self.signal_blocked = bool(blocked)

    def set_items(self, items: list[_Item]) -> None:
        self._items = list(items)
        if self._current_row >= len(self._items):
            self._current_row = len(self._items) - 1


class _Doc:
    def __init__(
        self,
        *,
        subtask_ids: list[str] | None = None,
        edges: list[tuple[str, str]] | None = None,
    ) -> None:
        subtasks = [{"id": sub_id} for sub_id in (subtask_ids or ["s0", "s1"])]
        self._tasks = [{"id": "t0", "subtasks": subtasks, "edges": list(edges or [])}]

    def list_tasks(self) -> list[dict]:
        return self._tasks

    def add_task(self) -> int:
        self._tasks.append({"id": f"t{len(self._tasks)}", "subtasks": [], "edges": []})
        return len(self._tasks) - 1

    def list_subtasks(self, task_index: int) -> list[dict]:
        return list(self._tasks[task_index]["subtasks"])

    def add_subtask(self, task_index: int, subtask_id: str | None) -> int:
        subtasks = self._tasks[task_index]["subtasks"]
        new_id = subtask_id or f"s{len(subtasks)}"
        subtasks.append({"id": new_id})
        return len(subtasks) - 1

    def get_subtask(self, task_index: int, subtask_index: int) -> dict:
        return dict(self._tasks[task_index]["subtasks"][subtask_index])

    def remove_subtask(self, task_index: int, subtask_index: int) -> None:
        subtasks = self._tasks[task_index]["subtasks"]
        removed = subtasks.pop(subtask_index)
        removed_id = str(removed.get("id") or "")
        self._tasks[task_index]["edges"] = [
            (src, dst)
            for src, dst in self._tasks[task_index]["edges"]
            if src != removed_id and dst != removed_id
        ]

    def list_edges(self, task_index: int) -> list[tuple[str, str]]:
        return list(self._tasks[task_index]["edges"])

    def add_edge(self, task_index: int, src_id: str, dst_id: str) -> None:
        self._tasks[task_index]["edges"].append((src_id, dst_id))

    def remove_edge(self, task_index: int, src_id: str, dst_id: str) -> None:
        self._tasks[task_index]["edges"] = [
            pair for pair in self._tasks[task_index]["edges"] if pair != (src_id, dst_id)
        ]


class _Owner:
    def __init__(self, doc: _Doc | None = None) -> None:
        self._doc = doc or _Doc()

        self._selected_task_index = 0
        self._selected_subtask_id = "s0"
        self._suspend_form_events = False

        self._dag_new_subtask_id = _LineEdit()
        self._dag_edge_src = _LineEdit()
        self._dag_edge_dst = _LineEdit()
        self._dag_persist_layout = _CheckBox(False)
        self._form_hint = _Label()

        self._dag_scene = _Scene()
        self._dag_view = _View()
        self._dag_node_centers: dict[str, QPointF] = {}
        self._dag_manual_positions_by_task: dict[str, dict[str, QPointF]] = {}

        self._populate_calls = 0
        self._refresh_calls = 0
        self._persist_calls = 0
        self._dirty_calls = 0
        self._update_edges_calls = 0
        self._refresh_task_calls = 0
        self._render_calls = 0

        self._dag_subtasks_list = _ListWidget()
        self._dag_edges_list = _ListWidget()
        self._sync_lists_from_doc()

    def _sync_lists_from_doc(self) -> None:
        if self._selected_task_index < 0:
            self._dag_subtasks_list.set_items([])
            self._dag_edges_list.set_items([])
            return
        subtasks = self._doc.list_subtasks(self._selected_task_index)
        self._dag_subtasks_list.set_items([_Item(str(sub.get("id") or "")) for sub in subtasks])
        edges = self._doc.list_edges(self._selected_task_index)
        self._dag_edges_list.set_items([_Item(f"{src} -> {dst}", (src, dst)) for src, dst in edges])

    def _ensure_config_doc(self) -> _Doc:
        return self._doc

    def _populate_form_from_doc(self) -> None:
        self._populate_calls += 1
        self._sync_lists_from_doc()

    def _refresh_dag_node_selection_visuals(self) -> None:
        self._refresh_calls += 1

    def _persist_current_dag_layout_to_doc(self) -> None:
        self._persist_calls += 1

    def _mark_form_dirty(self) -> None:
        self._dirty_calls += 1

    def _refresh_selected_task_fields(self, _doc: _Doc) -> None:
        self._refresh_task_calls += 1

    def _update_dag_edges_for_node(self, _subtask_id: str) -> None:
        self._update_edges_calls += 1

    def _current_task_layout_key(self, _doc: _Doc) -> str:
        return "t0"

    def _compute_auto_layout_positions(
        self,
        subtask_ids: list[str],
        _edges: list[tuple[str, str]],
    ) -> dict[str, QPointF]:
        return {sub_id: QPointF(float(idx * 100), 0.0) for idx, sub_id in enumerate(subtask_ids)}

    def _render_dag_scene(
        self,
        _subtask_ids: list[str],
        _edges: list[tuple[str, str]],
        *,
        positions: dict[str, QPointF],
    ) -> None:
        self._render_calls += 1
        self._dag_node_centers = dict(positions)


def test_on_dag_subtask_selected_respects_suspend_flag() -> None:
    owner = _Owner()
    controller = DagController(owner)
    owner._dag_subtasks_list.setCurrentRow(1)

    controller.on_dag_subtask_selected()
    assert owner._selected_subtask_id == "s1"

    owner._suspend_form_events = True
    owner._dag_subtasks_list.setCurrentRow(0)
    controller.on_dag_subtask_selected()
    assert owner._selected_subtask_id == "s1"

    owner._suspend_form_events = False
    owner._dag_subtasks_list.setCurrentRow(-1)
    controller.on_dag_subtask_selected()
    assert owner._selected_subtask_id == "s1"


def test_on_dag_add_subtask_creates_task_and_persists() -> None:
    owner = _Owner(doc=_Doc(subtask_ids=[], edges=[]))
    owner._selected_task_index = -1
    owner._dag_persist_layout.setChecked(True)
    owner._dag_new_subtask_id.setText("sx")
    controller = DagController(owner)

    controller.on_dag_add_subtask()

    assert owner._selected_task_index == 1
    assert owner._selected_subtask_id == "sx"
    assert owner._dag_new_subtask_id.text() == ""
    assert owner._populate_calls == 1
    assert owner._refresh_calls == 1
    assert owner._persist_calls == 1
    assert owner._dirty_calls == 1


def test_on_dag_remove_subtask_guard_and_success() -> None:
    owner = _Owner(doc=_Doc(subtask_ids=["s0", "s1", "s2"], edges=[("s0", "s1"), ("s1", "s2")]))
    controller = DagController(owner)

    owner._selected_task_index = -1
    controller.on_dag_remove_subtask()
    assert owner._populate_calls == 0

    owner._selected_task_index = 0
    owner._dag_subtasks_list.setCurrentRow(1)
    owner._dag_persist_layout.setChecked(True)
    controller.on_dag_remove_subtask()

    remaining = [sub["id"] for sub in owner._doc.list_subtasks(0)]
    assert remaining == ["s0", "s2"]
    assert owner._selected_subtask_id == "s0"
    assert owner._populate_calls == 1
    assert owner._refresh_calls == 1
    assert owner._persist_calls == 1
    assert owner._dirty_calls == 1


def test_on_dag_add_and_remove_edge_paths() -> None:
    owner = _Owner(doc=_Doc(subtask_ids=["s0", "s1"], edges=[]))
    controller = DagController(owner)

    owner._selected_subtask_id = "s0"
    owner._dag_edge_dst.setText("s1")
    controller.on_dag_add_edge()

    assert owner._doc.list_edges(0) == [("s0", "s1")]
    assert owner._dag_edge_src.text() == ""
    assert owner._dag_edge_dst.text() == ""

    owner._dag_edges_list.setCurrentRow(-1)
    controller.on_dag_remove_edge()
    assert owner._doc.list_edges(0) == [("s0", "s1")]

    owner._dag_edges_list.set_items([_Item("broken", "not_a_tuple")])
    owner._dag_edges_list.setCurrentRow(0)
    controller.on_dag_remove_edge()
    assert owner._doc.list_edges(0) == [("s0", "s1")]

    owner._dag_edges_list.set_items([_Item("s0 -> s1", ("s0", "s1"))])
    owner._dag_edges_list.setCurrentRow(0)
    owner._dag_persist_layout.setChecked(True)
    controller.on_dag_remove_edge()

    assert owner._doc.list_edges(0) == []
    assert owner._persist_calls == 1


def test_node_click_move_drag_and_layout_paths() -> None:
    owner = _Owner(doc=_Doc(subtask_ids=["s0", "s1"], edges=[]))
    controller = DagController(owner)

    controller.on_dag_node_clicked("s1")
    assert owner._selected_subtask_id == "s1"
    assert owner._dag_subtasks_list.currentItem() is not None
    assert owner._dag_subtasks_list.currentItem().text() == "s1"
    assert owner._refresh_task_calls == 1
    assert owner._refresh_calls == 1

    center = QPointF(10.0, 20.0)
    controller.on_dag_node_moved("s1", center)
    assert owner._dag_node_centers["s1"] == QPointF(10.0, 20.0)
    assert owner._update_edges_calls == 1
    assert owner._dag_view.last_scene_rect is not None
    assert owner._dag_manual_positions_by_task["t0"]["s1"] == QPointF(10.0, 20.0)

    controller.on_dag_node_drag_finished("s1")
    assert owner._persist_calls == 0
    owner._dag_persist_layout.setChecked(True)
    controller.on_dag_node_drag_finished("s1")
    assert owner._persist_calls == 1
    controller.on_dag_node_drag_finished("")
    assert owner._persist_calls == 1

    owner._selected_task_index = -1
    controller.on_dag_auto_layout()
    assert owner._render_calls == 0

    owner._selected_task_index = 0
    controller.on_dag_auto_layout()
    assert owner._render_calls == 1
    assert owner._form_hint.value == "DAG auto-layout applied."
    assert owner._persist_calls == 2

    controller.on_dag_persist_layout_toggled(True)
    assert owner._persist_calls == 3
    controller.on_dag_persist_layout_toggled(False)
    assert owner._form_hint.value == "DAG layout persistence disabled."


def test_try_add_dag_edge_validation_branches() -> None:
    owner = _Owner(doc=_Doc(subtask_ids=["s0", "s1"], edges=[]))
    controller = DagController(owner)

    assert controller.try_add_dag_edge("", "s1", show_feedback=True) is False
    assert owner._form_hint.value == "DAG edge rejected: src/dst can not be empty."

    assert controller.try_add_dag_edge("s0", "s0", show_feedback=True) is False
    assert owner._form_hint.value == "DAG edge rejected: self-loop is not allowed."

    assert controller.try_add_dag_edge("s0", "missing", show_feedback=True) is False
    assert owner._form_hint.value == "DAG edge rejected: src/dst node does not exist."

    assert controller.try_add_dag_edge("s0", "s1", show_feedback=True) is True
    assert controller.try_add_dag_edge("s0", "s1", show_feedback=True) is False
    assert owner._form_hint.value == "DAG edge ignored: s0->s1 already exists."


def test_would_create_cycle_handles_revisit_paths() -> None:
    doc = _Doc(
        subtask_ids=["s0", "s1", "s2", "s3"],
        edges=[("s0", "s1"), ("s0", "s2"), ("s1", "s3"), ("s2", "s3")],
    )

    assert DagController.would_create_cycle(doc, 0, "s4", "s0") is False
