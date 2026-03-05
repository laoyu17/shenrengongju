# 严格 Docx 验收矩阵（代码 + CLI + UI + 文档）

- 版本：v1.0
- 日期：2026-03-04
- 适用范围：`project/` 当前工作区
- 目标：将严格 Docx 口径映射为“实现点 + 测试点 + 交付件”并冻结验收路径。

| 条款ID | 严格口径要求 | 代码实现点 | 测试点 | 交付件 | 状态 |
|---|---|---|---|---|---|
| D-PLAN-01 | 计划结果需可追溯到唯一模型 | `rtos_sim/cli/main.py` `plan-static` 写入 `spec_fingerprint` | `tests/test_cli_planning_commands.py::test_cli_plan_static_outputs_json_and_csv` | 本矩阵 + 测试报告 | 已实现 |
| D-PLAN-02 | `analyze-wcrt` 禁止跨模型误用计划（严格模式） | `--strict-plan-match` + 指纹比对 | `test_cli_analyze_wcrt_strict_plan_match_*` | 测试细则/测试报告 | 已实现 |
| D-PLAN-03 | `export-os-config` 禁止跨模型误用计划（严格模式） | `--strict-plan-match` + `--config` 强约束 | `test_cli_export_os_config_strict_plan_match_*` | 测试细则/测试报告 | 已实现 |
| D-METRIC-01 | 可调度率需提供严格口径与兼容口径并行 | `rtos_sim/api.py::benchmark_sched_rate` 新增 `candidate_only_*` | `test_cli_benchmark_sched_rate_outputs_report` | 测试报告 | 已实现 |
| D-METRIC-02 | 基准脚本门禁采用严格口径 | `scripts/benchmark_sched_rate.py` gate 使用 `candidate_only_uplift` | `tests/test_sched_rate_benchmark_script.py` | 测试报告 | 已实现 |
| D-UI-01 | UI 可完成规划 → WCRT → OS 导出闭环 | `rtos_sim/ui/controllers/planning_controller.py` + `rtos_sim/ui/app.py` Planning 页 | `tests/test_ui_gantt.py::test_ui_planning_panel_end_to_end` | 用户手册/培训记录 | 已实现 |
| D-UI-02 | UI 展示释放/就绪/执行/挂起四态 | `timeline_controller.py` 消费 `JobReleased/SegmentReady/SegmentStart/SegmentBlocked` 并输出状态流 | `tests/ui/test_timeline_controller.py::test_state_stream_emits_four_runtime_states` | 用户手册 | 已实现 |
| D-UI-03 | UI 支持随机任务生成且同 seed 可复现 | `PlanningController.on_generate_random_tasks` | `tests/test_ui_gantt.py::test_ui_random_task_generation_is_seeded` | 用户手册/培训记录 | 已实现 |
| D-DOC-01 | 报告交付件清单完整可审查 | `docs/26-*` 系列文档 | 文档一致性复核 | 交付清单 | 已实现 |

## 统一口径说明

- 严格口径：`candidate_only_schedulable_rate` / `candidate_only_uplift`
- 兼容口径：`best_candidate_schedulable_rate` / `uplift`
- 严格门禁：`benchmark_sched_rate.py` 的 `--target-uplift` 以 `candidate_only_uplift` 判定。

## 验收命令

```bash
pytest -q tests/test_cli_planning_commands.py tests/test_sched_rate_benchmark_script.py
pytest -q tests/ui tests/test_ui_gantt.py
```
