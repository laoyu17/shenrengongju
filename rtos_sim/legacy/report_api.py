"""Report-compatible alias API that forwards to new planning services.

语义边界：
- 该模块用于“报告同名接口可调用性”兼容，不等价于完整运行时调度器。
- `sched_schedule` 仅基于静态表做时间点查询，不维护运行时队列/状态机。
- `sched_td_*` / `sched_dy_*` 仅维护轻量事件历史字典，不驱动仿真引擎。
- 需要运行时等价语义时，应使用 `rtos_sim.api` 与 CLI `run` 主链路。
"""

from __future__ import annotations

from math import inf
from pathlib import Path
from typing import Any, Mapping, Sequence

from rtos_sim import api
from rtos_sim.io import ConfigLoader
from rtos_sim.model import ModelSpec
from rtos_sim.planning import PlanningProblem, ScheduleTable, ScheduleWindow


def _as_spec_or_problem(
    config: str | Path | Mapping[str, Any] | ModelSpec | PlanningProblem,
    *,
    task_scope: str | None = None,
    include_non_rt: bool = False,
    horizon: float | None = None,
) -> ModelSpec | PlanningProblem:
    if isinstance(config, PlanningProblem):
        return config
    if isinstance(config, ModelSpec):
        return config
    if isinstance(config, (str, Path)):
        return ConfigLoader().load(str(config))
    return api.build_planning_problem(
        config,
        task_scope=task_scope,
        include_non_rt=include_non_rt,
        horizon=horizon,
    )


def _as_schedule_table(schedule_table: ScheduleTable | Mapping[str, Any]) -> ScheduleTable:
    if isinstance(schedule_table, ScheduleTable):
        return schedule_table
    return api.schedule_table_from_dict(schedule_table)


def sched_init_sched_table(
    config: str | Path | Mapping[str, Any] | ModelSpec | PlanningProblem,
    *,
    planner: str = "np_edf",
    lp_objective: str = "response_time",
    task_scope: str | None = None,
    include_non_rt: bool = False,
    horizon: float | None = None,
    time_limit_seconds: float | None = 30.0,
) -> dict[str, Any]:
    """报告同名函数：初始化并返回静态调度表。"""

    spec_or_problem = _as_spec_or_problem(
        config,
        task_scope=task_scope,
        include_non_rt=include_non_rt,
        horizon=horizon,
    )
    result = api.plan_static(
        spec_or_problem,
        planner=planner,
        task_scope=task_scope,
        include_non_rt=include_non_rt,
        horizon=horizon,
        lp_objective=lp_objective,
        time_limit_seconds=time_limit_seconds,
    )
    return result.schedule_table.to_dict()


def sched_plan_static(
    config: str | Path | Mapping[str, Any] | ModelSpec | PlanningProblem,
    *,
    planner: str = "np_edf",
    lp_objective: str = "response_time",
    task_scope: str | None = None,
    include_non_rt: bool = False,
    horizon: float | None = None,
    time_limit_seconds: float | None = 30.0,
) -> dict[str, Any]:
    """报告风格别名：返回完整静态规划结果。"""

    spec_or_problem = _as_spec_or_problem(
        config,
        task_scope=task_scope,
        include_non_rt=include_non_rt,
        horizon=horizon,
    )
    result = api.plan_static(
        spec_or_problem,
        planner=planner,
        task_scope=task_scope,
        include_non_rt=include_non_rt,
        horizon=horizon,
        lp_objective=lp_objective,
        time_limit_seconds=time_limit_seconds,
    )
    return result.to_dict()


def sched_analyze_wcrt(
    config: str | Path | Mapping[str, Any] | ModelSpec | PlanningProblem,
    schedule_table: ScheduleTable | Mapping[str, Any],
    *,
    task_scope: str | None = None,
    include_non_rt: bool = False,
    horizon: float | None = None,
    max_iterations: int = 64,
    epsilon: float = 1e-9,
) -> dict[str, Any]:
    """报告风格别名：执行 WCRT/RTA 分析并返回字典结果。"""

    spec_or_problem = _as_spec_or_problem(
        config,
        task_scope=task_scope,
        include_non_rt=include_non_rt,
        horizon=horizon,
    )
    table = _as_schedule_table(schedule_table)
    report = api.analyze_wcrt(
        spec_or_problem,
        table,
        task_scope=task_scope,
        include_non_rt=include_non_rt,
        horizon=horizon,
        max_iterations=max_iterations,
        epsilon=epsilon,
    )
    return report.to_dict()


def sched_export_os_config(
    schedule_table: ScheduleTable | Mapping[str, Any],
    *,
    policy: str = "deadline_then_wcet",
) -> dict[str, Any]:
    """报告风格别名：导出 OS 参数。"""

    table = _as_schedule_table(schedule_table)
    return api.export_os_config(table, policy=policy)


