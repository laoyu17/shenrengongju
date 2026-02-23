from __future__ import annotations

from rtos_sim.ui.dag_layout import compute_auto_layout_positions
from rtos_sim.ui.table_validation import build_resource_table_errors, build_task_table_errors


def test_compute_auto_layout_positions_places_nodes_by_topology() -> None:
    positions = compute_auto_layout_positions(
        subtask_ids=["s0", "s1", "s2"],
        edges=[("s0", "s1"), ("s1", "s2")],
    )
    assert set(positions) == {"s0", "s1", "s2"}
    assert positions["s0"][0] < positions["s1"][0] < positions["s2"][0]


def test_compute_auto_layout_positions_falls_back_for_cycle() -> None:
    positions = compute_auto_layout_positions(
        subtask_ids=["a", "b", "c"],
        edges=[("a", "b"), ("b", "a"), ("b", "c")],
    )
    assert set(positions) == {"a", "b", "c"}
    assert all(isinstance(value[0], float) and isinstance(value[1], float) for value in positions.values())


def test_build_task_table_errors_covers_duplicates_and_types() -> None:
    rows = [
        {"id": "t0", "name": "A", "task_type": "dynamic_rt", "arrival": "0", "deadline": "10"},
        {"id": "t0", "name": "", "task_type": "wrong", "arrival": "abc", "deadline": "-1"},
    ]
    errors = build_task_table_errors(rows=rows, valid_task_types={"dynamic_rt", "time_deterministic", "non_rt"})
    assert errors[(0, 0)] == "task.id must be unique"
    assert errors[(1, 0)] == "task.id must be unique"
    assert errors[(1, 1)] == "task.name can not be empty"
    assert errors[(1, 2)] == "task_type must be dynamic_rt/time_deterministic/non_rt"
    assert errors[(1, 3)] == "arrival must be number"
    assert errors[(1, 4)] == "deadline must be > 0"


def test_build_resource_table_errors_covers_required_fields() -> None:
    rows = [
        {"id": "r0", "name": "lock", "bound_core_id": "c0", "protocol": "mutex"},
        {"id": "r0", "name": "", "bound_core_id": "", "protocol": "bad"},
    ]
    errors = build_resource_table_errors(rows=rows, valid_protocols={"mutex", "pip", "pcp"})
    assert errors[(0, 0)] == "resource.id must be unique"
    assert errors[(1, 0)] == "resource.id must be unique"
    assert errors[(1, 1)] == "resource.name can not be empty"
    assert errors[(1, 2)] == "bound_core_id can not be empty"
    assert errors[(1, 3)] == "protocol must be mutex/pip/pcp"
