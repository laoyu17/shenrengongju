"""Time-deterministic readiness proof/checks."""

from __future__ import annotations

from typing import Any

from rtos_sim.analysis.audit_report_builder import CheckOutcome, make_check_outcome

AUDIT_TIME_DETERMINISTIC_PROOF_VERSION = "0.1"


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _parse_segment_template(segment_key: str) -> tuple[str, str, str] | None:
    parts = segment_key.rsplit(":", 2)
    if len(parts) != 3:
        return None
    job_id, subtask_id, segment_id = parts
    if not job_id or not subtask_id or not segment_id:
        return None
    task_parts = job_id.rsplit("@", 1)
    if len(task_parts) != 2 or not task_parts[0]:
        return None
    return task_parts[0], subtask_id, segment_id


def analyze_time_deterministic_ready(events: list[dict[str, Any]]) -> dict[str, Any]:
    tolerance = 1e-9
    job_hyper_period: dict[str, float] = {}
    phase_references: dict[tuple[str, str, str, int], float] = {}
    seen_window_offsets: set[tuple[str, str, str, int, int]] = set()
    issue_samples: list[dict[str, Any]] = []
    deterministic_segment_ready_count = 0
    deterministic_tasks: set[str] = set()
    max_ready_lag = 0.0
    max_phase_jitter = 0.0

    for event in events:
        if event.get("type") != "JobReleased":
            continue
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        job_id = event.get("job_id")
        hyper_period = _as_float(payload.get("deterministic_hyper_period"))
        if not isinstance(job_id, str) or not job_id or hyper_period is None or hyper_period <= tolerance:
            continue
        job_hyper_period[job_id] = hyper_period

    for event in events:
        if event.get("type") != "SegmentReady":
            continue
        payload = event.get("payload", {})
        if not isinstance(payload, dict):
            continue
        if "deterministic_ready_time" not in payload:
            continue

        deterministic_segment_ready_count += 1
        segment_key = payload.get("segment_key")
        if not isinstance(segment_key, str) or not segment_key:
            issue_samples.append(
                {
                    "event_id": event.get("event_id"),
                    "reason": "missing_segment_key",
                }
            )
            continue

        template = _parse_segment_template(segment_key)
        if template is None:
            issue_samples.append(
                {
                    "event_id": event.get("event_id"),
                    "reason": "invalid_segment_key",
                    "segment_key": segment_key,
                }
            )
            continue
        task_id, subtask_id, segment_id = template
        deterministic_tasks.add(task_id)

        deterministic_ready_time = _as_float(payload.get("deterministic_ready_time"))
        offset_index_raw = payload.get("deterministic_offset_index")
        window_id_raw = payload.get("deterministic_window_id")
        observed_time = _as_float(event.get("time"))

        if deterministic_ready_time is None:
            issue_samples.append(
                {
                    "event_id": event.get("event_id"),
                    "reason": "invalid_deterministic_ready_time",
                    "segment_key": segment_key,
                }
            )
            continue
        if observed_time is None:
            issue_samples.append(
                {
                    "event_id": event.get("event_id"),
                    "reason": "invalid_event_time",
                    "segment_key": segment_key,
                }
            )
            continue
        if not isinstance(offset_index_raw, int):
            issue_samples.append(
                {
                    "event_id": event.get("event_id"),
                    "reason": "missing_deterministic_offset_index",
                    "segment_key": segment_key,
                }
            )
            continue
        if not isinstance(window_id_raw, int):
            issue_samples.append(
                {
                    "event_id": event.get("event_id"),
                    "reason": "missing_deterministic_window_id",
                    "segment_key": segment_key,
                }
            )
            continue

        window_key = (task_id, subtask_id, segment_id, window_id_raw, offset_index_raw)
        if window_key in seen_window_offsets:
            issue_samples.append(
                {
                    "event_id": event.get("event_id"),
                    "reason": "duplicate_window_offset",
                    "segment_key": segment_key,
                    "deterministic_window_id": window_id_raw,
                    "deterministic_offset_index": offset_index_raw,
                }
            )
        else:
            seen_window_offsets.add(window_key)

        ready_lag = abs(observed_time - deterministic_ready_time)
        max_ready_lag = max(max_ready_lag, ready_lag)
        if ready_lag > tolerance:
            issue_samples.append(
                {
                    "event_id": event.get("event_id"),
                    "reason": "deterministic_ready_time_mismatch",
                    "segment_key": segment_key,
                    "observed_time": observed_time,
                    "deterministic_ready_time": deterministic_ready_time,
                    "lag": ready_lag,
                }
            )

        job_id = event.get("job_id")
        hyper_period = job_hyper_period.get(job_id) if isinstance(job_id, str) and job_id else None
        if hyper_period is None or hyper_period <= tolerance:
            continue

        phase = deterministic_ready_time % hyper_period
        phase_key = (task_id, subtask_id, segment_id, offset_index_raw)
        baseline = phase_references.get(phase_key)
        if baseline is None:
            phase_references[phase_key] = phase
            continue
        diff = abs(phase - baseline)
        phase_jitter = min(diff, abs(hyper_period - diff))
        max_phase_jitter = max(max_phase_jitter, phase_jitter)
        if phase_jitter > tolerance:
            issue_samples.append(
                {
                    "event_id": event.get("event_id"),
                    "reason": "deterministic_phase_jitter",
                    "segment_key": segment_key,
                    "deterministic_offset_index": offset_index_raw,
                    "deterministic_window_id": window_id_raw,
                    "expected_phase": baseline,
                    "observed_phase": phase,
                    "hyper_period": hyper_period,
                    "phase_jitter": phase_jitter,
                }
            )

    return {
        "proof_asset_version": AUDIT_TIME_DETERMINISTIC_PROOF_VERSION,
        "deterministic_segment_ready_count": deterministic_segment_ready_count,
        "deterministic_task_count": len(deterministic_tasks),
        "phase_reference_count": len(phase_references),
        "max_ready_lag": max_ready_lag,
        "max_phase_jitter": max_phase_jitter,
        "issue_count": len(issue_samples),
        "issue_samples": issue_samples[:20],
    }


def evaluate_time_deterministic_ready_consistency(
    time_deterministic_proof_assets: dict[str, Any],
) -> CheckOutcome:
    time_deterministic_issues = time_deterministic_proof_assets.get("issue_samples", [])

    issues: list[dict[str, Any]] = []
    if time_deterministic_issues:
        issues.append(
            {
                "rule": "time_deterministic_ready_consistency",
                "severity": "error",
                "message": (
                    "time_deterministic SegmentReady events must stay aligned to "
                    "deterministic_ready_time and hyper-period phase references"
                ),
                "samples": time_deterministic_issues,
            }
        )

    return make_check_outcome(
        rule="time_deterministic_ready_consistency",
        passed=not time_deterministic_issues,
        issues=issues,
        check_payload={
            "deterministic_segment_ready_count": time_deterministic_proof_assets[
                "deterministic_segment_ready_count"
            ],
            "deterministic_task_count": time_deterministic_proof_assets["deterministic_task_count"],
        },
    )