def sched_benchmark_sched_rate(
    config_paths: Sequence[str | Path],
    *,
    baseline: str = "np_edf",
    candidates: Sequence[str] = ("np_dm", "precautious_dm", "lp"),
    task_scope: str | None = None,
    include_non_rt: bool = False,
    horizon: float | None = None,
    lp_objective: str = "response_time",
    lp_time_limit_seconds: float | None = 30.0,
    wcrt_max_iterations: int = 64,
    wcrt_epsilon: float = 1e-9,
) -> dict[str, Any]:
    """报告风格别名：执行可调度率基准。"""

    normalized_paths = [str(Path(item)) for item in config_paths]
    return api.benchmark_sched_rate(
        normalized_paths,
        baseline=baseline,
        candidates=candidates,
        task_scope=task_scope,
        include_non_rt=include_non_rt,
        horizon=horizon,
        lp_objective=lp_objective,
        lp_time_limit_seconds=lp_time_limit_seconds,
        wcrt_max_iterations=wcrt_max_iterations,
        wcrt_epsilon=wcrt_epsilon,
    )


def sched_get_sched_table(
    config: str | Path | Mapping[str, Any] | ModelSpec | PlanningProblem,
    *,
    planner: str = "np_edf",
    lp_objective: str = "response_time",
    task_scope: str | None = None,
    include_non_rt: bool = False,
    horizon: float | None = None,
    time_limit_seconds: float | None = 30.0,
) -> dict[str, Any]:
    """报告同名函数：获取调度时间表。"""

    return sched_init_sched_table(
        config,
        planner=planner,
        lp_objective=lp_objective,
        task_scope=task_scope,
        include_non_rt=include_non_rt,
        horizon=horizon,
        time_limit_seconds=time_limit_seconds,
    )


def _normalize_window_payload(window: Mapping[str, Any]) -> ScheduleWindow:
    segment_key = str(window.get("segment_key", "")).strip()
    task_id = str(window.get("task_id", "")).strip()
    subtask_id = str(window.get("subtask_id", "")).strip()
    segment_id = str(window.get("segment_id", "")).strip()
    core_id = str(window.get("core_id", "")).strip()
    if not all((segment_key, task_id, subtask_id, segment_id, core_id)):
        raise ValueError("window requires segment_key/task_id/subtask_id/segment_id/core_id")
    start_raw = window.get("start_time", window.get("start"))
    end_raw = window.get("end_time", window.get("end"))
    if start_raw is None or end_raw is None:
        raise ValueError("window requires start/start_time and end/end_time")
    start_time = float(start_raw)
    end_time = float(end_raw)
    if end_time <= start_time:
        raise ValueError("window requires end > start")
    release_time = float(window.get("release_time", start_time))
    deadline_raw = window.get("absolute_deadline")
    return ScheduleWindow(
        segment_key=segment_key,
        task_id=task_id,
        subtask_id=subtask_id,
        segment_id=segment_id,
        core_id=core_id,
        start_time=start_time,
        end_time=end_time,
        release_time=release_time,
        absolute_deadline=float(deadline_raw) if deadline_raw is not None else None,
        constraint_evidence=dict(window.get("constraint_evidence", {})),
    )


def sched_sched_insert(
    schedule_table: ScheduleTable | Mapping[str, Any],
    window: Mapping[str, Any],
) -> dict[str, Any]:
    """报告同名函数：将任务调度时刻插入调度时间表。"""

    table = _as_schedule_table(schedule_table)
    rows = list(table.windows)
    rows.append(_normalize_window_payload(window))
    rows.sort(key=lambda item: (item.start_time, item.end_time, item.core_id, item.segment_key))
    return ScheduleTable(
        planner=table.planner,
        core_ids=list(table.core_ids),
        windows=rows,
        feasible=table.feasible,
        violations=list(table.violations),
        evidence=list(table.evidence),
    ).to_dict()


def sched_sched_remove(
    schedule_table: ScheduleTable | Mapping[str, Any],
    *,
    segment_key: str | None = None,
    core_id: str | None = None,
) -> dict[str, Any]:
    """报告同名函数：将任务调度时刻从调度时间表删除。"""

    table = _as_schedule_table(schedule_table)
    kept_windows: list[ScheduleWindow] = []
    for window in table.windows:
        if segment_key is not None and window.segment_key != segment_key:
            kept_windows.append(window)
            continue
        if core_id is not None and window.core_id != core_id:
            kept_windows.append(window)
            continue
        if segment_key is None and core_id is None:
            kept_windows.append(window)
    return ScheduleTable(
        planner=table.planner,
        core_ids=list(table.core_ids),
        windows=kept_windows,
        feasible=table.feasible,
        violations=list(table.violations),
        evidence=list(table.evidence),
    ).to_dict()


def _update_runtime_state(
    state: Mapping[str, Any] | None,
    *,
    event: str,
    task_id: str,
    time: float,
) -> dict[str, Any]:
    payload = dict(state or {})
    history = list(payload.get("events", []))
    history.append({"event": event, "task_id": task_id, "time": float(time)})
    payload["events"] = history
    payload["last_event"] = history[-1]
    return payload


def sched_td_task_new_arrival(
    state: Mapping[str, Any] | None = None,
    *,
    task_id: str,
    time: float,
) -> dict[str, Any]:
    """报告同名函数：同步任务实例到达服务函数。"""

    return _update_runtime_state(state, event="td_task_new_arrival", task_id=task_id, time=time)


