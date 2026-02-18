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
