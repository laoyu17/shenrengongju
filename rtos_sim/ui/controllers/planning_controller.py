"""Controller for UI planning panel interactions."""

from __future__ import annotations

import json
import random
from typing import TYPE_CHECKING, Any, Protocol

import yaml
from PyQt6.QtWidgets import QMessageBox, QTableWidget, QTableWidgetItem

from rtos_sim import api as sim_api
from rtos_sim.io import ConfigError


class UiErrorLogger(Protocol):
    def __call__(self, action: str, exc: Exception, **context: Any) -> None: ...


if TYPE_CHECKING:
    from rtos_sim.ui.app import MainWindow


class PlanningController:
    """Bridge planning APIs and planning tab widgets."""

    _LOAD_FACTOR_BY_TIER: dict[str, tuple[float, float]] = {
        "low": (0.12, 0.24),
        "medium": (0.28, 0.42),
        "high": (0.46, 0.62),
    }

    def __init__(self, owner: MainWindow, error_logger: UiErrorLogger) -> None:
        self._owner = owner
        self._error_logger = error_logger

    def _append_log(self, message: str) -> None:
        self._owner._planning_output.appendPlainText(message)

    def _horizon_or_none(self) -> float | None:
        value = float(self._owner._planning_horizon.value())
        return None if value <= 1e-12 else value

    def _current_planning_options(self) -> dict[str, Any]:
        return {
            "planner": self._owner._planning_planner.currentText().strip() or "np_edf",
            "lp_objective": self._owner._planning_lp_objective.currentText().strip() or "response_time",
            "task_scope": self._owner._planning_task_scope.currentText().strip() or "sync_only",
            "include_non_rt": bool(self._owner._planning_include_non_rt.isChecked()),
            "horizon": self._horizon_or_none(),
            "time_limit_seconds": float(self._owner._planning_time_limit.value()),
            "max_iterations": int(self._owner._planning_wcrt_max_iterations.value()),
            "epsilon": float(self._owner._planning_wcrt_epsilon.value()),
        }

    def _prepare_spec(self) -> tuple[object, dict[str, Any]] | None:
        if not self._owner._sync_form_to_text_if_dirty():
            return None
        try:
            payload = self._owner._read_editor_payload()
            spec = self._owner._loader.load_data(payload)
        except (ConfigError, ValueError, TypeError, yaml.YAMLError) as exc:
            self._error_logger("planning_prepare_spec", exc)
            QMessageBox.critical(self._owner, "Planning failed", f"Invalid config: {exc}")
            self._owner._status_label.setText("Planning blocked by invalid config")
            return None
        return spec, payload

    @staticmethod
    def _set_table_rows(table: QTableWidget, rows: list[list[Any]]) -> None:
        table.blockSignals(True)
        try:
            table.setRowCount(len(rows))
            for row_idx, row_values in enumerate(rows):
                for col_idx, value in enumerate(row_values):
                    table.setItem(row_idx, col_idx, QTableWidgetItem("" if value is None else str(value)))
        finally:
            table.blockSignals(False)

    def _render_plan_table(self, plan_result: Any) -> None:
        rows: list[list[Any]] = []
        for window in sorted(
            plan_result.schedule_table.windows,
            key=lambda item: (item.start_time, item.end_time, item.core_id, item.segment_key),
        ):
            rows.append(
                [
                    window.segment_key,
                    window.task_id,
                    window.subtask_id,
                    window.segment_id,
                    window.core_id,
                    round(float(window.start_time), 6),
                    round(float(window.end_time), 6),
                    (
                        round(float(window.absolute_deadline), 6)
                        if window.absolute_deadline is not None
                        else None
                    ),
                ]
            )
        self._set_table_rows(self._owner._planning_windows_table, rows)

    def _render_wcrt_table(self, report: Any) -> None:
        rows = [
            [
                item.task_id,
                round(float(item.wcrt), 6),
                round(float(item.deadline), 6) if item.deadline is not None else None,
                bool(item.schedulable),
            ]
            for item in report.items
        ]
        self._set_table_rows(self._owner._planning_wcrt_table, rows)

    def _render_os_table(self, os_payload: dict[str, Any]) -> None:
        rows: list[list[Any]] = []
        for thread in os_payload.get("threads", []):
            if not isinstance(thread, dict):
                continue
            core_binding = thread.get("core_binding")
            if isinstance(core_binding, list):
                core_binding = ",".join(str(item) for item in core_binding)
            rows.append(
                [
                    thread.get("task_id"),
                    thread.get("priority"),
                    core_binding,
                    thread.get("primary_core"),
                    thread.get("window_count"),
                    thread.get("deadline"),
                    thread.get("total_wcet"),
                ]
            )
        self._set_table_rows(self._owner._planning_os_table, rows)

    def _run_plan(self, spec: object, *, options: dict[str, Any]) -> Any:
        spec_fingerprint = sim_api.model_spec_fingerprint(spec)
        plan_result = sim_api.plan_static(
            spec,
            planner=str(options["planner"]),
            task_scope=str(options["task_scope"]),
            include_non_rt=bool(options["include_non_rt"]),
            horizon=options["horizon"],
            lp_objective=str(options["lp_objective"]),
            time_limit_seconds=float(options["time_limit_seconds"]),
        )
        self._owner._latest_plan_result = plan_result
        self._owner._latest_plan_spec_fingerprint = spec_fingerprint
        self._owner._latest_planning_wcrt_report = None
        self._owner._latest_planning_os_payload = None
        self._render_plan_table(plan_result)
        return plan_result

    def _require_matching_latest_plan(self, *, spec: object, action_name: str) -> bool:
        plan_result = self._owner._latest_plan_result
        if plan_result is None:
            return True
        current_spec_fingerprint = sim_api.model_spec_fingerprint(spec)
        plan_spec_fingerprint = self._owner._latest_plan_spec_fingerprint
        if isinstance(plan_spec_fingerprint, str) and plan_spec_fingerprint.strip():
            plan_spec_fingerprint = plan_spec_fingerprint.strip()
        else:
            plan_spec_fingerprint = None
        if plan_spec_fingerprint == current_spec_fingerprint:
            return True
        self._append_log(
            f"[Planning][ERROR] {action_name} blocked: "
            f"plan/config mismatch, expected#{current_spec_fingerprint}, actual#{plan_spec_fingerprint or 'missing'}; "
            "run plan-static first."
        )
        self._owner._status_label.setText(f"{action_name} blocked by plan/config mismatch")
        return False

    def on_plan_static(self) -> None:
        prepared = self._prepare_spec()
        if prepared is None:
            return
        spec, _payload = prepared
        options = self._current_planning_options()
        try:
            plan_result = self._run_plan(spec, options=options)
            spec_fingerprint = sim_api.model_spec_fingerprint(spec)
        except Exception as exc:  # noqa: BLE001
            self._error_logger("planning_plan_static", exc)
            QMessageBox.critical(self._owner, "Planning failed", str(exc))
            self._owner._status_label.setText("Planning failed")
            return

        self._append_log(
            "[Planning] plan-static done: "
            f"planner={plan_result.planner}, feasible={plan_result.feasible}, "
            f"windows={len(plan_result.schedule_table.windows)}, spec_fingerprint={spec_fingerprint}"
        )
        self._owner._status_label.setText("Planning done")

    def on_plan_analyze_wcrt(self) -> None:
        prepared = self._prepare_spec()
        if prepared is None:
            return
        spec, _payload = prepared
        options = self._current_planning_options()
        try:
            plan_result = self._owner._latest_plan_result
            if plan_result is None:
                plan_result = self._run_plan(spec, options=options)
            elif not self._require_matching_latest_plan(spec=spec, action_name="analyze-wcrt"):
                return
            report = sim_api.analyze_wcrt(
                spec,
                plan_result.schedule_table,
                task_scope=str(options["task_scope"]),
                include_non_rt=bool(options["include_non_rt"]),
                horizon=options["horizon"],
                max_iterations=int(options["max_iterations"]),
                epsilon=float(options["epsilon"]),
            )
        except Exception as exc:  # noqa: BLE001
            self._error_logger("planning_analyze_wcrt", exc)
            QMessageBox.critical(self._owner, "WCRT failed", str(exc))
            self._owner._status_label.setText("WCRT failed")
            return

        self._owner._latest_planning_wcrt_report = report
        self._render_wcrt_table(report)
        self._append_log(
            "[Planning] analyze-wcrt done: "
            f"feasible={report.feasible}, task_count={len(report.items)}, "
            f"max_iterations={options['max_iterations']}, epsilon={options['epsilon']}"
        )
        self._owner._status_label.setText("WCRT done")

    def on_plan_export_os_config(self) -> None:
        prepared = self._prepare_spec()
        if prepared is None:
            return
        spec, _payload = prepared
        options = self._current_planning_options()
        try:
            plan_result = self._owner._latest_plan_result
            if plan_result is None:
                plan_result = self._run_plan(spec, options=options)
            elif not self._require_matching_latest_plan(spec=spec, action_name="export-os-config"):
                return
            os_payload = sim_api.export_os_config(plan_result.schedule_table)
        except Exception as exc:  # noqa: BLE001
            self._error_logger("planning_export_os", exc)
            QMessageBox.critical(self._owner, "OS export failed", str(exc))
            self._owner._status_label.setText("OS export failed")
            return

        self._owner._latest_planning_os_payload = dict(os_payload)
        self._render_os_table(os_payload)
        self._append_log(
            "[Planning] export-os-config done: "
            f"threads={len(os_payload.get('threads', []))}, "
            f"windows={len(os_payload.get('schedule_windows', []))}"
        )
        self._owner._status_label.setText("OS config done")

    @staticmethod
    def _split_budget(total_wcet: float, parts: int, rng: random.Random) -> list[float]:
        if parts <= 1:
            return [round(total_wcet, 3)]
        cuts = sorted(rng.random() for _ in range(parts - 1))
        segments = [cuts[0], *(cuts[idx] - cuts[idx - 1] for idx in range(1, len(cuts))), 1.0 - cuts[-1]]
        values = [max(0.05, total_wcet * ratio) for ratio in segments]
        correction = total_wcet - sum(values)
        values[-1] += correction
        return [round(max(0.01, value), 3) for value in values]

    def _build_random_task(self, *, task_idx: int, core_ids: list[str], rng: random.Random) -> dict[str, Any]:
        task_id = f"auto_t{task_idx}"
        load_tier = self._owner._planning_random_load_tier.currentText().strip() or "medium"
        min_factor, max_factor = self._LOAD_FACTOR_BY_TIER.get(load_tier, self._LOAD_FACTOR_BY_TIER["medium"])
        period = float(rng.choice([8.0, 10.0, 12.0, 16.0, 20.0]))
        load_factor = rng.uniform(min_factor, max_factor)
        total_wcet = round(max(0.15, period * load_factor), 3)
        deadline = round(max(total_wcet * 1.1, period * rng.uniform(0.72, 0.95)), 3)
        if total_wcet >= deadline:
            total_wcet = round(max(0.1, deadline * 0.82), 3)
        rule = self._owner._planning_random_rule.currentText().strip() or "single_chain"
        mapping_hint = core_ids[task_idx % len(core_ids)] if core_ids else "c0"

        if rule == "fork_join":
            entry_wcet = round(total_wcet * 0.35, 3)
            branch_budget = round(total_wcet - entry_wcet, 3)
            branch_pair = self._split_budget(branch_budget, 2, rng)
            subtasks = [
                {
                    "id": "s0",
                    "predecessors": [],
                    "successors": ["s1", "s2"],
                    "segments": [
                        {
                            "id": "seg0",
                            "index": 1,
                            "wcet": entry_wcet,
                            "required_resources": [],
                            "mapping_hint": mapping_hint,
                        }
                    ],
                },
                {
                    "id": "s1",
                    "predecessors": ["s0"],
                    "successors": [],
                    "segments": [
                        {
                            "id": "seg0",
                            "index": 1,
                            "wcet": branch_pair[0],
                            "required_resources": [],
                            "mapping_hint": mapping_hint,
                        }
                    ],
                },
                {
                    "id": "s2",
                    "predecessors": ["s0"],
                    "successors": [],
                    "segments": [
                        {
                            "id": "seg0",
                            "index": 1,
                            "wcet": branch_pair[1],
                            "required_resources": [],
                            "mapping_hint": mapping_hint,
                        }
                    ],
                },
            ]
        else:
            segment_count = int(rng.randint(1, 3))
            segments = []
            for segment_idx, wcet in enumerate(self._split_budget(total_wcet, segment_count, rng), start=1):
                segments.append(
                    {
                        "id": f"seg{segment_idx - 1}",
                        "index": segment_idx,
                        "wcet": wcet,
                        "required_resources": [],
                        "mapping_hint": mapping_hint,
                    }
                )
            subtasks = [{"id": "s0", "predecessors": [], "successors": [], "segments": segments}]

        task_type = "time_deterministic" if (task_idx % 2 == 0) else "dynamic_rt"
        return {
            "id": task_id,
            "name": task_id,
            "task_type": task_type,
            "period": period,
            "deadline": deadline,
            "arrival": round(rng.uniform(0.0, period * 0.2), 3),
            "subtasks": subtasks,
        }

    def on_generate_random_tasks(self) -> None:
        prepared = self._prepare_spec()
        if prepared is None:
            return
        _spec, payload = prepared
        seed = int(self._owner._planning_random_seed.value())
        task_count = int(self._owner._planning_random_task_count.value())
        rule = self._owner._planning_random_rule.currentText().strip() or "single_chain"
        tier = self._owner._planning_random_load_tier.currentText().strip() or "medium"

        rng = random.Random(seed)
        cores = payload.get("platform", {}).get("cores", [])
        core_ids = [str(item.get("id")) for item in cores if isinstance(item, dict) and item.get("id")]
        if not core_ids:
            core_ids = ["c0"]

        payload["tasks"] = [
            self._build_random_task(task_idx=idx, core_ids=core_ids, rng=rng)
            for idx in range(task_count)
        ]
        payload.setdefault("scheduler", {"name": "edf", "params": {}})
        payload.setdefault("sim", {"duration": 60.0, "seed": seed})
        payload["sim"]["seed"] = seed

        dumped = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
        self._owner._suspend_text_events = True
        try:
            self._owner._editor.setPlainText(dumped)
        finally:
            self._owner._suspend_text_events = False
        self._owner._config_doc = None
        self._owner._sync_text_to_form(show_message=False)

        self._append_log(
            "[Planning] random tasks generated: "
            f"seed={seed}, tier={tier}, rule={rule}, count={task_count}"
        )
        self._append_log(f"[Planning] random task ids: {json.dumps([task['id'] for task in payload['tasks']])}")
        self._owner._status_label.setText("Random tasks generated")
