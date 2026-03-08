# Docx 需求追踪矩阵（需求 → 代码 → 测试 → 审计）

## 0. 文档控制
- 版本：v0.6
- 日期：2026-03-07
- 基线：`250909-仿真工具-基础模型.docx`
- 追踪范围：仓库根目录当前主干实现
- 证据基线：`evidence_git_sha=a98218562038b60c23a0b99ab630780c3da67970`
- 工作区基线：`workspace_git_sha=a98218562038b60c23a0b99ab630780c3da67970`
- 复核命令：
  - `python -m pytest -q`
  - `python scripts/quality_snapshot.py --output artifacts/quality/quality-snapshot.json --coverage-json artifacts/quality/coverage.json`

## 1. 追踪矩阵（M-01 ~ M-12）

| ID | Docx 要求（摘要） | 代码实现证据 | 自动化测试证据 | 审计/报告证据 | 状态 |
|---|---|---|---|---|---|
| M-01 | 多处理器类型 + 多核 + 速度缩放 | `rtos_sim/model/spec.py:80`；`rtos_sim/core/engine.py:153` | `tests/test_engine_scenarios.py:617` | `artifacts/metrics*.json`（core utilization） | 已实现 |
| M-02 | `core_count` 与核心声明一致 | `rtos_sim/model/spec.py:323` | `tests/test_model_validation.py:153` | `rtos-sim validate` 校验路径 | 已实现 |
| M-03 | 资源互斥 + 绑定核 + 协议语义 | `rtos_sim/model/spec.py:349`；`rtos_sim/protocols/pip.py:9`；`rtos_sim/protocols/pcp.py:9` | `tests/test_engine_scenarios.py:43`；`tests/test_protocol_pcp.py:1`；`tests/analysis/test_audit_deadlock_checks.py:6` | `rtos_sim/analysis/audit_checks/resource_checks.py:36`（平衡）/`rtos_sim/analysis/audit_checks/deadlock_checks.py:32`（死锁）/`rtos_sim/analysis/audit_checks/protocol_checks.py:452`（owner 一致性）/`rtos_sim/analysis/audit.py:207`（研究闭环画像） | 已实现（研究闭环口径已机读化） |
| M-04 | DAG 任务图（无环/引用完整） | `rtos_sim/model/spec.py:488` | `tests/test_model_validation.py:41` | `rtos-sim validate` 错误可定位 | 已实现 |
| M-05 | 子任务分段顺序执行，可阻塞/可抢占 | `rtos_sim/model/spec.py:410`；`rtos_sim/core/engine_dispatch.py:14` | `tests/test_engine_scenarios.py:35`；`tests/test_engine_scenarios.py:118` | 事件流 `SegmentStart/End/Blocked/Unblocked/Preempt` | 已实现 |
| M-06 | 任务/子任务/分段三级映射与回退 | `rtos_sim/model/spec.py:413` | `tests/test_model_validation.py:284`；`tests/test_model_validation.py:293`；`tests/test_model_validation.py:304` | `inspect-model` 映射输出（`segment_to_core`） | 已实现 |
| M-07 | 任务/子任务/分段 与 核/资源关系集合 | `rtos_sim/analysis/model_relations.py:202`；`rtos_sim/analysis/model_relations.py:344` | `tests/test_model_relations.py:13`；`tests/test_cli.py:155` | `inspect-model` 报告 `status/checks/check_version/compliance_profiles` | 已实现（工程/研究画像） |
| M-08 | 周期/偶发/零星 + 随机到达模型 | `rtos_sim/model/spec.py:193`；`rtos_sim/core/engine_release.py:131`；`rtos_sim/core/engine_release.py:224`；`rtos_sim/arrival/registry.py:20`；`rtos_sim/planning/normalized.py:312` | `tests/test_engine_scenarios.py:229`；`tests/test_engine_scenarios.py:437`；`tests/test_engine_scenarios.py:488`；`tests/test_engine_scenarios.py:537`；`tests/test_planning_heuristics.py:423` | 到达过程校验：`tests/test_model_validation.py:252`；研究到达 trace：`arrival_assumption_trace` | 已实现（基础类型 + `periodic_jitter/burst_sequence` 研究模板） |
| M-09 | 时间确定性（定时定点/超周期重复） | `rtos_sim/core/engine.py:487`；`rtos_sim/core/engine_release.py:109` | `tests/test_engine_scenarios.py:131`；`tests/test_audit.py:540`；`tests/core/test_engine_split_helpers.py:99` | 协议一致性审计 + 时间确定性一致性检查：`rtos_sim/analysis/audit_checks/time_deterministic_checks.py:31`；`rtos_sim/analysis/audit.py:224` | 已实现（研究闭环口径） |
| M-10 | 动态实时截止期约束与超期处理 | `rtos_sim/core/engine_runtime.py:202`；`rtos_sim/core/engine_abort.py:15` | `tests/test_engine_scenarios.py:112`；`tests/core/test_engine_split_helpers.py:200`；`tests/core/test_engine_split_helpers.py:296` | 审计 `abort_cancel_release_visibility`：`rtos_sim/analysis/audit_checks/resource_checks.py:83` | 已实现 |
| M-11 | 非实时任务（best-effort） | `rtos_sim/model/spec.py:119`；`rtos_sim/core/engine_release.py:131` | `tests/test_engine_scenarios.py:317`；`tests/test_engine_scenarios.py:1794` | 指标报告 `jobs_completed/core_utilization` | 已实现 |
| M-12 | 大规模任务集（>=1000）可持续运行 | `scripts/perf_baseline.py:123`；`.github/workflows/ci.yml:128` | `tests/test_perf_delta.py:62` | nightly `perf-nightly-1000` + `perf-delta-summary` | 已实现（非阻断口径） |

