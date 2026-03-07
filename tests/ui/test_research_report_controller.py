from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from rtos_sim.ui.controllers.research_report_controller import ResearchReportController


@dataclass
class _Label:
    text: str = ""

    def setText(self, value: str) -> None:  # noqa: N802
        self.text = value


class _Scheduler:
    name = "np_edf"


@dataclass
class _Spec:
    scheduler: _Scheduler


class _Owner:
    def __init__(self) -> None:
        self._status_label = _Label()
        self._latest_run_spec: object | None = None
        self._latest_run_events: list[dict] | None = None
        self._latest_quality_snapshot: dict | None = None
        self._latest_model_relations_report: dict | None = None
        self._latest_audit_report: dict | None = None
        self._latest_research_report: dict | None = None


def _build_controller(owner: _Owner, errors: list[tuple[str, str | None]]) -> ResearchReportController:
    def _logger(action: str, _exc: Exception, **context: object) -> None:
        errors.append((action, str(context.get("path") if context else None)))

    return ResearchReportController(owner, _logger)


def test_research_export_requires_completed_run(monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _Owner()
    controller = _build_controller(owner, [])
    info_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.research_report_controller.QMessageBox.information",
        lambda _parent, title, message: info_calls.append((title, message)),
    )

    controller.on_research_export()

    assert info_calls == [
        ("Research Report", "Run simulation first to capture spec/events for research export.")
    ]


def test_research_export_writes_json_markdown_and_csv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _Owner()
    owner._latest_run_spec = _Spec(scheduler=_Scheduler())
    owner._latest_run_events = [{"event_id": "e1"}, {"event_id": "e2"}]
    owner._latest_quality_snapshot = {"status": "pass", "pytest": {"passed": 10}}
    errors: list[tuple[str, str | None]] = []
    controller = _build_controller(owner, errors)

    markdown_path = tmp_path / "research-report.md"
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.research_report_controller.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: (str(markdown_path), "Markdown Files (*.md)"),
    )
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.research_report_controller.build_model_relations_report",
        lambda spec: {"status": "pass", "summary": {"spec_seen": spec is owner._latest_run_spec}},
    )
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.research_report_controller.build_audit_report",
        lambda events, **kwargs: {
            "status": "pass",
            "events": len(events),
            "summary": kwargs.get("model_relation_summary"),
            "scheduler_name": kwargs.get("scheduler_name"),
        },
    )
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.research_report_controller.build_research_report_payload",
        lambda **kwargs: {
            "status": "pass",
            "warnings": [],
            "audit_events": kwargs["audit_report"]["events"],
            "quality_status": kwargs["quality_snapshot"]["status"] if kwargs["quality_snapshot"] else "missing",
        },
    )
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.research_report_controller.render_research_report_markdown",
        lambda report: f"# report\nstatus={report['status']}\n",
    )
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.research_report_controller.research_report_to_rows",
        lambda report: [{"category": "summary", "status": report["status"]}],
    )

    controller.on_research_export()

    json_path = markdown_path.with_suffix(".json")
    csv_path = markdown_path.with_name("research-report-summary.csv")
    assert markdown_path.exists()
    assert json_path.exists()
    assert csv_path.exists()
    assert markdown_path.read_text(encoding="utf-8") == "# report\nstatus=pass\n"
    assert json.loads(json_path.read_text(encoding="utf-8"))["audit_events"] == 2
    assert "category,status" in csv_path.read_text(encoding="utf-8")
    assert owner._latest_model_relations_report == {"status": "pass", "summary": {"spec_seen": True}}
    assert owner._latest_audit_report == {
        "status": "pass",
        "events": 2,
        "summary": {"spec_seen": True},
        "scheduler_name": "np_edf",
    }
    assert owner._latest_research_report == {
        "status": "pass",
        "warnings": [],
        "audit_events": 2,
        "quality_status": "pass",
    }
    assert owner._status_label.text == f"Research report exported: {markdown_path}"
    assert errors == []


def test_research_export_loads_cached_quality_from_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _Owner()
    owner._latest_run_spec = _Spec(scheduler=_Scheduler())
    owner._latest_run_events = []
    errors: list[tuple[str, str | None]] = []
    controller = _build_controller(owner, errors)

    artifacts_quality = tmp_path / "artifacts" / "quality"
    artifacts_quality.mkdir(parents=True)
    snapshot_path = artifacts_quality / "quality-snapshot.json"
    snapshot_path.write_text(json.dumps({"status": "pass", "pytest": {"passed": 20}}), encoding="utf-8")
    output_path = tmp_path / "research.md"

    monkeypatch.setattr(
        "rtos_sim.ui.controllers.research_report_controller.Path.cwd",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.research_report_controller.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: (str(output_path), "Markdown Files (*.md)"),
    )
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.research_report_controller.build_model_relations_report",
        lambda _spec: {"status": "pass", "summary": {}},
    )
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.research_report_controller.build_audit_report",
        lambda _events, **_kwargs: {"status": "pass"},
    )
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.research_report_controller.build_research_report_payload",
        lambda **kwargs: {"status": kwargs["quality_snapshot"]["status"]},
    )
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.research_report_controller.render_research_report_markdown",
        lambda report: report["status"],
    )
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.research_report_controller.research_report_to_rows",
        lambda report: [{"status": report["status"]}],
    )

    controller.on_research_export()

    assert owner._latest_quality_snapshot == {"status": "pass", "pytest": {"passed": 20}}
    assert errors == []


def test_research_export_handles_write_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    owner = _Owner()
    owner._latest_run_spec = _Spec(scheduler=_Scheduler())
    owner._latest_run_events = [{"event_id": "e1"}]
    errors: list[tuple[str, str | None]] = []
    controller = _build_controller(owner, errors)
    critical_calls: list[tuple[str, str]] = []

    output_path = tmp_path / "research.md"
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.research_report_controller.QFileDialog.getSaveFileName",
        lambda *_args, **_kwargs: (str(output_path), "Markdown Files (*.md)"),
    )
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.research_report_controller.QMessageBox.critical",
        lambda _parent, title, message: critical_calls.append((title, message)),
    )
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.research_report_controller.build_model_relations_report",
        lambda _spec: {"status": "pass", "summary": {}},
    )
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.research_report_controller.build_audit_report",
        lambda _events, **_kwargs: {"status": "pass"},
    )
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.research_report_controller.build_research_report_payload",
        lambda **_kwargs: {"status": "pass"},
    )
    monkeypatch.setattr(
        "rtos_sim.ui.controllers.research_report_controller.render_research_report_markdown",
        lambda _report: (_ for _ in ()).throw(OSError("disk full")),
    )

    controller.on_research_export()

    assert critical_calls == [("Research report export failed", "disk full")]
    assert errors == [("research_report_export", str(output_path))]
