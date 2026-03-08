"""Document/form synchronization helpers for ``MainWindow``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

import yaml

from rtos_sim.io import ConfigError
from rtos_sim.ui.config_doc import ConfigDocument
from rtos_sim.ui.gantt_helpers import safe_float


class UiErrorLogger(Protocol):
    def __call__(self, action: str, exc: Exception, **context: Any) -> None: ...


if TYPE_CHECKING:
    from rtos_sim.ui.app import MainWindow


class DocumentSyncController:
    """Keep config document synchronization logic out of ``MainWindow``."""

    def __init__(self, owner: MainWindow, error_logger: UiErrorLogger) -> None:
        self._owner = owner
        self._error_logger = error_logger

    def read_editor_payload(self) -> dict[str, Any]:
        text = self._owner._editor.toPlainText()
        payload = yaml.safe_load(text)
        if not isinstance(payload, dict):
            raise ConfigError("config root must be object")
        return payload

    def populate_form_from_payload(self, payload: dict[str, Any]) -> None:
        self._owner._dag_manual_positions_by_task.clear()
        self._owner._config_doc = ConfigDocument.from_payload(payload)
        self.populate_form_from_doc()

    def populate_form_from_doc(self) -> None:
        doc = self.ensure_config_doc()

        tasks = doc.list_tasks()
        resources = doc.list_resources()
        task_count = len(tasks)
        resource_count = len(resources)

        if task_count <= 0:
            self._owner._selected_task_index = -1
        else:
            self._owner._selected_task_index = min(max(self._owner._selected_task_index, 0), task_count - 1)

        if resource_count <= 0:
            self._owner._selected_resource_index = -1
        else:
            self._owner._selected_resource_index = min(
                max(self._owner._selected_resource_index, 0),
                resource_count - 1,
            )

        processor = doc.get_primary_processor()
        core = doc.get_primary_core()
        scheduler = doc.get_scheduler()
        scheduler_params = scheduler.get("params")
        params = scheduler_params if isinstance(scheduler_params, dict) else {}
        planning = doc.get_planning()
        sim = doc.get_sim()

        self._owner._suspend_form_events = True
        try:
            self._owner._form_processor_id.setText(str(processor.get("id", "CPU")))
            self._owner._form_processor_name.setText(str(processor.get("name", "cpu")))
            self._owner._form_processor_core_count.setValue(
                max(1, int(safe_float(processor.get("core_count"), 1)))
            )
            self._owner._form_processor_speed.setValue(safe_float(processor.get("speed_factor"), 1.0))

            self._owner._form_core_id.setText(str(core.get("id", "c0")))
            self._owner._form_core_speed.setValue(safe_float(core.get("speed_factor"), 1.0))

            self._owner._refresh_resource_table(doc)
            self._owner._refresh_task_table(doc)
            self._owner._refresh_selected_resource_fields(doc)
            self._owner._refresh_selected_task_fields(doc)

            self._owner._set_combo_value(
                self._owner._form_scheduler_name,
                str(scheduler.get("name", "edf")),
            )
            self._owner._set_combo_value(
                self._owner._form_tie_breaker,
                str(params.get("tie_breaker", "fifo")),
            )
            self._owner._form_allow_preempt.setChecked(self._owner._to_bool(params.get("allow_preempt"), True))
            self._owner._set_combo_value(
                self._owner._form_event_id_mode,
                str(params.get("event_id_mode", "deterministic")),
            )
            self._owner._set_combo_value(
                self._owner._form_resource_acquire_policy,
                str(params.get("resource_acquire_policy", "legacy_sequential")),
            )
            self._owner._form_sim_duration.setValue(safe_float(sim.get("duration"), 10.0))
            self._owner._form_sim_seed.setValue(int(safe_float(sim.get("seed"), 42)))

            self._owner._planning_enabled.setChecked(self._owner._to_bool(planning.get("enabled"), False))
            self._owner._set_combo_value(
                self._owner._planning_planner,
                str(planning.get("planner", "np_edf")),
            )
            self._owner._set_combo_value(
                self._owner._planning_lp_objective,
                str(planning.get("lp_objective", "response_time")),
            )
            self._owner._set_combo_value(
                self._owner._planning_task_scope,
                str(planning.get("task_scope", "sync_only")),
            )
            self._owner._planning_include_non_rt.setChecked(
                self._owner._to_bool(planning.get("include_non_rt"), False)
            )
            self._owner._planning_horizon.setValue(safe_float(planning.get("horizon"), 0.0))
        finally:
            self._owner._suspend_form_events = False

        self._owner._refresh_dag_widgets(doc)

    def ensure_config_doc(self) -> ConfigDocument:
        if self._owner._config_doc is not None:
            return self._owner._config_doc
        try:
            payload = self.read_editor_payload()
        except (ConfigError, ValueError, TypeError, yaml.YAMLError) as exc:
            self._error_logger("ensure_config_doc_fallback", exc)
            payload = {}
        self._owner._config_doc = ConfigDocument.from_payload(payload)
        return self._owner._config_doc

    def apply_form_to_payload(self, base_payload: dict[str, Any]) -> dict[str, Any]:
        doc = ConfigDocument.from_payload(base_payload)
        self.apply_form_to_document(doc)
        self._owner._config_doc = doc
        return doc.to_payload()

    def apply_form_to_document(self, doc: ConfigDocument) -> None:
        processor_id = self._owner._form_processor_id.text().strip() or "CPU"
        core_id = self._owner._form_core_id.text().strip() or "c0"

        doc.patch_primary_processor(
            {
                "id": processor_id,
                "name": self._owner._form_processor_name.text().strip() or "cpu",
                "core_count": int(self._owner._form_processor_core_count.value()),
                "speed_factor": float(self._owner._form_processor_speed.value()),
            }
        )
        doc.patch_primary_core(
            {
                "id": core_id,
                "type_id": processor_id,
                "speed_factor": float(self._owner._form_core_speed.value()),
            }
        )

        resources = doc.list_resources()
        if self._owner._form_resource_enabled.isChecked():
            if not resources:
                self._owner._selected_resource_index = doc.add_resource()
            elif self._owner._selected_resource_index < 0:
                self._owner._selected_resource_index = 0
            if doc.list_resources():
                self._owner._selected_resource_index = min(
                    self._owner._selected_resource_index,
                    len(doc.list_resources()) - 1,
                )
                doc.patch_resource(
                    self._owner._selected_resource_index,
                    {
                        "id": self._owner._form_resource_id.text().strip() or "r0",
                        "name": self._owner._form_resource_name.text().strip() or "lock",
                        "bound_core_id": self._owner._form_resource_bound_core.text().strip() or core_id,
                        "protocol": self._owner._form_resource_protocol.currentText().strip() or "mutex",
                    },
                )
        else:
            for idx in range(len(resources) - 1, -1, -1):
                doc.remove_resource(idx)
            self._owner._selected_resource_index = -1

        tasks = doc.list_tasks()
        if not tasks:
            self._owner._selected_task_index = doc.add_task()
            tasks = doc.list_tasks()
        if self._owner._selected_task_index < 0:
            self._owner._selected_task_index = 0
        self._owner._selected_task_index = min(self._owner._selected_task_index, len(tasks) - 1)

        task_type = self._owner._form_task_type.currentText().strip() or "dynamic_rt"
        period_value = self._owner._parse_optional_float(
            self._owner._form_task_period.text(),
            "task.period",
        )
        deadline_value = self._owner._parse_optional_float(
            self._owner._form_task_deadline.text(),
            "task.deadline",
        )
        if task_type == "time_deterministic":
            if period_value is None:
                period_value = 10.0
            if deadline_value is None:
                deadline_value = period_value
        elif task_type != "non_rt" and deadline_value is None:
            deadline_value = 10.0

        doc.patch_task(
            self._owner._selected_task_index,
            {
                "id": self._owner._form_task_id.text().strip() or "t0",
                "name": self._owner._form_task_name.text().strip() or "task",
                "task_type": task_type,
                "arrival": float(self._owner._form_task_arrival.value()),
                "period": period_value,
                "deadline": deadline_value,
                "abort_on_miss": bool(self._owner._form_task_abort_on_miss.isChecked()),
            },
        )

        subtasks = doc.list_subtasks(self._owner._selected_task_index)
        selected_subtask_index = 0
        if subtasks:
            for idx, subtask in enumerate(subtasks):
                if str(subtask.get("id") or "") == self._owner._selected_subtask_id:
                    selected_subtask_index = idx
                    break
        else:
            selected_subtask_index = doc.add_subtask(self._owner._selected_task_index)

        doc.patch_subtask(
            self._owner._selected_task_index,
            selected_subtask_index,
            {"id": self._owner._form_subtask_id.text().strip() or "s0"},
        )
        selected_subtask = doc.get_subtask(self._owner._selected_task_index, selected_subtask_index)
        self._owner._selected_subtask_id = str(selected_subtask.get("id") or "s0")

        required_resources = [
            token.strip()
            for token in self._owner._form_segment_required_resources.text().split(",")
            if token.strip()
        ]
        mapping_hint = self._owner._form_segment_mapping_hint.text().strip()
        doc.patch_segment(
            self._owner._selected_task_index,
            selected_subtask_index,
            {
                "id": self._owner._form_segment_id.text().strip() or "seg0",
                "index": 1,
                "wcet": float(self._owner._form_segment_wcet.value()),
                "mapping_hint": mapping_hint or None,
                "required_resources": required_resources,
                "preemptible": bool(self._owner._form_segment_preemptible.isChecked()),
            },
        )

        doc.patch_scheduler(
            self._owner._form_scheduler_name.currentText().strip() or "edf",
            {
                "tie_breaker": self._owner._form_tie_breaker.currentText().strip() or "fifo",
                "allow_preempt": bool(self._owner._form_allow_preempt.isChecked()),
                "event_id_mode": self._owner._form_event_id_mode.currentText().strip() or "deterministic",
                "resource_acquire_policy": self._owner._form_resource_acquire_policy.currentText().strip()
                or "legacy_sequential",
            },
        )
        doc.patch_sim(
            float(self._owner._form_sim_duration.value()),
            int(self._owner._form_sim_seed.value()),
        )
        planning_horizon = float(self._owner._planning_horizon.value())
        doc.patch_planning(
            {
                "enabled": bool(self._owner._planning_enabled.isChecked()),
                "planner": self._owner._planning_planner.currentText().strip() or "np_edf",
                "lp_objective": self._owner._planning_lp_objective.currentText().strip()
                or "response_time",
                "task_scope": self._owner._planning_task_scope.currentText().strip() or "sync_only",
                "include_non_rt": bool(self._owner._planning_include_non_rt.isChecked()),
                "horizon": None if planning_horizon <= 1e-12 else planning_horizon,
            }
        )