## 2. 审计规则映射（协议可证明性资产）

- 资源平衡与终止路径：`resource_release_balance`、`abort_cancel_release_visibility`（`rtos_sim/analysis/audit_checks/resource_checks.py:36`, `rtos_sim/analysis/audit_checks/resource_checks.py:83`）
- PIP 证明辅助：`pip_priority_chain_consistency`、`pip_owner_hold_consistency`（`rtos_sim/analysis/audit_checks/protocol_checks.py:322`, `rtos_sim/analysis/audit_checks/protocol_checks.py:452`）
- PCP 证明辅助：`pcp_priority_domain_alignment`、`pcp_ceiling_numeric_domain`、`pcp_ceiling_transition_consistency`（`rtos_sim/analysis/audit_checks/protocol_checks.py:236`, `rtos_sim/analysis/audit_checks/protocol_checks.py:279`, `rtos_sim/analysis/audit_checks/protocol_checks.py:380`）
- 死锁证明辅助：`wait_for_deadlock`（`rtos_sim/analysis/audit_checks/deadlock_checks.py:32`）
- 证明资产导出：`protocol_proof_assets`（`rtos_sim/analysis/audit_checks/protocol_checks.py:50`）
- 时间确定性证明资产：`time_deterministic_proof_assets`（ready-time 对齐 + 超周期相位稳定性）
- 研究闭环画像：`compliance_profiles`（`engineering_v1/research_v1/research_v2`，`rtos_sim/analysis/audit.py:207`）
- 规则边界回归：`tests/analysis/test_audit_deadlock_checks.py:6`、`tests/analysis/test_audit_checks_boundaries.py:8`
- 研究反例基准集：`examples/research_counterexamples.json` + `scripts/research_case_suite.py`（严格匹配：`missing_expected_checks` + `unexpected_actual_checks`）
- 研究模板化报告：`scripts/research_report.py`（Markdown/CSV/JSON，失败项聚合 `issue_count/sample_count/sample_event_ids` + `non_audit_fail_details`）
- UI 研究报告出口：`rtos_sim/ui/controllers/research_report_controller.py`（复用同一 research_report 产物链，输出 `.md + .json + -summary.csv`）

## 3. 研究闭环 DoD（research_v1 / research_v2）

