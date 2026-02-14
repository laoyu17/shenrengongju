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
