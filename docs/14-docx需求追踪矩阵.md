# Docx 需求追踪矩阵（需求 → 代码 → 测试 → 审计）

## 0. 文档控制
- 版本：v0.1
- 日期：2026-02-22
- 基线：`250909-仿真工具-基础模型.docx`
- 追踪范围：`project/` 当前主干实现

## 1. 追踪矩阵（M-01 ~ M-12）

| ID | Docx 要求（摘要） | 代码实现证据 | 自动化测试证据 | 审计/报告证据 | 状态 |
|---|---|---|---|---|---|
| M-01 | 多处理器类型 + 多核 + 速度缩放 | `rtos_sim/model/spec.py:80`；`rtos_sim/core/engine.py:161` | `tests/test_engine_scenarios.py:617` | `artifacts/metrics*.json`（core utilization） | 已实现 |
| M-02 | `core_count` 与核心声明一致 | `rtos_sim/model/spec.py:323` | `tests/test_model_validation.py:153` | `rtos-sim validate` 校验路径 | 已实现 |
| M-03 | 资源互斥 + 绑定核 + 协议语义 | `rtos_sim/model/spec.py:349`；`rtos_sim/protocols/pip.py:9`；`rtos_sim/protocols/pcp.py:9` | `tests/test_engine_scenarios.py:43`；`tests/test_protocol_pcp.py:1` | `rtos_sim/analysis/audit.py:270`（平衡）/`rtos_sim/analysis/audit.py:640`（死锁）/`rtos_sim/analysis/audit.py:653`（owner 一致性） | 已实现（研究级增强中） |
| M-04 | DAG 任务图（无环/引用完整） | `rtos_sim/model/spec.py:488` | `tests/test_model_validation.py:41` | `rtos-sim validate` 错误可定位 | 已实现 |
| M-05 | 子任务分段顺序执行，可阻塞/可抢占 | `rtos_sim/model/spec.py:410`；`rtos_sim/core/engine.py:1178` | `tests/test_engine_scenarios.py:35`；`tests/test_engine_scenarios.py:118` | 事件流 `SegmentStart/End/Blocked/Unblocked/Preempt` | 已实现 |
| M-06 | 任务/子任务/分段三级映射与回退 | `rtos_sim/model/spec.py:413` | `tests/test_model_validation.py:284`；`tests/test_model_validation.py:293`；`tests/test_model_validation.py:304` | `inspect-model` 映射输出（`segment_to_core`） | 已实现 |
| M-07 | 任务/子任务/分段 与 核/资源关系集合 | `rtos_sim/analysis/model_relations.py:147`；`rtos_sim/analysis/model_relations.py:242` | `tests/test_model_relations.py:13`；`tests/test_cli.py:155` | `inspect-model` 报告 `status/checks/check_version` | 已实现（自动判定基础版） |
| M-08 | 周期/偶发/零星 + 随机到达模型 | `rtos_sim/model/spec.py:193`；`rtos_sim/core/engine.py:676`；`rtos_sim/core/engine.py:716`；`rtos_sim/arrival/registry.py:20` | `tests/test_engine_scenarios.py:229`；`tests/test_engine_scenarios.py:437`；`tests/test_engine_scenarios.py:488`；`tests/test_engine_scenarios.py:537` | 到达过程校验：`tests/test_model_validation.py:252` | 已实现（可扩展） |
| M-09 | 时间确定性（定时定点/超周期重复） | `rtos_sim/core/engine.py:654`；`rtos_sim/core/engine.py:465` | `tests/test_engine_scenarios.py:131`；`tests/test_engine_scenarios.py:1794` | 协议一致性审计：`rtos_sim/analysis/audit.py:362`；`rtos_sim/analysis/audit.py:534` | 部分实现（证明级资产仍需补） |
| M-10 | 动态实时截止期约束与超期处理 | `rtos_sim/core/engine.py:1293`；`rtos_sim/core/engine.py:1320` | `tests/test_engine_scenarios.py:112` | 审计 `abort_cancel_release_visibility`：`rtos_sim/analysis/audit.py:324` | 已实现 |
| M-11 | 非实时任务（best-effort） | `rtos_sim/model/spec.py:119`；`rtos_sim/core/engine.py:738` | `tests/test_engine_scenarios.py:317`；`tests/test_engine_scenarios.py:1794` | 指标报告 `jobs_completed/core_utilization` | 已实现 |
| M-12 | 大规模任务集（>=1000）可持续运行 | `scripts/perf_baseline.py:123`；`.github/workflows/ci.yml:128` | `tests/test_perf_delta.py:62` | nightly `perf-nightly-1000` + `perf-delta-summary` | 已实现（非阻断口径） |

## 2. 审计规则映射（协议可证明性资产）

- 资源平衡与终止路径：`resource_release_balance`、`abort_cancel_release_visibility`（`rtos_sim/analysis/audit.py:293`, `rtos_sim/analysis/audit.py:330`）
- PIP 证明辅助：`pip_priority_chain_consistency`、`pip_owner_hold_consistency`（`rtos_sim/analysis/audit.py:477`, `rtos_sim/analysis/audit.py:653`）
- PCP 证明辅助：`pcp_priority_domain_alignment`、`pcp_ceiling_numeric_domain`、`pcp_ceiling_transition_consistency`（`rtos_sim/analysis/audit.py:368`, `rtos_sim/analysis/audit.py:381`, `rtos_sim/analysis/audit.py:540`）
- 死锁证明辅助：`wait_for_deadlock`（`rtos_sim/analysis/audit.py:640`）
- 证明资产导出：`protocol_proof_assets`（`rtos_sim/analysis/audit.py:664`）

## 3. 使用建议（联审流程）

1. 先运行 `rtos-sim validate -c <config>`，确认模型语义合法。
2. 再运行 `rtos-sim run ... --audit-out artifacts/audit.json`，获取规则判定与证明资产。
3. 并行执行 `rtos-sim inspect-model ... --out-json ... --out-csv ...`，确认关系矩阵与 `status/checks`。
4. 评审时以本矩阵为索引，逐条核对 Docx 条目与证据链是否一致。
