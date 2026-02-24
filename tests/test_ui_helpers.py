from __future__ import annotations

from PyQt6.QtCore import Qt

from rtos_sim.ui.dag_layout import compute_auto_layout_positions
from rtos_sim.ui.gantt_helpers import (
    SegmentVisualMeta,
    brush_style_name,
    format_segment_details,
    parse_segment_key,
    pen_style_name,
    safe_float,
    safe_optional_float,
    safe_optional_int,
    task_from_job,
)
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


def test_gantt_helper_parse_and_safe_casts() -> None:
    assert task_from_job("taskA@3") == "taskA"
    assert task_from_job("") == "unknown"
    assert parse_segment_key("job@0:s0:seg0") == ("s0", "seg0")
    assert parse_segment_key("bad_key") == ("unknown", "unknown")
    assert safe_float("1.25", 0.0) == 1.25
    assert safe_float("x", 0.0) == 0.0
    assert safe_optional_float("2.5") == 2.5
    assert safe_optional_float("x") is None
    assert safe_optional_int("7") == 7
    assert safe_optional_int("x") is None


def test_gantt_helper_style_and_detail_format() -> None:
    meta = SegmentVisualMeta(
        task_id="t0",
        job_id="t0@0",
        subtask_id="s0",
        segment_id="seg0",
        segment_key="t0@0:s0:seg0",
        core_id="c0",
        start=1.0,
        end=2.5,
        duration=1.5,
        status="Completed",
        resources=["r0"],
        event_id_start="ev1",
        event_id_end="ev2",
        seq_start=1,
        seq_end=2,
        correlation_id="corr",
        deadline=3.0,
        lateness_at_end=-0.5,
        remaining_after_preempt=None,
        execution_time_est=1.6,
        context_overhead=0.1,
        migration_overhead=0.0,
        estimated_finish=2.6,
    )
    detail = format_segment_details(meta)
    assert "task_id: t0" in detail
    assert "segment_key: t0@0:s0:seg0" in detail
    assert "remaining_after_preempt: -" in detail
    assert brush_style_name(Qt.BrushStyle.Dense4Pattern) == "Dense4"
    assert pen_style_name(Qt.PenStyle.DashDotLine) == "DashDot"
