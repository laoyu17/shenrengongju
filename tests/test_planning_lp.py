from __future__ import annotations

import pytest

from rtos_sim.planning import PlanningProblem, PlanningSegment, plan_lp
import rtos_sim.planning.lp_solver as lp_solver


def _segment(
    *,
    task_id: str,
    segment_id: str,
    wcet: float,
    release: float = 0.0,
    deadline: float | None = None,
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
        period=10.0,
        relative_deadline=deadline,
        absolute_deadline=absolute_deadline,
        mapping_hint=mapping_hint,
        predecessors=list(predecessors or []),
    )


def _problem(segments: list[PlanningSegment], cores: list[str] | None = None) -> PlanningProblem:
    return PlanningProblem(core_ids=list(cores or ["c0", "c1"]), segments=segments, horizon=30.0)


def test_lp_precheck_invalid_mapping_hint_returns_explained_failure() -> None:
    segment = _segment(task_id="t0", segment_id="bad_map", wcet=1.0, deadline=5.0, mapping_hint="cx")
    result = plan_lp(_problem([segment]), objective="response_time")

    assert not result.feasible
    assert any(item.constraint == "invalid_mapping_hint" for item in result.schedule_table.violations)


def test_lp_precheck_deadline_window_violation_returns_explained_failure() -> None:
    segment = _segment(task_id="t0", segment_id="late", wcet=6.0, release=0.0, deadline=4.0, mapping_hint="c0")
    result = plan_lp(_problem([segment], cores=["c0"]), objective="response_time")

    assert not result.feasible
    assert any(item.constraint == "deadline_window_too_small" for item in result.schedule_table.violations)


def test_lp_solver_unavailable_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    segment = _segment(task_id="t0", segment_id="s0", wcet=1.0, deadline=5.0, mapping_hint="c0")

    def _raise_import() -> None:
        raise ModuleNotFoundError("mock pulp not installed")

    monkeypatch.setattr(lp_solver, "_load_pulp", _raise_import)
    result = plan_lp(_problem([segment], cores=["c0"]), objective="response_time")

    assert not result.feasible
    assert any(item.constraint == "solver_unavailable" for item in result.schedule_table.violations)


def test_lp_response_time_solution_respects_precedence_and_non_overlap() -> None:
    pulp = pytest.importorskip("pulp")
    assert pulp is not None

    first = _segment(task_id="a", segment_id="s0", wcet=2.0, deadline=10.0, mapping_hint="c0")
    second = _segment(
        task_id="a",
        segment_id="s1",
        wcet=2.0,
        deadline=10.0,
        mapping_hint="c0",
        predecessors=[first.key],
    )
    result = plan_lp(_problem([first, second], cores=["c0"]), objective="response_time")

    assert result.feasible
    by_key = {window.segment_key: window for window in result.schedule_table.windows}
    assert by_key[first.key].end_time <= by_key[second.key].start_time + 1e-9
    assert result.assignments[first.key] == "c0"
    assert result.assignments[second.key] == "c0"


def test_lp_spread_execution_prefers_balanced_assignment() -> None:
    pulp = pytest.importorskip("pulp")
    assert pulp is not None

    left = _segment(task_id="t0", segment_id="a", wcet=3.0, deadline=10.0)
    right = _segment(task_id="t1", segment_id="b", wcet=3.0, deadline=10.0)
    result = plan_lp(_problem([left, right], cores=["c0", "c1"]), objective="spread_execution")

    assert result.feasible
    assert result.assignments[left.key] != result.assignments[right.key]
