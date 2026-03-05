from __future__ import annotations

from rtos_sim.model import ModelSpec
from rtos_sim.planning import (
    PlanningProblem,
    PlanningSegment,
    assign_segments_wfd,
    plan_np_dm,
    plan_np_edf,
    plan_precautious_dm,
)


def _segment(
    *,
    task_id: str,
    segment_id: str,
    wcet: float,
    release: float = 0.0,
    deadline: float | None = None,
    period: float | None = 10.0,
    mapping_hint: str | None = None,
    predecessors: list[str] | None = None,
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
    )


def test_wfd_assignment_balances_load() -> None:
    segments = [
        _segment(task_id="t0", segment_id="a", wcet=4.0, deadline=10.0),
        _segment(task_id="t1", segment_id="b", wcet=4.0, deadline=10.0),
        _segment(task_id="t2", segment_id="c", wcet=1.0, deadline=10.0),
    ]
    problem = PlanningProblem(core_ids=["c0", "c1"], segments=segments, horizon=20.0)
    assignments, evidence, violations = assign_segments_wfd(problem)

    assert not violations
    assert assignments[segments[0].key] == "c0"
    assert assignments[segments[1].key] == "c1"
    loads = {"c0": 0.0, "c1": 0.0}
    for segment in segments:
        core_id = assignments[segment.key]
        loads[core_id] += segment.wcet / 10.0
    assert abs(loads["c0"] - loads["c1"]) <= 0.2
    assert any(item.rule == "wfd_assignment" for item in evidence)


def test_np_dm_orders_by_relative_deadline() -> None:
    urgent = _segment(task_id="urgent", segment_id="a", wcet=1.0, deadline=3.0, mapping_hint="c0")
    relaxed = _segment(task_id="relaxed", segment_id="b", wcet=1.0, deadline=8.0, mapping_hint="c0")
    result = plan_np_dm(PlanningProblem(core_ids=["c0"], segments=[relaxed, urgent]))

    core_windows = result.schedule_table.by_core()["c0"]
    assert result.feasible
    assert core_windows[0].segment_key == urgent.key
    assert core_windows[1].segment_key == relaxed.key


def test_np_edf_orders_by_absolute_deadline() -> None:
    late = _segment(task_id="late", segment_id="a", wcet=1.0, deadline=8.0, mapping_hint="c0")
    early = _segment(task_id="early", segment_id="b", wcet=1.0, deadline=4.0, mapping_hint="c0")
    result = plan_np_edf(PlanningProblem(core_ids=["c0"], segments=[late, early]))

    core_windows = result.schedule_table.by_core()["c0"]
    assert result.feasible
    assert core_windows[0].segment_key == early.key
    assert core_windows[1].segment_key == late.key


def test_precautious_dm_waits_for_risky_short_deadline_task() -> None:
    long_running = _segment(
        task_id="long",
        segment_id="a",
        wcet=4.0,
        release=0.0,
        deadline=10.0,
        mapping_hint="c0",
    )
    short_deadline = _segment(
        task_id="short",
        segment_id="b",
        wcet=1.0,
        release=1.0,
        deadline=2.0,
        mapping_hint="c0",
    )
    result = plan_precautious_dm(PlanningProblem(core_ids=["c0"], segments=[long_running, short_deadline]))
    by_key = {window.segment_key: window for window in result.schedule_table.windows}

    assert result.feasible
    assert by_key[short_deadline.key].start_time == 1.0
    assert by_key[short_deadline.key].end_time == 2.0
    assert by_key[long_running.key].start_time == 2.0
    assert any(item.rule == "precautious_wait" for item in result.schedule_table.evidence)


def test_schedule_respects_predecessor_constraints_across_cores() -> None:
    first = _segment(task_id="t0", segment_id="a", wcet=2.0, deadline=10.0, mapping_hint="c0")
    second = _segment(
        task_id="t1",
        segment_id="b",
        wcet=1.0,
        deadline=10.0,
        mapping_hint="c1",
        predecessors=[first.key],
    )
    result = plan_np_edf(PlanningProblem(core_ids=["c0", "c1"], segments=[first, second]))
    by_key = {window.segment_key: window for window in result.schedule_table.windows}

    assert result.feasible
    assert by_key[second.key].start_time >= by_key[first.key].end_time


