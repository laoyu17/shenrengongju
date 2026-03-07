from __future__ import annotations

import pytest

from rtos_sim.api import analyze_wcrt as analyze_wcrt_api, plan_static as plan_static_api
from rtos_sim.model import ModelSpec
from rtos_sim.planning import (
    PlanningProblem,
    PlanningSegment,
    ScheduleTable,
    ScheduleWindow,
    analyze_wcrt,
)


def _segment(
    *,
    task_id: str,
    segment_id: str,
    wcet: float,
    release: float = 0.0,
    deadline: float | None = None,
    period: float | None = None,
    mapping_hint: str | None = None,
    predecessors: list[str] | None = None,
    task_type: str = "dynamic_rt",
    required_resources: list[str] | None = None,
) -> PlanningSegment:
    absolute_deadline = release + deadline if deadline is not None else None
    return PlanningSegment(
        task_id=task_id,
        subtask_id="s0",
        segment_id=segment_id,
        wcet=wcet,
        release_time=release,
        period=period,
        relative_deadline=deadline,
        absolute_deadline=absolute_deadline,
        mapping_hint=mapping_hint,
        predecessors=list(predecessors or []),
        metadata={
            "task_type": task_type,
            "required_resources": list(required_resources or []),
            "raw_wcet": wcet,
        },
    )


def _window(segment: PlanningSegment, *, core_id: str, start: float, end: float) -> ScheduleWindow:
    return ScheduleWindow(
        segment_key=segment.key,
        task_id=segment.task_id,
        subtask_id=segment.subtask_id,
        segment_id=segment.segment_id,
        core_id=core_id,
        start_time=start,
        end_time=end,
        release_time=segment.release_time,
        absolute_deadline=segment.absolute_deadline,
        constraint_evidence={},
    )


def test_wcrt_single_task_no_interference() -> None:
    task = _segment(task_id="t0", segment_id="a", wcet=2.0, deadline=6.0, period=10.0, mapping_hint="c0")
    problem = PlanningProblem(core_ids=["c0"], segments=[task])
    schedule = ScheduleTable(
        planner="np_edf",
        core_ids=["c0"],
        windows=[_window(task, core_id="c0", start=0.0, end=2.0)],
        feasible=True,
    )
    report = analyze_wcrt(problem, schedule)

    assert report.feasible
    item = report.items[0]
    assert item.task_id == "t0"
    assert item.wcrt == pytest.approx(2.0)
    assert item.schedulable
    assert item.iterations[0] == pytest.approx(2.0)


def test_wcrt_includes_sync_interference_from_static_windows() -> None:
    sync_task = _segment(
        task_id="sync",
        segment_id="a",
        wcet=2.0,
        deadline=20.0,
        period=20.0,
        mapping_hint="c0",
        task_type="time_deterministic",
    )
    target = _segment(task_id="target", segment_id="b", wcet=2.0, deadline=5.0, period=10.0, mapping_hint="c0")
    problem = PlanningProblem(core_ids=["c0"], segments=[sync_task, target])
    schedule = ScheduleTable(
        planner="np_dm",
        core_ids=["c0"],
        windows=[
            _window(sync_task, core_id="c0", start=0.0, end=2.0),
            _window(target, core_id="c0", start=2.0, end=4.0),
        ],
        feasible=True,
    )
    report = analyze_wcrt(problem, schedule)
    item_by_task = {item.task_id: item for item in report.items}

    assert item_by_task["target"].wcrt == pytest.approx(4.0)
    assert item_by_task["target"].schedulable


def test_wcrt_includes_high_priority_independent_interference() -> None:
    hp = _segment(task_id="hp", segment_id="a", wcet=1.0, deadline=5.0, period=5.0, mapping_hint="c0")
    lp = _segment(task_id="lp", segment_id="b", wcet=2.0, deadline=10.0, period=10.0, mapping_hint="c0")
    problem = PlanningProblem(core_ids=["c0"], segments=[hp, lp])
    schedule = ScheduleTable(
        planner="np_edf",
        core_ids=["c0"],
        windows=[
            _window(hp, core_id="c0", start=0.0, end=1.0),
            _window(lp, core_id="c0", start=1.0, end=3.0),
        ],
        feasible=True,
    )
    report = analyze_wcrt(problem, schedule)
    item_by_task = {item.task_id: item for item in report.items}
    lp_item = item_by_task["lp"]

    assert lp_item.wcrt == pytest.approx(3.0)
    assert lp_item.iterations[-1] == pytest.approx(3.0)
    assert lp_item.schedulable


