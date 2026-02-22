from __future__ import annotations

from pathlib import Path

from rtos_sim.analysis import build_model_relations_report, model_relations_report_to_rows
from rtos_sim.analysis.model_relations import RELATION_SECTIONS, UNBOUND_CORE_ID
from rtos_sim.io import ConfigLoader


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_model_relations_tracks_unbound_segments() -> None:
    spec = ConfigLoader().load(str(EXAMPLES / "at01_single_dag_single_core.yaml"))

    report = build_model_relations_report(spec)

    assert report["summary"]["task_count"] == 1
    assert report["summary"]["segment_count"] == 2
    assert report["summary"]["unbound_segment_count"] == 2
    assert report["status"] == "warn"
    assert report["checks"]["segment_core_binding_coverage"]["passed"] is False
    assert {"task_id": "t0", "core_id": UNBOUND_CORE_ID} in report["task_to_cores"]
    assert {
        "task_id": "t0",
        "subtask_id": "s0",
        "segment_id": "seg0",
        "segment_key": "t0:s0:seg0",
        "core_id": UNBOUND_CORE_ID,
    } in report["segment_to_core"]


def test_model_relations_maps_resource_bound_segments_to_cores() -> None:
    spec = ConfigLoader().load(str(EXAMPLES / "at02_resource_mutex.yaml"))

    report = build_model_relations_report(spec)

    assert report["summary"]["unbound_segment_count"] == 0
    assert report["status"] == "pass"
    assert report["checks"]["segment_core_binding_coverage"]["passed"] is True
    assert report["checks"]["resource_segment_bound_core_alignment"]["passed"] is True
    assert all(item["core_id"] == "c0" for item in report["segment_to_core"])
    assert {
        "resource_id": "r0",
        "task_id": "high",
        "subtask_id": "s0",
        "segment_id": "seg0",
        "segment_key": "high:s0:seg0",
    } in report["resource_to_segments"]
    assert {
        "core_id": "c0",
        "task_id": "low",
        "subtask_id": "s0",
        "segment_id": "seg0",
        "segment_key": "low:s0:seg0",
    } in report["core_to_segments"]


def test_model_relations_rows_include_all_sections() -> None:
    spec = ConfigLoader().load(str(EXAMPLES / "at02_resource_mutex.yaml"))

    report = build_model_relations_report(spec)
    rows = model_relations_report_to_rows(report)

    categories = {row["category"] for row in rows}
    for section in RELATION_SECTIONS:
        if report[section]:
            assert section in categories
    assert all("category" in row for row in rows)


def test_model_relations_report_contains_check_version() -> None:
    spec = ConfigLoader().load(str(EXAMPLES / "at01_single_dag_single_core.yaml"))

    report = build_model_relations_report(spec)

    assert report["check_version"] == "0.2"
    assert "core_reverse_relation_consistency" in report["checks"]
    assert "compliance_profiles" in report


def test_model_relations_profiles_are_reported() -> None:
    spec = ConfigLoader().load(str(EXAMPLES / "at02_resource_mutex.yaml"))

    report = build_model_relations_report(spec)
    profiles = report["compliance_profiles"]

    assert profiles["profile_version"] == "0.1"
    assert profiles["profiles"]["engineering_v1"]["status"] == "pass"
    assert profiles["profiles"]["research_v1"]["status"] == "pass"


def test_model_relations_detects_time_deterministic_unbound_segment() -> None:
    spec = ConfigLoader().load(str(EXAMPLES / "at06_time_deterministic.yaml"))
    spec.tasks[0].subtasks[0].segments[0].mapping_hint = None

    report = build_model_relations_report(spec)

    assert report["status"] == "fail"
    check = report["checks"]["time_deterministic_segment_binding_strict"]
    assert check["passed"] is False
    assert check["samples"][0]["task_id"] == spec.tasks[0].id


def test_model_relations_detects_resource_bound_core_mismatch() -> None:
    payload = {
        "version": "0.2",
        "platform": {
            "processor_types": [
                {"id": "CPU", "name": "cpu", "core_count": 2, "speed_factor": 1.0},
            ],
            "cores": [
                {"id": "c0", "type_id": "CPU", "speed_factor": 1.0},
                {"id": "c1", "type_id": "CPU", "speed_factor": 1.0},
            ],
        },
        "resources": [{"id": "r0", "name": "lock", "bound_core_id": "c0", "protocol": "mutex"}],
        "tasks": [
            {
                "id": "t0",
                "name": "task",
                "task_type": "dynamic_rt",
                "arrival": 0.0,
                "deadline": 10.0,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": [],
                        "segments": [{"id": "seg0", "index": 1, "wcet": 1.0, "required_resources": ["r0"]}],
                    }
                ],
            }
        ],
        "scheduler": {"name": "edf", "params": {}},
        "sim": {"duration": 5.0, "seed": 9},
    }
    spec = ConfigLoader().load_data(payload)
    spec.tasks[0].subtasks[0].segments[0].mapping_hint = "c1"

    report = build_model_relations_report(spec)
    mismatch = report["checks"]["resource_bound_core_consistency"]

    assert report["status"] == "fail"
    assert mismatch["passed"] is False
    assert mismatch["samples"][0]["expected_core_id"] == "c0"
    assert mismatch["samples"][0]["observed_core_id"] == "c1"
