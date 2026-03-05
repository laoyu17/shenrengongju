# Docx条款追踪矩阵（2026-03-04）

基线文档仅使用以下两份：
- `250909-仿真工具-基础模型.docx`
- `异构计算平台混合实时任务调度规划与仿真工具设计方案报告.docx`

提取锚点：
- 研制目标 8 条：`review/docx/baseline_design_report_extracted.md` 中 `[P0049]~[P0056]`
- 任务书测试映射：`[TABLE 13]`
- 满足性表：`[TABLE 17]`
- 函数接口表：`[TABLE 6]`

## A. 主条款（研制目标 8 条）

| 条款ID | Docx原文锚点 | 代码证据 | 测试证据 | 运行证据 | 判定 |
|---|---|---|---|---|---|
| G-01 固定点任务规划 | `baseline_design_report_extracted.md:84` | `rtos_sim/cli/main.py:480` `cmd_plan_static`；`rtos_sim/planning/types.py:160` | `tests/test_cli_planning_commands.py:17` | `review/runtime/logs/04_plan_at06.log:1` | 已实现 |
| G-02 固定点+定期+间歇混合调度 | `baseline_design_report_extracted.md:85` | `rtos_sim/planning/types.py:17`（`task_scope`）；`rtos_sim/core/engine_static_window.py:77`（静态窗口约束） | `tests/test_engine_static_window_mode.py:107` | `review/runtime/logs/15_run_at05_preempt.log:1` + `review/runtime/artifacts/at05_metrics.json`（`preempt_count=1`） | 已实现 |
| G-03 混合任务可调度性分析（WCRT） | `baseline_design_report_extracted.md:86` | `rtos_sim/cli/main.py:537`；`rtos_sim/planning/wcrt.py:190` | `tests/test_wcrt_analysis.py:76` | `review/runtime/logs/05_wcrt_at06_strict_match.log:1` | 已实现 |
| G-04 可调度率提升 30%（口径） | `baseline_design_report_extracted.md:87` | `rtos_sim/cli/main.py:709`；`scripts/benchmark_sched_rate.py:183` | `tests/test_sched_rate_benchmark_script.py:22` | `review/runtime/logs/11_benchmark_script_strict.log:1`（`macro_uplift=0.833333333`） | 部分实现 |
| G-05 图形化输入/输出界面 | `baseline_design_report_extracted.md:88` | `rtos_sim/ui/app.py:636`（Planning页）`rtos_sim/ui/app.py:668`（结果Tab） | `tests/test_ui_gantt.py:242` | `python -m pytest -q` 全绿（UI用例含该场景） | 已实现 |
| G-06 平台参数与任务模型参数配置 | `baseline_design_report_extracted.md:89` | `rtos_sim/ui/config_doc.py:269`（planning 默认与补丁）；`rtos_sim/io/schema.py:227` | `tests/test_cli_planning_commands.py:405`（迁移补全 planning） | `review/runtime/logs/13_migrate_at01.log:1` | 已实现 |
| G-07 运行时动态仿真与状态展示 | `baseline_design_report_extracted.md:90` | `rtos_sim/ui/controllers/timeline_controller.py:53`~`102`（Released/Ready/Executing/Blocked） | `tests/test_ui_gantt.py:283`；`tests/ui/test_timeline_controller.py:195` | `python -m pytest -q` 全绿（状态流测试覆盖） | 已实现 |
| G-08 任务调度参数输出接口 | `baseline_design_report_extracted.md:91` | `rtos_sim/cli/main.py:607`；`rtos_sim/api.py:260` | `tests/test_cli_planning_commands.py:134` | `review/runtime/logs/06_export_os_at06_strict_match.log:1` | 已实现 |

## B. 主索引表一致性（13/17/6）

| Docx表 | 关键结论 | 代码与测试映射 | 判定 |
|---|---|---|---|
| 表13（任务书技术要求与测试）`baseline_design_report_extracted.md:403` | 7项均标注“满足任务书要求” | CLI/UI/WCRT/导出链路均有测试：`tests/test_cli_planning_commands.py`、`tests/test_ui_gantt.py`、`tests/test_wcrt_analysis.py` | 与现状基本一致 |
| 表17（设计满足任务书）`baseline_design_report_extracted.md:482` | 固定点规划、混合调度、WCRT、状态四态、用户交互、OS参数导出 | `rtos_sim/cli/main.py`、`rtos_sim/api.py`、`rtos_sim/ui/app.py`、`rtos_sim/ui/controllers/timeline_controller.py` | 与现状一致 |
| 表6（主要接口）`baseline_design_report_extracted.md:272` | `sched_init_sched_table` 等接口需可用 | `rtos_sim/legacy/report_api.py:42`~`452` 提供同名别名；`tests/test_cli_planning_commands.py:476` 覆盖可调用性 | 已实现（别名层） |

## C. 重点清单核对

- CLI：`plan-static/analyze-wcrt/export-os-config/benchmark-sched-rate/inspect-model/migrate-config` 已在 `rtos_sim/cli/main.py:843`~`1012` 注册并具备错误码语义。
- `--strict-plan-match`：`analyze-wcrt` 与 `export-os-config` 校验模型指纹，见 `rtos_sim/cli/main.py:552`、`615`，并有正负测试 `tests/test_cli_planning_commands.py:78`、`169`。
- Python API：`rtos_sim/api.py:113`、`142`、`260`、`419`；旧接口别名层 `rtos_sim/legacy/report_api.py:42`~`452`。
- 配置与类型：`planning` 段定义于 `rtos_sim/io/schema.py:227`，类型约束在 `rtos_sim/model/spec.py:300`；序列化契约在 `rtos_sim/planning/types.py:121`、`255`、`294`。
- UI闭环与四态：Planning 面板控件 `rtos_sim/ui/app.py:345`~`404`，动作链路 `rtos_sim/ui/controllers/planning_controller.py:151`~`231`，四态事件映射 `rtos_sim/ui/controllers/timeline_controller.py:53`~`102`。