def test_wcrt_filters_high_priority_interference_on_disjoint_cores() -> None:
    hp = _segment(task_id="hp", segment_id="a", wcet=1.0, deadline=5.0, period=5.0, mapping_hint="c0")
    lp = _segment(task_id="lp", segment_id="b", wcet=2.0, deadline=10.0, period=10.0, mapping_hint="c1")
    problem = PlanningProblem(core_ids=["c0", "c1"], segments=[hp, lp])
    schedule = ScheduleTable(
        planner="np_edf",
        core_ids=["c0", "c1"],
        windows=[
            _window(hp, core_id="c0", start=0.0, end=1.0),
            _window(lp, core_id="c1", start=0.0, end=2.0),
        ],
        feasible=True,
    )
    report = analyze_wcrt(problem, schedule)
    item_by_task = {item.task_id: item for item in report.items}

    assert item_by_task["lp"].wcrt == pytest.approx(2.0)
    assert item_by_task["lp"].schedulable


def test_wcrt_excludes_dependent_task_from_independent_interference() -> None:
    low = _segment(task_id="low", segment_id="a", wcet=2.0, deadline=10.0, period=10.0, mapping_hint="c0")
    high_dep = _segment(
        task_id="high_dep",
        segment_id="b",
        wcet=1.0,
        deadline=3.0,
        period=3.0,
        mapping_hint="c1",
        predecessors=[low.key],
    )
    problem = PlanningProblem(core_ids=["c0", "c1"], segments=[low, high_dep])
    schedule = ScheduleTable(
        planner="np_edf",
        core_ids=["c0", "c1"],
        windows=[
            _window(low, core_id="c0", start=0.0, end=2.0),
            _window(high_dep, core_id="c1", start=2.0, end=3.0),
        ],
        feasible=True,
    )
    report = analyze_wcrt(problem, schedule)
    item_by_task = {item.task_id: item for item in report.items}

    assert item_by_task["low"].wcrt == pytest.approx(2.0)
    assert item_by_task["low"].schedulable


def test_wcrt_includes_lower_priority_resource_blocking_bound() -> None:
    low = _segment(
        task_id="low",
        segment_id="a",
        wcet=4.0,
        deadline=20.0,
        period=20.0,
        mapping_hint="c0",
        required_resources=["r0"],
    )
    target = _segment(
        task_id="target",
        segment_id="b",
        wcet=2.0,
        deadline=10.0,
        period=10.0,
        mapping_hint="c0",
        required_resources=["r0"],
    )
    problem = PlanningProblem(
        core_ids=["c0"],
        segments=[low, target],
        metadata={
            "resource_bindings": {"r0": {"bound_core_id": "c0", "protocol": "mutex"}},
            "scheduler_context": {"overhead": {"context_switch": 0.0, "migration": 0.0, "schedule": 0.0}},
        },
    )
    schedule = ScheduleTable(
        planner="np_edf",
        core_ids=["c0"],
        windows=[
            _window(low, core_id="c0", start=0.0, end=4.0),
            _window(target, core_id="c0", start=4.0, end=6.0),
        ],
        feasible=True,
    )

    report = analyze_wcrt(problem, schedule)
    item_by_task = {item.task_id: item for item in report.items}

    assert item_by_task["target"].wcrt == pytest.approx(6.0)
    assert report.metadata["blocking_bound"] == "modeled"
    assert "resource_blocking" in report.metadata["modeled_dimensions"]
    component = next(item for item in report.evidence if item.payload.get("task_id") == "target")
    assert component.payload["blocking_bound"] == pytest.approx(4.0)