def test_deadline_miss_marks_infeasible() -> None:
    segment = _segment(task_id="t0", segment_id="late", wcet=5.0, deadline=3.0, mapping_hint="c0")
    result = plan_np_edf(PlanningProblem(core_ids=["c0"], segments=[segment]))

    assert not result.feasible
    assert any(item.constraint == "deadline_miss" for item in result.schedule_table.violations)


def test_planning_problem_from_model_spec_builds_segment_precedence() -> None:
    spec = ModelSpec.model_validate(
        {
            "version": "0.2",
            "platform": {
                "processor_types": [
                    {"id": "cpu", "name": "cpu", "core_count": 2, "speed_factor": 1.0}
                ],
                "cores": [
                    {"id": "c0", "type_id": "cpu", "speed_factor": 1.0},
                    {"id": "c1", "type_id": "cpu", "speed_factor": 1.0},
                ],
            },
            "resources": [],
            "tasks": [
                {
                    "id": "t0",
                    "name": "task0",
                    "task_type": "dynamic_rt",
                    "deadline": 10.0,
                    "arrival": 1.0,
                    "subtasks": [
                        {
                            "id": "s0",
                            "predecessors": [],
                            "successors": [],
                            "segments": [
                                {"id": "seg0", "index": 1, "wcet": 2.0, "required_resources": []}
                            ],
                        },
                        {
                            "id": "s1",
                            "predecessors": ["s0"],
                            "successors": [],
                            "segments": [
                                {"id": "seg1", "index": 1, "wcet": 1.0, "required_resources": []}
                            ],
                        },
                    ],
                }
            ],
            "scheduler": {"name": "edf", "params": {}},
            "sim": {"duration": 20.0, "seed": 1},
        }
    )
    problem = PlanningProblem.from_model_spec(spec, task_scope="sync_and_dynamic_rt")
    by_key = {segment.key: segment for segment in problem.segments}

    assert len(problem.core_ids) == 2
    assert len(problem.segments) == 2
    first_key = "t0:s0:seg0"
    second_key = "t0:s1:seg1"
    assert by_key[first_key].release_time == 1.0
    assert by_key[first_key].absolute_deadline == 11.0
    assert second_key in by_key
    assert first_key in by_key[second_key].predecessors


def test_planning_problem_default_task_scope_includes_sync_only() -> None:
    spec = ModelSpec.model_validate(
        {
            "version": "0.2",
            "platform": {
                "processor_types": [
                    {"id": "cpu", "name": "cpu", "core_count": 1, "speed_factor": 1.0}
                ],
                "cores": [{"id": "c0", "type_id": "cpu", "speed_factor": 1.0}],
            },
            "resources": [],
            "tasks": [
                {
                    "id": "sync",
                    "name": "sync",
                    "task_type": "time_deterministic",
                    "period": 10.0,
                    "deadline": 10.0,
                    "arrival": 0.0,
                    "phase_offset": 0.0,
                    "subtasks": [
                        {
                            "id": "s0",
                            "predecessors": [],
                            "successors": [],
                            "segments": [
                                {
                                    "id": "seg0",
                                    "index": 1,
                                    "wcet": 1.0,
                                    "required_resources": [],
                                    "mapping_hint": "c0",
                                }
                            ],
                        }
                    ],
                },
                {
                    "id": "dyn",
                    "name": "dynamic",
                    "task_type": "dynamic_rt",
                    "deadline": 10.0,
                    "arrival": 0.0,
                    "subtasks": [
                        {
                            "id": "s0",
                            "predecessors": [],
                            "successors": [],
                            "segments": [
                                {"id": "seg0", "index": 1, "wcet": 1.0, "required_resources": []}
                            ],
                        }
                    ],
                },
            ],
            "scheduler": {"name": "edf", "params": {}},
            "sim": {"duration": 20.0, "seed": 1},
        }
    )
    problem = PlanningProblem.from_model_spec(spec)

    assert [segment.task_id for segment in problem.segments] == ["sync"]
    assert problem.metadata["task_scope"] == "sync_only"
    assert problem.metadata["skipped_dynamic_rt_tasks"] == 1
