"""Default metrics implementation."""

from __future__ import annotations

from collections import defaultdict

from rtos_sim.events import EventType, SimEvent

from .base import IMetric


class CoreMetrics(IMetric):
    """Aggregate key simulation metrics from event stream."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._job_release: dict[str, float] = {}
        self._job_deadline: dict[str, float] = {}
        self._job_complete: dict[str, float] = {}
        self._deadline_miss_jobs: set[str] = set()
        self._running: dict[str, tuple[float, str]] = {}
        self._core_busy: dict[str, float] = defaultdict(float)
        self._preempt_count = 0
        self._migrate_count = 0
        self._event_count = 0
        self._max_time = 0.0

    def consume(self, event: SimEvent) -> None:
        self._event_count += 1
        self._max_time = max(self._max_time, event.time)

        if event.type == EventType.JOB_RELEASED:
            if event.job_id:
                self._job_release[event.job_id] = event.time
                deadline = event.payload.get("absolute_deadline")
                if isinstance(deadline, (int, float)):
                    self._job_deadline[event.job_id] = float(deadline)

        elif event.type == EventType.SEGMENT_START:
            segment_key = self._segment_runtime_key(event)
            if segment_key and event.core_id:
                self._running[segment_key] = (event.time, event.core_id)

        elif event.type == EventType.SEGMENT_END:
            segment_key = self._segment_runtime_key(event)
            if segment_key and segment_key in self._running:
                start, core = self._running.pop(segment_key)
                self._core_busy[core] += max(0.0, event.time - start)

        elif event.type == EventType.PREEMPT:
            segment_key = self._segment_runtime_key(event)
            if segment_key and segment_key in self._running:
                start, core = self._running.pop(segment_key)
                self._core_busy[core] += max(0.0, event.time - start)
            self._preempt_count += 1

        elif event.type == EventType.MIGRATE:
            self._migrate_count += 1

        elif event.type == EventType.DEADLINE_MISS:
            if event.job_id:
                self._deadline_miss_jobs.add(event.job_id)

        elif event.type == EventType.JOB_COMPLETE and event.job_id:
            self._job_complete[event.job_id] = event.time

    def _segment_runtime_key(self, event: SimEvent) -> str | None:
        segment_key = event.payload.get("segment_key")
        if isinstance(segment_key, str) and segment_key:
            return segment_key
        if event.segment_id:
            return event.segment_id
        return None

    def report(self) -> dict:
        response_times: list[float] = []
        lateness_values: list[float] = []

        for job_id, complete_time in self._job_complete.items():
            release_time = self._job_release.get(job_id)
            if release_time is not None:
                response_times.append(complete_time - release_time)
            deadline = self._job_deadline.get(job_id)
            if deadline is not None:
                lateness_values.append(max(0.0, complete_time - deadline))

        total_jobs = max(1, len(self._job_release))
        avg_response = sum(response_times) / len(response_times) if response_times else 0.0
        avg_lateness = sum(lateness_values) / len(lateness_values) if lateness_values else 0.0

        utilization = {
            core_id: (busy_time / self._max_time if self._max_time > 0 else 0.0)
            for core_id, busy_time in self._core_busy.items()
        }

        return {
            "jobs_released": len(self._job_release),
            "jobs_completed": len(self._job_complete),
            "deadline_miss_count": len(self._deadline_miss_jobs),
            "deadline_miss_ratio": len(self._deadline_miss_jobs) / total_jobs,
            "avg_response_time": avg_response,
            "avg_lateness": avg_lateness,
            "preempt_count": self._preempt_count,
            "migrate_count": self._migrate_count,
            "core_utilization": utilization,
            "event_count": self._event_count,
            "max_time": self._max_time,
        }
