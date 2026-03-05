from __future__ import annotations

import pytest

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
        metadata={"task_type": task_type},
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