def sched_td_task_complete(
    state: Mapping[str, Any] | None = None,
    *,
    task_id: str,
    time: float,
) -> dict[str, Any]:
    """报告同名函数：同步任务实例完成服务函数。"""

    return _update_runtime_state(state, event="td_task_complete", task_id=task_id, time=time)


def sched_dy_task_new_arrival(
    state: Mapping[str, Any] | None = None,
    *,
    task_id: str,
    time: float,
) -> dict[str, Any]:
    """报告同名函数：定期任务、间歇任务到达。"""

    return _update_runtime_state(state, event="dy_task_new_arrival", task_id=task_id, time=time)


def sched_dy_task_complete(
    state: Mapping[str, Any] | None = None,
    *,
    task_id: str,
    time: float,
) -> dict[str, Any]:
    """报告同名函数：定期任务、间歇任务完成。"""

    return _update_runtime_state(state, event="dy_task_complete", task_id=task_id, time=time)


def sched_pick_next_task(candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """报告同名函数：选取下一个调度的任务实例。"""

    normalized: list[dict[str, Any]] = []
    for candidate in candidates:
        task_id = str(candidate.get("task_id", "")).strip()
        if not task_id:
            continue
        deadline_raw = candidate.get("absolute_deadline", candidate.get("deadline"))
        wcet_raw = candidate.get("wcet", candidate.get("execution_time", 0.0))
        release_raw = candidate.get("release_time", 0.0)
        normalized.append(
            {
                **dict(candidate),
                "task_id": task_id,
                "_deadline_sort": float(deadline_raw) if deadline_raw is not None else inf,
                "_wcet_sort": float(wcet_raw),
                "_release_sort": float(release_raw),
            }
        )
    if not normalized:
        return None
    chosen = min(
        normalized,
        key=lambda item: (item["_deadline_sort"], item["_release_sort"], item["_wcet_sort"], item["task_id"]),
    )
    return {key: value for key, value in chosen.items() if not key.startswith("_")}


def sched_schedule(
    schedule_table: ScheduleTable | Mapping[str, Any],
    *,
    now: float,
    core_id: str | None = None,
) -> dict[str, Any]:
    """报告同名函数：调度服务函数（静态表查询语义）。"""

    table = _as_schedule_table(schedule_table)
    windows = [window for window in table.windows if core_id is None or window.core_id == core_id]
    active = [
        window
        for window in windows
        if window.start_time <= now < window.end_time
    ]
    if active:
        selected = min(active, key=lambda item: (item.end_time, item.core_id, item.segment_key)).to_dict()
        return {"now": float(now), "core_id": core_id, "selected_window": selected}
    future = [window for window in windows if window.start_time > now]
    selected_future = (
        min(future, key=lambda item: (item.start_time, item.core_id, item.segment_key)).to_dict()
        if future
        else None
    )
    return {"now": float(now), "core_id": core_id, "selected_window": selected_future}


def sched_model_change(
    *,
    mode: str,
    schedule_table: ScheduleTable | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """报告同名函数：切换静态调度与动态调度模式。"""

    normalized = mode.strip().lower()
    if normalized not in {"static", "dynamic"}:
        raise ValueError("mode must be static|dynamic")
    payload: dict[str, Any] = {"mode": normalized, "static_window_mode": normalized == "static"}
    if normalized == "static" and schedule_table is not None:
        payload["static_windows"] = api.schedule_table_to_runtime_windows(_as_schedule_table(schedule_table))
    return payload


def wcrt_analyse(
    config: str | Path | Mapping[str, Any] | ModelSpec | PlanningProblem,
    schedule_table: ScheduleTable | Mapping[str, Any],
    *,
    task_scope: str | None = None,
    include_non_rt: bool = False,
    horizon: float | None = None,
    max_iterations: int = 64,
    epsilon: float = 1e-9,
) -> dict[str, Any]:
    """报告同名函数：分析最坏响应时间。"""

    return sched_analyze_wcrt(
        config,
        schedule_table,
        task_scope=task_scope,
        include_non_rt=include_non_rt,
        horizon=horizon,
        max_iterations=max_iterations,
        epsilon=epsilon,
    )


def partition_periodic_task(
    tasks: Sequence[str | Mapping[str, Any]],
    core_ids: Sequence[str],
) -> dict[str, Any]:
    """报告同名函数：为动态任务划分计算资源。"""

    normalized_cores = [str(core_id).strip() for core_id in core_ids if str(core_id).strip()]
    if not normalized_cores:
        raise ValueError("core_ids must not be empty")
    mapping: dict[str, str] = {}
    ordered_tasks: list[str] = []
    for item in tasks:
        if isinstance(item, Mapping):
            task_id = str(item.get("task_id", item.get("id", ""))).strip()
        else:
            task_id = str(item).strip()
        if not task_id:
            continue
        ordered_tasks.append(task_id)
        mapping[task_id] = normalized_cores[(len(ordered_tasks) - 1) % len(normalized_cores)]
    return {"task_to_core": mapping, "core_ids": normalized_cores}