`run --audit-out` 产物中的 `compliance_profiles.profiles.research_v1.status` 作为历史兼容研究基线；`compliance_profiles.profiles.research_v2.status` 作为当前研究级证据门禁。M-03/M-09 的机读结论优先以 `research_v2=pass` 为准，同时保留 `research_v1` 以兼容旧报告与历史冻结产物。

- 必过检查（research_v1 / research_v2 共有）：
  - `resource_release_balance`
  - `abort_cancel_release_visibility`
  - `pcp_priority_domain_alignment`
  - `pcp_ceiling_numeric_domain`
  - `resource_partial_hold_on_block`
  - `pip_priority_chain_consistency`
  - `pcp_ceiling_transition_consistency`
  - `wait_for_deadlock`
  - `pip_owner_hold_consistency`
  - `time_deterministic_ready_consistency`
- `research_v2` 额外要求：`protocol_proof_asset_completeness` 必须为 `pass`，并输出 `rule_version`、`chain_depth_stats`、`unclosed_category_counts`、`sample_event_refs`、`failure_samples`。
- 配套说明文档：`docs/15-研究闭环验收基线.md`

## 4. 使用建议（联审流程）

1. 先运行 `rtos-sim validate -c <config>`，确认模型语义合法。
   - 需要脚本门禁时，建议加 `--strict-id-tokens`（将内部保留分隔符告警升级为失败）。
2. 再运行 `rtos-sim run ... --audit-out artifacts/audit.json`，获取规则判定与证明资产。
3. 并行执行 `rtos-sim inspect-model ... --out-json ... --out-csv ...`，确认关系矩阵与 `status/checks`。
   - 脚本/CI 推荐：`rtos-sim inspect-model ... --strict-on-fail`（将 `status!=pass` 转为非 0）
   - 当前基线（2026-02-27）：官方样例 `at01~at10` 均可在 `--strict-on-fail` 下通过；`segment_core_binding_coverage` 对迁移导向 `unbound` 仅记录 advisory 计数
4. 运行 `python scripts/quality_snapshot.py --output artifacts/quality/quality-snapshot.json --coverage-json artifacts/quality/coverage.json`，固化测试/覆盖率快照。
5. 运行 `python scripts/research_case_suite.py --cases examples/research_counterexamples.json ...`，核对反例基准集匹配率。
   - 单案例需校验：`missing_expected_checks` 与 `unexpected_actual_checks` 均为空。
6. 运行 `python scripts/research_report.py --audit ... --relations ... --quality ...`，生成评审模板化报告。
   - 研究画像需同时查看：`engineering_v1/research_v1/research_v2`。
   - 失败项需核对：同一 rule 的 `issue_count/sample_count/sample_event_ids` 聚合是否完整。
   - `research_v2` 需额外核对：`protocol_proof_assets.rule_version/chain_depth_stats/unclosed_category_counts/sample_event_refs/failure_samples`。
   - 失败原因需核对：`non_audit_fail_details`（如 `model_relations/quality` 导致的总体失败）。
   - 若做 UI 预览，可使用工具栏 `Export Research Report`；该入口复用同一产物结构，但当前仅基于最近一次 UI 运行缓存的 `spec/events`。
7. Compare 联审可选：右侧 Compare 面板现支持 `JSON / CSV / Markdown` 导出，且 report JSON 已包含 `comparison_mode/scenario_labels/scenarios/scalar_summary/core_utilization_summary`，便于与研究报告并排核对。
8. 评审时以本矩阵为索引，逐条核对 Docx 条目与证据链是否一致。


## 5. Phase 4 当前边界（2026-03-07）

- Compare：结构与导出层已 N-way-ready，UI 也已切到 ordered scenarios 装载与构建；当前 backlog 只保留 DAG 深交互。
- Research Report：UI 已提供导出入口，但底层仍复用既有 `research_report.py` 产物链，不单独维护第二套报告引擎。
- DAG：多选 / 批量移动 / 批量删除未在本轮实现，继续作为后续 backlog。
