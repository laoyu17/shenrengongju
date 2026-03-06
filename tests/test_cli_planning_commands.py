from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from rtos_sim import api as sim_api
from rtos_sim.cli.main import main
from rtos_sim.legacy import report_api


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_cli_plan_static_outputs_json_and_csv(tmp_path: Path) -> None:
    out_json = tmp_path / "plan.json"
    out_csv = tmp_path / "plan.csv"

    code = main(
        [
            "plan-static",
            "-c",
            str(EXAMPLES / "at01_single_dag_single_core.yaml"),
            "--planner",
            "np_edf",
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
    assert payload["planner"] == "np_edf"
    assert isinstance(payload["schedule_table"]["windows"], list)
    assert isinstance(payload.get("spec_fingerprint"), str) and payload["spec_fingerprint"]
    assert payload["metadata"]["spec_fingerprint"] == payload["spec_fingerprint"]


def test_cli_plan_static_supports_np_rm_planner(tmp_path: Path) -> None:
    out_json = tmp_path / "plan-rm.json"

    code = main(
        [
            "plan-static",
            "-c",
            str(EXAMPLES / "at01_single_dag_single_core.yaml"),
            "--planner",
            "np_rm",
            "--out-json",
            str(out_json),
        ]
    )

    assert code == 0
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["planner"] == "np_rm"


def test_cli_analyze_wcrt_can_reuse_plan_json(tmp_path: Path) -> None:
    plan_json = tmp_path / "plan.json"
    report_json = tmp_path / "wcrt.json"

    code = main(
        [
            "plan-static",
            "-c",
            str(EXAMPLES / "at06_time_deterministic.yaml"),
            "--out-json",
            str(plan_json),
        ]
    )
    assert code == 0

    code = main(
        [
            "analyze-wcrt",
            "-c",
            str(EXAMPLES / "at01_single_dag_single_core.yaml"),
            "--plan-json",
            str(plan_json),
            "--out-json",
            str(report_json),
        ]
    )

    assert code == 0
    payload = json.loads(report_json.read_text(encoding="utf-8"))
    assert "items" in payload
    assert isinstance(payload["items"], list)


def test_cli_analyze_wcrt_strict_plan_match_fails_on_mismatch(tmp_path: Path) -> None:
    plan_json = tmp_path / "plan_mismatch.json"
    code = main(
        [
            "plan-static",
            "-c",
            str(EXAMPLES / "at06_time_deterministic.yaml"),
            "--out-json",
            str(plan_json),
        ]
    )
    assert code == 0

    code = main(
        [
            "analyze-wcrt",
            "-c",
            str(EXAMPLES / "at01_single_dag_single_core.yaml"),
            "--plan-json",
            str(plan_json),
            "--strict-plan-match",
            "--out-json",
            str(tmp_path / "wcrt.json"),
        ]
    )
    assert code == 2


def test_cli_analyze_wcrt_strict_plan_match_passes_on_match(tmp_path: Path) -> None:
    plan_json = tmp_path / "plan_match.json"
    code = main(
        [
            "plan-static",
            "-c",
            str(EXAMPLES / "at01_single_dag_single_core.yaml"),
            "--out-json",
            str(plan_json),
        ]
    )
    assert code == 0

    code = main(
        [
            "analyze-wcrt",
            "-c",
            str(EXAMPLES / "at01_single_dag_single_core.yaml"),
            "--plan-json",
            str(plan_json),
            "--strict-plan-match",
            "--out-json",
            str(tmp_path / "wcrt.json"),
        ]
    )
    assert code == 0


def test_cli_export_os_config_outputs_json_and_csv(tmp_path: Path) -> None:
    plan_json = tmp_path / "plan.json"
    os_json = tmp_path / "os.json"
    os_csv = tmp_path / "os.csv"

    code = main(
        [
            "plan-static",
            "-c",
            str(EXAMPLES / "at06_time_deterministic.yaml"),
            "--out-json",
            str(plan_json),
        ]
    )
    assert code == 0

    code = main(
        [
            "export-os-config",
            "--plan-json",
            str(plan_json),
            "--out-json",
            str(os_json),
            "--out-csv",
            str(os_csv),
        ]
    )

    assert code == 0
    payload = json.loads(os_json.read_text(encoding="utf-8"))
    assert "threads" in payload
    assert "schedule_windows" in payload
    assert os_csv.exists()


def test_cli_export_os_config_strict_plan_match_fails_on_mismatch(tmp_path: Path) -> None:
    plan_json = tmp_path / "plan_mismatch.json"
    code = main(
        [
            "plan-static",
            "-c",
            str(EXAMPLES / "at06_time_deterministic.yaml"),
            "--out-json",
            str(plan_json),
        ]
    )
    assert code == 0

    code = main(
        [
            "export-os-config",
            "--plan-json",
            str(plan_json),
            "--config",
            str(EXAMPLES / "at01_single_dag_single_core.yaml"),
            "--strict-plan-match",
            "--out-json",
            str(tmp_path / "os.json"),
        ]
    )
    assert code == 2


def test_cli_export_os_config_strict_plan_match_requires_config(tmp_path: Path) -> None:
    plan_json = tmp_path / "plan.json"
    code = main(
        [
            "plan-static",
            "-c",
            str(EXAMPLES / "at06_time_deterministic.yaml"),
            "--out-json",
            str(plan_json),
        ]
    )
    assert code == 0

    code = main(
        [
            "export-os-config",
            "--plan-json",
            str(plan_json),
            "--strict-plan-match",
            "--out-json",
            str(tmp_path / "os.json"),
        ]
    )
    assert code == 2


def test_schedule_table_to_runtime_windows_keeps_segment_level_fields(tmp_path: Path) -> None:
    plan_json = tmp_path / "plan.json"
    code = main(
        [
            "plan-static",
            "-c",
            str(EXAMPLES / "at06_time_deterministic.yaml"),
            "--out-json",
            str(plan_json),
        ]
    )
    assert code == 0

    payload = json.loads(plan_json.read_text(encoding="utf-8"))
    schedule_table = sim_api.planning_result_from_dict(payload).schedule_table
    windows = sim_api.schedule_table_to_runtime_windows(schedule_table)

    assert windows
    assert {"segment_key", "core_id", "task_id", "subtask_id", "segment_id", "start", "end"}.issubset(
        set(windows[0].keys())
    )


def test_cli_benchmark_sched_rate_outputs_report(tmp_path: Path) -> None:
    report_json = tmp_path / "benchmark.json"
    report_csv = tmp_path / "benchmark.csv"

    code = main(
        [
            "benchmark-sched-rate",
            "-c",
            str(EXAMPLES / "at01_single_dag_single_core.yaml"),
            str(EXAMPLES / "at02_resource_mutex.yaml"),
            "--baseline",
            "np_edf",
            "--candidates",
            "np_dm,precautious_dm",
            "--out-json",
            str(report_json),
            "--out-csv",
            str(report_csv),
        ]
    )

    assert code == 0
    payload = json.loads(report_json.read_text(encoding="utf-8"))
    assert payload["total_cases"] == 2
    assert "uplift" in payload
    assert "candidate_only_uplift" in payload
    assert "candidate_only_schedulable_rate" in payload
    assert "empty_scope_case_count" in payload
    assert "non_empty_case_count" in payload
    assert "non_empty_candidate_only_uplift" in payload
    assert report_csv.exists()


def test_cli_benchmark_sched_rate_uses_wcrt_gating(tmp_path: Path) -> None:
    config = tmp_path / "wcrt_gate.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "version": "0.2",
                "platform": {
                    "processor_types": [
                        {"id": "CPU", "name": "cpu", "core_count": 1, "speed_factor": 1.0}
                    ],
                    "cores": [{"id": "c0", "type_id": "CPU", "speed_factor": 1.0}],
                },
                "resources": [],
                "tasks": [
                    {
                        "id": "lp",
                        "name": "lp",
                        "task_type": "dynamic_rt",
                        "period": 10.0,
                        "deadline": 3.5,
                        "arrival": 0.0,
                        "subtasks": [
                            {
                                "id": "s0",
                                "predecessors": [],
                                "successors": [],
                                "segments": [
                                    {
                                            "id": "seg0",
                                            "index": 1,
                                            "wcet": 2.0,
                                            "required_resources": [],
                                            "mapping_hint": "c0",
                                        }
                                    ],
                            }
                        ],
                    },
                    {
                        "id": "hp",
                        "name": "hp",
                        "task_type": "dynamic_rt",
                        "period": 2.0,
                        "deadline": 1.5,
                        "arrival": 3.0,
                        "subtasks": [
                            {
                                "id": "s0",
                                "predecessors": [],
                                "successors": [],
                                "segments": [
                                    {
                                            "id": "seg0",
                                            "index": 1,
                                            "wcet": 1.0,
                                            "required_resources": [],
                                            "mapping_hint": "c0",
                                        }
                                    ],
                            }
                        ],
                    },
                ],
                "scheduler": {"name": "edf", "params": {}},
                "sim": {"duration": 10.0, "seed": 1},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    report_json = tmp_path / "benchmark.json"
    code = main(
        [
            "benchmark-sched-rate",
            "-c",
            str(config),
            "--baseline",
            "np_edf",
            "--candidates",
            "np_dm",
            "--task-scope",
            "sync_and_dynamic_rt",
            "--out-json",
            str(report_json),
        ]
    )
    assert code == 0

    payload = json.loads(report_json.read_text(encoding="utf-8"))
    case = payload["cases"][0]
    assert case["baseline_planning_feasible"] is True
    assert case["baseline_wcrt_feasible"] is False
    assert case["baseline_feasible"] is False
    assert case["candidates"]["np_dm"]["planning_feasible"] is True
    assert case["candidates"]["np_dm"]["wcrt_feasible"] is False
    assert case["candidate_only_feasible"] is False


def test_cli_benchmark_sched_rate_target_uplift_uses_candidate_only_metric(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_report = {
        "total_cases": 1,
        "baseline_schedulable_rate": 0.2,
        "best_candidate_schedulable_rate": 0.5,
        "candidate_only_schedulable_rate": 0.25,
        "uplift": 1.5,
        "candidate_only_uplift": 0.25,
        "cases": [],
    }
    monkeypatch.setattr("rtos_sim.cli.main.sim_api.benchmark_sched_rate", lambda *_a, **_k: fake_report)

    code = main(
        [
            "benchmark-sched-rate",
            "-c",
            str(EXAMPLES / "at01_single_dag_single_core.yaml"),
            "--target-uplift",
            "0.3",
            "--out-json",
            str(tmp_path / "benchmark.json"),
        ]
    )

    assert code == 2


def test_cli_migrate_config_autofills_planning_defaults(tmp_path: Path) -> None:
    source = tmp_path / "v02.json"
    source.write_text(
        json.dumps(
            {
                "version": "0.2",
                "platform": {
                    "processor_types": [
                        {"id": "CPU", "name": "cpu", "core_count": 1, "speed_factor": 1.0}
                    ],
                    "cores": [{"id": "c0", "type_id": "CPU", "speed_factor": 1.0}],
                },
                "resources": [],
                "tasks": [
                    {
                        "id": "t0",
                        "name": "task",
                        "task_type": "dynamic_rt",
                        "deadline": 10,
                        "arrival": 0,
                        "subtasks": [
                            {
                                "id": "s0",
                                "predecessors": [],
                                "successors": [],
                                "segments": [{"id": "seg0", "index": 1, "wcet": 1}],
                            }
                        ],
                    }
                ],
                "scheduler": {"name": "edf", "params": {}},
                "sim": {"duration": 10, "seed": 1},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    out_json = tmp_path / "migrated.json"
    report_json = tmp_path / "report.json"

    code = main(
        [
            "migrate-config",
            "--in",
            str(source),
            "--out",
            str(out_json),
            "--report-out",
            str(report_json),
        ]
    )

    assert code == 0
    migrated = json.loads(out_json.read_text(encoding="utf-8"))
    report = json.loads(report_json.read_text(encoding="utf-8"))
    assert migrated["planning"]["planner"] == "np_edf"
    assert "planning" in report["added_keys"]
    assert report["planning_defaults_applied"] is True


def test_legacy_report_api_alias_sched_init_sched_table() -> None:
    table = report_api.sched_init_sched_table(
        EXAMPLES / "at01_single_dag_single_core.yaml",
        planner="np_edf",
    )

    assert table["planner"] == "np_edf"
    assert isinstance(table["windows"], list)


def test_legacy_report_api_alias_table62_functions_are_callable() -> None:
    table = report_api.sched_init_sched_table(
        EXAMPLES / "at06_time_deterministic.yaml",
        planner="np_edf",
    )
    assert table["windows"]

    fetched = report_api.sched_get_sched_table(
        EXAMPLES / "at06_time_deterministic.yaml",
        planner="np_edf",
    )
    assert fetched["planner"] == "np_edf"

    inserted = report_api.sched_sched_insert(table, table["windows"][0])
    assert len(inserted["windows"]) == len(table["windows"]) + 1

    removed = report_api.sched_sched_remove(inserted, segment_key=table["windows"][0]["segment_key"])
    assert len(removed["windows"]) <= len(inserted["windows"])

    td_state = report_api.sched_td_task_new_arrival(task_id="sync", time=0.0)
    td_state = report_api.sched_td_task_complete(td_state, task_id="sync", time=1.0)
    dy_state = report_api.sched_dy_task_new_arrival(td_state, task_id="dyn", time=2.0)
    dy_state = report_api.sched_dy_task_complete(dy_state, task_id="dyn", time=3.0)
    assert dy_state["last_event"]["event"] == "dy_task_complete"

    picked = report_api.sched_pick_next_task(
        [
            {"task_id": "a", "deadline": 8.0, "wcet": 1.0},
            {"task_id": "b", "deadline": 4.0, "wcet": 2.0},
        ]
    )
    assert picked is not None
    assert picked["task_id"] == "b"

    scheduled = report_api.sched_schedule(table, now=0.0)
    assert "selected_window" in scheduled

    changed = report_api.sched_model_change(mode="static", schedule_table=table)
    assert changed["static_window_mode"] is True
    assert isinstance(changed.get("static_windows"), list)

    wcrt = report_api.wcrt_analyse(EXAMPLES / "at06_time_deterministic.yaml", table)
    assert "items" in wcrt

    partition = report_api.partition_periodic_task(["t1", "t2", "t3"], ["c0", "c1"])
    assert partition["task_to_core"]["t1"] == "c0"
    assert partition["task_to_core"]["t2"] == "c1"


def test_legacy_report_api_semantic_boundary_is_lightweight_compat_only() -> None:
    table = report_api.sched_init_sched_table(
        EXAMPLES / "at06_time_deterministic.yaml",
        planner="np_edf",
    )

    first_pick = report_api.sched_schedule(table, now=0.0)
    second_pick = report_api.sched_schedule(table, now=0.0)
    assert first_pick == second_pick

    state = report_api.sched_td_task_new_arrival(task_id="sync", time=0.0)
    state = report_api.sched_dy_task_complete(state, task_id="dyn", time=1.0)
    assert sorted(state.keys()) == ["events", "last_event"]
    assert len(state["events"]) == 2

    dynamic_patch = report_api.sched_model_change(mode="dynamic", schedule_table=table)
    assert dynamic_patch == {"mode": "dynamic", "static_window_mode": False}

    static_patch = report_api.sched_model_change(mode="static")
    assert static_patch == {"mode": "static", "static_window_mode": True}
