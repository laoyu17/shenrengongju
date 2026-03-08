from __future__ import annotations

from dataclasses import dataclass

from rtos_sim.ui.controllers.dag_controller import DagController


@dataclass
class _Label:
    text: str = ""

    def setText(self, value: str) -> None:  # noqa: N802
        self.text = value


class _Doc:
    def __init__(self) -> None:
        self._subtasks = [{"id": "s0"}, {"id": "s1"}]
        self._edges: list[tuple[str, str]] = [("s0", "s1")]

    def list_tasks(self) -> list[dict]:
        return [{"id": "t0"}]

    def get_task(self, _task_index: int) -> dict:
        return {"id": "t0"}

    def list_subtasks(self, _task_index: int) -> list[dict]:
        return list(self._subtasks)

    def list_edges(self, _task_index: int) -> list[tuple[str, str]]:
        return list(self._edges)

    def add_edge(self, _task_index: int, src_id: str, dst_id: str) -> None:
        self._edges.append((src_id, dst_id))


class _Owner:
    def __init__(self) -> None:
        self._selected_task_index = 0
        self._selected_subtask_id = "s0"
        self._form_hint = _Label()
        self._populate_calls = 0
        self._refresh_calls = 0
        self._dirty_marks = 0
        self._doc = _Doc()
        self._dag_overview_canvas_entry = None

    def _ensure_config_doc(self) -> _Doc:
        return self._doc

    def _populate_form_from_doc(self) -> None:
        self._populate_calls += 1

    def _refresh_dag_node_selection_visuals(self) -> None:
        self._refresh_calls += 1

    def _mark_form_dirty(self) -> None:
        self._dirty_marks += 1




class _EmptyDoc:
    def list_tasks(self) -> list[dict[str, str]]:
        return []


class _EmptyOwner:
    def __init__(self) -> None:
        self._selected_task_index = 3
        self._selected_subtask_id = "stale"

    def _ensure_config_doc(self) -> _EmptyDoc:
        return _EmptyDoc()


def test_select_task_resets_selection_when_doc_is_empty(monkeypatch) -> None:
    owner = _EmptyOwner()
    controller = DagController(owner)

    synced: list[str | None] = []
    refreshed: list[_EmptyDoc] = []
    monkeypatch.setattr(controller, "_sync_single_selection_state", lambda subtask_id: synced.append(subtask_id))
    monkeypatch.setattr(controller, "refresh_dag_widgets", lambda doc: refreshed.append(doc))

    assert controller.select_task(0, sync_table_selection=False) is False
    assert owner._selected_task_index == -1
    assert owner._selected_subtask_id == "s0"
    assert synced == [None]
    assert len(refreshed) == 1

def test_would_create_cycle_detects_back_edge() -> None:
    doc = _Doc()

    assert DagController.would_create_cycle(doc, 0, "s1", "s0") is True
    assert DagController.would_create_cycle(doc, 0, "s0", "s1") is False


def test_try_add_dag_edge_rejects_cycle() -> None:
    owner = _Owner()
    controller = DagController(owner)

    assert controller.try_add_dag_edge("s1", "s0", show_feedback=True) is False
    assert owner._doc.list_edges(0) == [("s0", "s1")]
    assert "creates a cycle" in owner._form_hint.text


def test_try_add_dag_edge_adds_edge_and_marks_dirty() -> None:
    owner = _Owner()
    controller = DagController(owner)

    assert controller.try_add_dag_edge("s0", "s1", show_feedback=True) is False
    assert controller.try_add_dag_edge("s1", "s0", show_feedback=False) is False

    # Add a valid non-duplicate edge after extending nodes.
    owner._doc._subtasks.append({"id": "s2"})
    assert controller.try_add_dag_edge("s1", "s2", show_feedback=True) is True

    assert ("s1", "s2") in owner._doc.list_edges(0)
    assert owner._populate_calls == 1
    assert owner._refresh_calls == 1
    assert owner._dirty_marks == 1
    assert owner._form_hint.text == "DAG edge added: s1->s2"


def test_try_add_dag_edge_requires_selected_task() -> None:
    owner = _Owner()
    owner._selected_task_index = -1
    controller = DagController(owner)

    assert controller.try_add_dag_edge("s0", "s1", show_feedback=True) is False
    assert owner._form_hint.text == "DAG edge rejected: no selected task."
