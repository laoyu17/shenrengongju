from __future__ import annotations

import pytest

from rtos_sim.ui.config_doc import ConfigDocument


def _base_payload() -> dict:
    return {
        "version": "0.2",
        "platform": {
            "processor_types": [{"id": "CPU", "name": "cpu", "core_count": 1, "speed_factor": 1.0}],
            "cores": [{"id": "c0", "type_id": "CPU", "speed_factor": 1.0}],
        },
        "resources": [{"id": "r0", "name": "lock", "bound_core_id": "c0", "protocol": "mutex"}],
        "tasks": [
            {
                "id": "t0",
                "name": "task",
                "task_type": "dynamic_rt",
                "arrival": 0,
                "deadline": 10,
                "subtasks": [
                    {
                        "id": "s0",
                        "predecessors": [],
                        "successors": ["s1"],
                        "segments": [{"id": "seg0", "index": 1, "wcet": 1.0}],
                    },
                    {
                        "id": "s1",
                        "predecessors": ["s0"],
                        "successors": [],
                        "segments": [{"id": "seg0", "index": 1, "wcet": 1.0}],
                    },
                ],
            }
        ],
        "scheduler": {"name": "edf", "params": {"tie_breaker": "fifo"}},
        "sim": {"duration": 10.0, "seed": 1},
    }


def test_layout_round_trip_and_invalid_entries_are_ignored() -> None:
    payload = _base_payload()
    payload["ui_layout"] = {
        "task_nodes": {
            "t0": {
                "ok": [10, 20],
                "tuple_ok": (1.5, 2.5),
                "too_short": [1],
                "bad": ["x", 3],
            }
        }
    }
    doc = ConfigDocument.from_payload(payload)

    assert doc.has_ui_layout() is True
    assert doc.get_task_node_layout("t0") == {"ok": (10.0, 20.0), "tuple_ok": (1.5, 2.5)}
    assert doc.get_task_node_layout("missing") == {}

    before = doc.to_payload()
    doc.set_task_node_layout("", {"s0": (3.0, 4.0)})
    assert doc.to_payload() == before

    doc.set_task_node_layout("t0", {"s0": (3, 4)})
    assert doc.to_payload()["ui_layout"]["task_nodes"]["t0"]["s0"] == [3.0, 4.0]


def test_platform_and_primary_entries_are_repaired_from_invalid_shape() -> None:
    doc = ConfigDocument.from_payload({"platform": "bad", "tasks": [], "resources": []})

    platform = doc.get_platform()
    assert isinstance(platform["processor_types"], list)
    assert isinstance(platform["cores"], list)

    processor = doc.get_primary_processor()
    core = doc.get_primary_core()
    assert isinstance(processor, dict)
    assert isinstance(core, dict)

    doc.patch_primary_processor({"id": "P0", "core_count": 2})
    doc.patch_primary_core({"id": "c0", "type_id": "P0"})
    payload = doc.to_payload()
    assert payload["platform"]["processor_types"][0]["id"] == "P0"
    assert payload["platform"]["cores"][0]["id"] == "c0"


def test_task_and_resource_crud_handles_edge_cases() -> None:
    payload = _base_payload()
    payload["tasks"].append("not-an-object")
    payload["resources"].append("not-an-object")
    doc = ConfigDocument.from_payload(payload)

    task_views = doc.list_tasks()
    assert len(task_views) == 1

    new_task_index = doc.add_task({"id": "t0", "name": "custom"})
    assert new_task_index == 2
    assert doc.get_task(new_task_index)["id"].startswith("t")

    doc.patch_task(new_task_index, {"period": None, "deadline": None, "arrival": 2.0})
    patched = doc.get_task(new_task_index)
    assert "period" not in patched
    assert "deadline" not in patched
    assert patched["arrival"] == 2.0

    with pytest.raises(IndexError):
        doc.get_task(1)
    doc.remove_task(99)
    doc.remove_task(1)
    assert len(doc.list_tasks()) == 2

    resource_views = doc.list_resources()
    assert len(resource_views) == 1

    new_resource_index = doc.add_resource({"id": "r0"})
    assert new_resource_index == 2
    assert doc.get_resource(new_resource_index)["id"].startswith("r")
    doc.patch_resource(new_resource_index, {"protocol": "pcp"})
    assert doc.get_resource(new_resource_index)["protocol"] == "pcp"

    with pytest.raises(IndexError):
        doc.get_resource(1)
    doc.remove_resource(99)
    doc.remove_resource(1)
    assert len(doc.list_resources()) == 2


def test_subtask_rename_and_remove_update_dag_references() -> None:
    doc = ConfigDocument.from_payload(_base_payload())

    # Duplicate ID should be ignored.
    doc.patch_subtask(0, 0, {"id": "s1"})
    assert doc.get_subtask(0, 0)["id"] == "s0"

    doc.patch_subtask(0, 0, {"id": "s2"})
    assert doc.get_subtask(0, 0)["id"] == "s2"
    assert doc.get_subtask(0, 1)["predecessors"] == ["s2"]

    doc.remove_subtask(0, 0)
    remaining = doc.list_subtasks(0)
    assert len(remaining) == 1
    assert remaining[0]["predecessors"] == []
    assert remaining[0]["successors"] == []


def test_segment_and_edges_cover_invalid_paths() -> None:
    payload = _base_payload()
    payload["tasks"][0]["subtasks"][0]["segments"] = []
    doc = ConfigDocument.from_payload(payload)

    segment = doc.get_segment(0, 0)
    assert segment["id"] == "seg0"

    subtasks = doc.get_task(0)["subtasks"]
    subtasks[0]["segments"][0] = "bad"
    repaired = doc.get_segment(0, 0)
    assert repaired["id"] == "seg0"

    subtasks[0]["segments"].append("bad2")
    with pytest.raises(IndexError):
        doc.get_segment(0, 0, segment_index=1)

    doc.patch_segment(0, 0, {"wcet": 2.5})
    assert doc.get_segment(0, 0)["wcet"] == 2.5

    doc.add_subtask(0, "s1")
    ids = {item["id"] for item in doc.list_subtasks(0)}
    assert len(ids) == len(doc.list_subtasks(0))

    # Invalid edge operations should not crash.
    doc.add_edge(0, "", "s0")
    doc.add_edge(0, "s0", "")
    doc.add_edge(0, "s0", "s0")
    doc.add_edge(0, "not_exist", "s0")

    doc.add_edge(0, "s0", "s1")
    doc.add_edge(0, "s0", "s1")  # duplicate
    assert doc.list_edges(0).count(("s0", "s1")) == 1

    doc.remove_edge(0, "x", "y")
    doc.remove_edge(0, "s0", "s1")
    assert ("s0", "s1") not in doc.list_edges(0)


def test_scheduler_and_sim_patch_merge_defaults() -> None:
    doc = ConfigDocument.from_payload({"tasks": [], "resources": []})

    scheduler = doc.get_scheduler()
    assert scheduler["name"] == "edf"
    doc.patch_scheduler("rm", {"allow_preempt": False})
    scheduler = doc.get_scheduler()
    assert scheduler["name"] == "rm"
    assert scheduler["params"]["allow_preempt"] is False

    sim = doc.get_sim()
    assert sim["duration"] == 10.0
    assert sim["seed"] == 42
    doc.patch_sim(duration=20.0, seed=99)
    assert doc.get_sim()["duration"] == 20.0
    assert doc.get_sim()["seed"] == 99
