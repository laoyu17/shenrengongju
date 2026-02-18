from __future__ import annotations

import json
from pathlib import Path

from rtos_sim.cli.main import main


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