def test_wcrt_includes_dispatch_and_migration_overheads() -> None:
    first = _segment(task_id="t0", segment_id="a", wcet=1.0, deadline=10.0, period=10.0, mapping_hint="c0")
    second = _segment(task_id="t0", segment_id="b", wcet=2.0, deadline=10.0, period=10.0, mapping_hint="c1")
    second.predecessors = [first.key]
    problem = PlanningProblem(
        core_ids=["c0", "c1"],
        segments=[first, second],
        metadata={
            "scheduler_context": {
                "overhead": {"context_switch": 0.25, "migration": 0.5, "schedule": 0.25}
            }
        },
    )
    schedule = ScheduleTable(
        planner="np_edf",
        core_ids=["c0", "c1"],
        windows=[
            _window(first, core_id="c0", start=0.0, end=1.0),
            _window(second, core_id="c1", start=1.0, end=3.0),
        ],
        feasible=True,
    )

    report = analyze_wcrt(problem, schedule)
    item = report.items[0]

    assert item.wcrt == pytest.approx(4.5)
    assert report.metadata["overhead_bound"] == "modeled"
    assert "dispatch_overhead" in report.metadata["modeled_dimensions"]
    assert "migration_overhead" in report.metadata["modeled_dimensions"]
    component = next(item for item in report.evidence if item.payload.get("task_id") == "t0")
    assert component.payload["dispatch_overhead"] == pytest.approx(1.0)
    assert component.payload["migration_overhead"] == pytest.approx(0.5)


def test_wcrt_uses_execution_cost_of_scheduled_core() -> None:
    task = _segment(task_id="t0", segment_id="a", wcet=4.0, deadline=6.0, period=10.0, mapping_hint="c1")
    task.metadata["eligible_core_ids"] = ["c0", "c1"]
    task.metadata["execution_cost_by_core"] = {"c0": 4.0, "c1": 2.0}
    task.metadata["default_execution_cost"] = 2.0
    problem = PlanningProblem(core_ids=["c0", "c1"], segments=[task])
    schedule = ScheduleTable(
        planner="np_edf",
        core_ids=["c0", "c1"],
        windows=[_window(task, core_id="c1", start=0.0, end=2.0)],
        feasible=True,
    )

    report = analyze_wcrt(problem, schedule)

    assert report.feasible
    assert report.items[0].wcrt == pytest.approx(2.0)


def test_api_wcrt_metadata_includes_arrival_assumption_trace() -> None:
    spec = ModelSpec.model_validate(
        {
            "version": "0.2",
            "platform": {
                "processor_types": [{"id": "cpu", "name": "cpu", "core_count": 1, "speed_factor": 1.0}],
                "cores": [{"id": "c0", "type_id": "cpu", "speed_factor": 1.0}],
            },
            "resources": [],
            "tasks": [
                {
                    "id": "p",
                    "name": "poisson",
                    "task_type": "dynamic_rt",
                    "deadline": 10.0,
                    "arrival": 0.0,
                    "arrival_process": {
                        "type": "poisson",
                        "params": {"rate": 2.0},
                        "max_releases": 5,
                    },
                    "subtasks": [
                        {"id": "s0", "predecessors": [], "successors": [], "segments": [{"id": "seg0", "index": 1, "wcet": 0.1}]}
                    ],
                }
            ],
            "scheduler": {"name": "edf", "params": {}},
            "sim": {"duration": 10.0, "seed": 31},
            "planning": {
                "enabled": True,
                "params": {
                    "arrival_analysis_mode": "conservative_envelope",
                    "arrival_envelope_min_intervals": {"p": 0.25},
                },
            },
        }
    )

    plan = plan_static_api(spec, task_scope="sync_and_dynamic_rt")
    report = analyze_wcrt_api(spec, plan.schedule_table, task_scope="sync_and_dynamic_rt")

    trace = report.metadata["arrival_assumption_trace"]
    assert trace["arrival_analysis_mode"] == "conservative_envelope"
    task_trace = trace["tasks"][0]
    assert task_trace["generator"] == "poisson"
    assert task_trace["seed_source"] == "not_used(conservative_envelope)"
    assert task_trace["resolved_min_interval"] == pytest.approx(0.25)
    assert task_trace["envelope_source"] == "planning.params.arrival_envelope_min_intervals.p"
    assert report.metadata["planning_context"]["arrival_analysis_mode"] == "conservative_envelope"
