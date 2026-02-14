"""Scheduler interfaces and base classes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from rtos_sim.model import Decision, DecisionAction, ReadySegment, ScheduleSnapshot


@dataclass(slots=True)
class ScheduleContext:
    core_ids: list[str]


class IScheduler(ABC):
    """Scheduling interface used by simulation core."""

    def init(self, context: ScheduleContext) -> None:
        """Initialize scheduler with immutable platform context."""

    def on_release(self, job_id: str) -> None:
        """Hook called when a job is released."""

    def on_complete(self, job_id: str) -> None:
        """Hook called when a job completes."""

    def on_segment_ready(self, segment_key: str) -> None:
        """Hook called when a segment enters the ready queue."""

    @abstractmethod
    def schedule(self, now: float, snapshot: ScheduleSnapshot) -> list[Decision]:
        """Produce decisions from current scheduler snapshot."""


class PriorityScheduler(IScheduler, ABC):
    """Priority-based multi-core scheduler with side-effect free decisions."""

    def __init__(self) -> None:
        self._core_ids: list[str] = []

    def init(self, context: ScheduleContext) -> None:
        self._core_ids = list(context.core_ids)

    def on_release(self, job_id: str) -> None:  # noqa: ARG002
        return

    def on_complete(self, job_id: str) -> None:  # noqa: ARG002
        return

    def on_segment_ready(self, segment_key: str) -> None:  # noqa: ARG002
        return

    @abstractmethod
    def priority_key(self, segment: ReadySegment, now: float) -> tuple:
        """Return a sortable key. Lower tuple = higher priority."""

    def schedule(self, now: float, snapshot: ScheduleSnapshot) -> list[Decision]:
        ready = list(snapshot.ready_segments)
        core_states = {core.core_id: core for core in snapshot.core_states}
        running_segment_to_core = {
            core.running_segment.key: core.core_id
            for core in snapshot.core_states
            if core.running_segment is not None
        }

        assignments: dict[str, ReadySegment | None] = {core_id: None for core_id in self._core_ids}
        used_segment_keys: set[str] = set()

        for core_id in self._core_ids:
            current_segment = core_states[core_id].running_segment if core_id in core_states else None
            candidates = [
                segment
                for segment in ready
                if segment.key not in used_segment_keys
                and (segment.mapping_hint is None or segment.mapping_hint == core_id)
            ]
            if current_segment and current_segment.key not in used_segment_keys:
                candidates.append(current_segment)
            if not candidates:
                continue
            candidates.sort(key=lambda seg: self.priority_key(seg, now))
            chosen = candidates[0]
            assignments[core_id] = chosen
            used_segment_keys.add(chosen.key)

        decisions: list[Decision] = []
        preempted_cores: set[str] = set()

        for core_id in self._core_ids:
            state = core_states.get(core_id)
            current_key = state.running_segment_key if state else None
            chosen = assignments[core_id]
            chosen_key = chosen.key if chosen else None

            if current_key == chosen_key:
                continue

            if current_key is not None and chosen_key is not None:
                decisions.append(
                    Decision(
                        action=DecisionAction.PREEMPT,
                        job_id=current_key.split(":", 1)[0],
                        segment_id=current_key,
                        from_core=core_id,
                        to_core=None,
                        reason="higher-priority segment selected",
                    )
                )
                preempted_cores.add(core_id)

            if chosen is None:
                if current_key is None:
                    decisions.append(
                        Decision(
                            action=DecisionAction.IDLE,
                            job_id=None,
                            segment_id=None,
                            from_core=core_id,
                            to_core=core_id,
                            reason="no ready segment",
                        )
                    )
                continue

            source_core = running_segment_to_core.get(chosen_key)
            if source_core and source_core != core_id and source_core not in preempted_cores:
                decisions.append(
                    Decision(
                        action=DecisionAction.MIGRATE,
                        job_id=chosen.job_id,
                        segment_id=chosen.key,
                        from_core=source_core,
                        to_core=core_id,
                        reason="rebalance to target core",
                    )
                )

            decisions.append(
                Decision(
                    action=DecisionAction.DISPATCH,
                    job_id=chosen.job_id,
                    segment_id=chosen.key,
                    from_core=None,
                    to_core=core_id,
                    reason="priority dispatch",
                )
            )

        return decisions
