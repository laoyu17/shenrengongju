"""Table-driven execution time model."""

from __future__ import annotations

from typing import Any

from .base import IExecutionTimeModel


class TableBasedExecutionTimeModel(IExecutionTimeModel):
    """Apply table-configured scaling factors on top of baseline WCET/core_speed."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        config = params or {}
        raw_default_scale = config.get("default_scale", 1.0)
        self._default_scale = float(raw_default_scale)
        if self._default_scale <= 0:
            raise ValueError("scheduler.params.etm_params.default_scale must be > 0")

        raw_table = config.get("table", {})
        if not isinstance(raw_table, dict):
            raise ValueError("scheduler.params.etm_params.table must be object")

        self._scale_table: dict[str, float] = {}
        for raw_key, raw_scale in raw_table.items():
            key = str(raw_key).strip()
            if not key:
                raise ValueError("scheduler.params.etm_params.table contains empty key")
            scale = float(raw_scale)
            if scale <= 0:
                raise ValueError(f"scheduler.params.etm_params.table['{key}'] must be > 0")
            self._scale_table[key] = scale

    def estimate(
        self,
        segment_wcet: float,
        core_speed: float,
        now: float,  # noqa: ARG002
        *,
        task_id: str | None = None,
        subtask_id: str | None = None,
        segment_id: str | None = None,
        core_id: str | None = None,
    ) -> float:
        baseline = segment_wcet / core_speed
        scale = self._resolve_scale(
            task_id=task_id,
            subtask_id=subtask_id,
            segment_id=segment_id,
            core_id=core_id,
        )
        return baseline * scale

    def on_exec(self, segment_key: str, core_id: str, dt: float) -> None:  # noqa: ARG002
        return

    def _resolve_scale(
        self,
        *,
        task_id: str | None,
        subtask_id: str | None,
        segment_id: str | None,
        core_id: str | None,
    ) -> float:
        candidates = self._build_lookup_candidates(
            task_id=task_id,
            subtask_id=subtask_id,
            segment_id=segment_id,
            core_id=core_id,
        )
        for key in candidates:
            scale = self._scale_table.get(key)
            if scale is not None:
                return scale
        return self._default_scale

    @staticmethod
    def _build_lookup_candidates(
        *,
        task_id: str | None,
        subtask_id: str | None,
        segment_id: str | None,
        core_id: str | None,
    ) -> list[str]:
        if not segment_id:
            return []
        core = core_id or "*"
        candidates = [f"{segment_id}@{core}", f"{segment_id}@*"]
        if task_id and subtask_id:
            prefix = f"{task_id}/{subtask_id}/{segment_id}"
            candidates = [f"{prefix}@{core}", f"{prefix}@*"] + candidates
        return candidates
