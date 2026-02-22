from __future__ import annotations

import json
from pathlib import Path

from rtos_sim.cli.main import main
import yaml


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_cli_validate_ok() -> None:
    code = main(["validate", "-c", str(EXAMPLES / "at01_single_dag_single_core.yaml")])
    assert code == 0


def test_cli_run_outputs(tmp_path: Path) -> None:
    events_out = tmp_path / "events.jsonl"
    metrics_out = tmp_path / "metrics.json"

    code = main(
        [
            "run",
            "-c",
            str(EXAMPLES / "at01_single_dag_single_core.yaml"),
            "--events-out",
            str(events_out),
            "--metrics-out",
            str(metrics_out),
        ]
    )
    assert code == 0
    assert events_out.exists()
    assert metrics_out.exists()

    first_line = events_out.read_text(encoding="utf-8").splitlines()[0]
    assert first_line
    metrics = json.loads(metrics_out.read_text(encoding="utf-8"))
    assert "jobs_completed" in metrics


def test_cli_batch_run_outputs_summary(tmp_path: Path) -> None:
    base_config = tmp_path / "base.yaml"
    base_config.write_text(
        (EXAMPLES / "at01_single_dag_single_core.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    batch_config = tmp_path / "batch.yaml"
    batch_config.write_text(
        """
version: "0.1"
base_config: "base.yaml"
output_dir: "out"
factors:
  scheduler.name: ["edf", "rm"]
  sim.seed: [11, 22]
""".strip(),
        encoding="utf-8",
    )

    code = main(["batch-run", "-b", str(batch_config)])
    assert code == 0

    summary_json = tmp_path / "out" / "summary.json"
    summary_csv = tmp_path / "out" / "summary.csv"
    assert summary_json.exists()
    assert summary_csv.exists()

    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    assert payload["total_runs"] == 4
    assert payload["succeeded_runs"] == 4
    assert payload["failed_runs"] == 0


def test_cli_batch_run_strict_mode_returns_non_zero_on_failed_runs(tmp_path: Path) -> None:
    base_config = tmp_path / "base.yaml"
    base_config.write_text(
        (EXAMPLES / "at01_single_dag_single_core.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    batch_config = tmp_path / "batch.yaml"
    batch_config.write_text(
        """
version: "0.1"
base_config: "base.yaml"
output_dir: "out"
factors:
  tasks.*.task_type: ["dynamic_rt", "bad_type"]
""".strip(),
        encoding="utf-8",
    )

    code = main(["batch-run", "-b", str(batch_config), "--strict-fail-on-error"])
    assert code == 2

    payload = json.loads((tmp_path / "out" / "summary.json").read_text(encoding="utf-8"))
    assert payload["total_runs"] == 2
    assert payload["succeeded_runs"] == 1
    assert payload["failed_runs"] == 1


def test_cli_compare_outputs_json_and_csv(tmp_path: Path) -> None:
    left = tmp_path / "left.json"
    right = tmp_path / "right.json"
    out_json = tmp_path / "compare.json"
    out_csv = tmp_path / "compare.csv"
    left.write_text(
        json.dumps(
            {
                "jobs_completed": 5,
                "deadline_miss_count": 1,
                "core_utilization": {"c0": 0.5},
            }
        ),
        encoding="utf-8",
    )
    right.write_text(
        json.dumps(
            {
                "jobs_completed": 6,
                "deadline_miss_count": 0,
                "core_utilization": {"c0": 0.75},
            }
        ),
        encoding="utf-8",
    )

    code = main(
        [
            "compare",
            "--left-metrics",
            str(left),
            "--right-metrics",
            str(right),
            "--left-label",
            "base",
            "--right-label",
            "new",
            "--out-json",
            str(out_json),
            "--out-csv",
            str(out_csv),
        ]
    )
    assert code == 0
    assert out_json.exists()
    assert out_csv.exists()
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["left_label"] == "base"
    assert payload["right_label"] == "new"
    assert any(row["metric"] == "jobs_completed" for row in payload["scalar_metrics"])


def test_cli_inspect_model_outputs_json_and_csv(tmp_path: Path) -> None:
    out_json = tmp_path / "model_relations.json"
    out_csv = tmp_path / "model_relations.csv"

    code = main(
        [
            "inspect-model",
            "-c",
            str(EXAMPLES / "at02_resource_mutex.yaml"),
            "--out-json",
            str(out_json),
            "--out-csv",
            str(out_csv),
        ]
    )
    assert code == 0
    assert out_json.exists()
    assert out_csv.exists()

    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["summary"]["task_count"] == 2
    assert any(row["task_id"] == "low" for row in payload["task_to_cores"])

    header = out_csv.read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith("category,")


def test_cli_validate_rejects_unknown_scheduler(tmp_path: Path) -> None:
    config = tmp_path / "unknown_scheduler.yaml"
    config.write_text(
        """
version: "0.2"
platform:
  processor_types:
    - id: CPU
      name: cpu
      core_count: 1
      speed_factor: 1.0
  cores:
    - id: c0
      type_id: CPU
      speed_factor: 1.0
resources: []
tasks:
  - id: t0
    name: task
    task_type: dynamic_rt
    deadline: 10
    arrival: 0
    subtasks:
      - id: s0
        predecessors: []
        successors: []
        segments:
          - id: seg0
            index: 1
            wcet: 1
scheduler:
  name: not_registered
  params: {}
sim:
  duration: 5
  seed: 1
""".strip(),
        encoding="utf-8",
    )

    code = main(["validate", "-c", str(config)])
    assert code == 1


def test_cli_run_rejects_unknown_scheduler_without_uncaught_exception(tmp_path: Path) -> None:
    config = tmp_path / "unknown_scheduler.yaml"
    config.write_text(
        """
version: "0.2"
platform:
  processor_types:
    - id: CPU
      name: cpu
      core_count: 1
      speed_factor: 1.0
  cores:
    - id: c0
      type_id: CPU
      speed_factor: 1.0
resources: []
tasks:
  - id: t0
    name: task
    task_type: dynamic_rt
    deadline: 10
    arrival: 0
    subtasks:
      - id: s0
        predecessors: []
        successors: []
        segments:
          - id: seg0
            index: 1
            wcet: 1
scheduler:
  name: not_registered
  params: {}
sim:
  duration: 5
  seed: 1
""".strip(),
        encoding="utf-8",
    )

    code = main(["run", "-c", str(config)])
    assert code == 1


def test_cli_run_step_mode_and_csv_export(tmp_path: Path) -> None:
    events_out = tmp_path / "events.jsonl"
    metrics_out = tmp_path / "metrics.json"
    events_csv_out = tmp_path / "events.csv"

    code = main(
        [
            "run",
            "-c",
            str(EXAMPLES / "at01_single_dag_single_core.yaml"),
            "--until",
            "5",
            "--step",
            "--delta",
            "0.5",
            "--events-out",
            str(events_out),
            "--events-csv-out",
            str(events_csv_out),
            "--metrics-out",
            str(metrics_out),
        ]
    )
    assert code == 0
    assert events_out.exists()
    assert metrics_out.exists()
    assert events_csv_out.exists()
    header = events_csv_out.read_text(encoding="utf-8").splitlines()[0]
    assert header == "event_id,seq,correlation_id,time,type,job_id,segment_id,core_id,resource_id,payload"


def test_cli_run_pause_at_stops_early(tmp_path: Path) -> None:
    events_out = tmp_path / "events.jsonl"
    metrics_out = tmp_path / "metrics.json"

    code = main(
        [
            "run",
            "-c",
            str(EXAMPLES / "at01_single_dag_single_core.yaml"),
            "--pause-at",
            "2",
            "--events-out",
            str(events_out),
            "--metrics-out",
            str(metrics_out),
        ]
    )
    assert code == 0
    metrics = json.loads(metrics_out.read_text(encoding="utf-8"))
    assert metrics["max_time"] <= 2.0 + 1e-6

    event_times = [
        json.loads(line)["time"]
        for line in events_out.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert max(event_times) <= 2.0 + 1e-6


def test_cli_run_writes_audit_report(tmp_path: Path) -> None:
    events_out = tmp_path / "events.jsonl"
    metrics_out = tmp_path / "metrics.json"
    audit_out = tmp_path / "audit.json"

    code = main(
        [
            "run",
            "-c",
            str(EXAMPLES / "at01_single_dag_single_core.yaml"),
            "--events-out",
            str(events_out),
            "--metrics-out",
            str(metrics_out),
            "--audit-out",
            str(audit_out),
        ]
    )
    assert code == 0
    report = json.loads(audit_out.read_text(encoding="utf-8"))
    assert report["status"] == "pass"
    assert report["issue_count"] == 0


def test_cli_run_returns_error_when_audit_fails(tmp_path: Path, monkeypatch) -> None:
    events_out = tmp_path / "events.jsonl"
    metrics_out = tmp_path / "metrics.json"
    audit_out = tmp_path / "audit.json"

    monkeypatch.setattr(
        "rtos_sim.cli.main.build_audit_report",
        lambda events, scheduler_name=None, model_relation_summary=None: {  # noqa: ARG005
            "status": "fail",
            "issue_count": 1,
            "issues": [{"rule": "simulated_failure"}],
            "checks": {},
        },
    )
    code = main(
        [
            "run",
            "-c",
            str(EXAMPLES / "at01_single_dag_single_core.yaml"),
            "--events-out",
            str(events_out),
            "--metrics-out",
            str(metrics_out),
            "--audit-out",
            str(audit_out),
        ]
    )
    assert code == 2
    report = json.loads(audit_out.read_text(encoding="utf-8"))
    assert report["status"] == "fail"


def test_cli_migrate_config_removes_deprecated_event_id_validation(tmp_path: Path) -> None:
    source = yaml.safe_load((EXAMPLES / "at01_single_dag_single_core.yaml").read_text(encoding="utf-8"))
    source["scheduler"]["params"]["event_id_mode"] = "deterministic"
    source["scheduler"]["params"]["event_id_validation"] = "strict"
    src_path = tmp_path / "legacy.yaml"
    out_path = tmp_path / "migrated.yaml"
    report_path = tmp_path / "migrate_report.json"
    src_path.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")

    code = main(
        [
            "migrate-config",
            "--in",
            str(src_path),
            "--out",
            str(out_path),
            "--report-out",
            str(report_path),
        ]
    )
    assert code == 0
    assert out_path.exists()
    assert report_path.exists()

    migrated = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    assert "event_id_validation" not in migrated["scheduler"]["params"]
    assert main(["validate", "-c", str(out_path)]) == 0

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert "scheduler.params.event_id_validation" in report["removed_keys"]


def test_cli_migrate_config_preserves_ui_layout_metadata(tmp_path: Path) -> None:
    source = yaml.safe_load((EXAMPLES / "at01_single_dag_single_core.yaml").read_text(encoding="utf-8"))
    source["scheduler"]["params"]["event_id_validation"] = "strict"
    source["ui_layout"] = {"task_nodes": {"t0": {"s0": [12.0, 34.0]}}}
    src_path = tmp_path / "legacy_with_layout.yaml"
    out_path = tmp_path / "migrated_with_layout.yaml"
    src_path.write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")

    code = main(["migrate-config", "--in", str(src_path), "--out", str(out_path)])
    assert code == 0

    migrated = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    assert migrated["ui_layout"]["task_nodes"]["t0"]["s0"] == [12.0, 34.0]
