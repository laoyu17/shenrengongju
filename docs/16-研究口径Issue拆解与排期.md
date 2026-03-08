# 研究口径执行 Issue 拆解与排期（S7）

## 0. 文档控制
- 版本：v0.6
- 日期：2026-03-07
- 适用范围：`project/` 当前主干实现
- 输入基线：`docs/11-实施现状问题与Sprint规划.md`、`docs/14-docx需求追踪矩阵.md`、`docs/15-研究闭环验收基线.md`
- 非目标：**性能优化**（按当前评审口径不纳入达标条件）

## 1. 目标与完成定义

### 1.1 目标
将“研究闭环已机读化，但证明级资产深度不足”的差距，拆解为可直接执行的工程 Issue，并形成 2 个迭代内可完成的交付路径。

### 1.2 完成定义（DoD）
以下条件全部满足即视为 S7 完成：
1. 研究反例集（PIP/PCP/混合到达）可一键运行并产出审计证据。
2. `research_v1` 的失败样例与修复样例均有自动化测试覆盖，`research_v2` 额外证明资产具备机读断言。
3. 审计报告可自动生成“评审可读”模板（Markdown/CSV/JSON），并可被 UI 导出入口直接复用。
4. CI 新增研究口径非阻断任务，稳定输出趋势报告。
5. 文档追踪矩阵与执行文档保持一致更新（`11/14/15/16` 四份）。

## 2. 当前基线快照（2026-03-05）
- 证据基线：`evidence_git_sha=7f0b9a502b93da00d16d9d272b99fd95d965bb72`
- 工作区基线：`workspace_git_sha=7f0b9a502b93da00d16d9d272b99fd95d965bb72`
- 全量测试：主线事实以 `artifacts/quality/quality-snapshot.json` 为准（当前基线 `482 passed`）。
- 覆盖率：主线事实以 `artifacts/quality/quality-snapshot.json` 为准（当前基线 `89.98%`，`line_rate=89.9769053117783`）。
- 现有研究判定入口：`compliance_profiles.profiles.research_v1.status`（兼容） + `compliance_profiles.profiles.research_v2.status`（当前主口径）
- 当前结论：证明资产、报告模板化、CI 稳定化与 UI 研究报告出口已形成最小闭环；剩余差距集中在 DAG 深交互的易用性/批量编辑体验，以及最新 freeze 证据追平。
- 门禁升级建议：维持 `research_audit` 非阻断；当连续 7 天 `research_v2=pass` 且 `unexpected_actual_checks=0` 后，再评估升级为阻断。

## 3. Issue Backlog（按优先级）

| ID | 优先级 | 目标 | 主要产出 | 预估工时 | 依赖 |
|---|---|---|---|---:|---|
| R-001 | P0 | 建立研究反例基准集 | 新增反例配置与对应回归测试 | 2.0 人天 | 无 |
| R-002 | P0 | 强化协议证明资产深度 | `protocol_proof_assets` 扩展字段 + 规则解释 | 2.5 人天 | R-001 |
| R-003 | P1 | 输出模板化研究报告 | 新增报告脚本 + Markdown/CSV/JSON 摘要 + UI 复用出口 | 2.0 人天 | R-002 |
| R-004 | P1 | 接入 CI 研究画像非阻断任务 | workflow job + artifacts + step summary | 1.5 人天 | R-003 |
| R-005 | P1 | 收紧模型关系研究判定规则 | `inspect-model` 新增研究向 checks | 2.0 人天 | R-001 |
| R-006 | P2 | 文档与追踪矩阵收敛 | `11/14/15/16` 同步 + 发布前复核清单 | 1.0 人天 | R-002,R-003,R-005 |

> 总工时：约 **11.0 人天**（单人）；双人并行可压缩至 6~7 人天。

## 4. 每个 Issue 的执行细节

### R-001（P0）研究反例基准集
**目标**：让研究口径不只“跑通正例”，还可稳定复现典型失败与修复路径。

**建议改动文件**：
- `examples/`（新增 `research_*` 场景）
- `tests/test_audit.py`
- `tests/test_engine_scenarios.py`

**交付项**：
1. 至少 6 个反例场景（建议：PIP owner 链错位、PCP ceiling 边界、死锁环、abort 释放可见性、混合到达突发、跨核绑定冲突）。
2. 每个反例都包含“fail case + fixed case”成对样例。
3. 测试断言覆盖：`checks[*].passed`、`failed_checks`、`protocol_proof_assets` 关键字段。

**验收命令**：
- `python -m pytest tests/test_audit.py -q`
- `python -m pytest tests/test_engine_scenarios.py -q`

**风险**：反例构造过弱会导致“看似通过，实则未触发规则”。

---

### R-002（P0）协议证明资产深度增强
**目标**：把审计从“是否通过”扩展到“为何通过/为何失败可追溯”。

**建议改动文件**：
- `rtos_sim/analysis/audit.py`
- `docs/15-研究闭环验收基线.md`
- `tests/test_audit.py`

**交付项**：
1. 扩展 `protocol_proof_assets`：补充链路深度统计、未闭环分类统计、关键事件引用（event_id）聚合。
2. 每条研究检查项补充“失败样例片段定位”字段（示例数量受限，默认前 N 条）。
3. `rule_version` 升级并记录字段变更说明。

**验收命令**：
- `python -m pytest tests/test_audit.py -q`
- `rtos-sim run -c <research_case.yaml> --audit-out artifacts/audit.json`

**风险**：字段膨胀可能影响报告可读性，需控制默认输出规模。

---

### R-003（P1）模板化研究报告生成
**目标**：让评审材料自动生成，减少手工整理偏差。

**建议改动文件**：
- `scripts/`（新增 `research_report.py`）
- `rtos_sim/analysis/`（如需新增组合函数）
- `tests/`（新增脚本级回归）

**交付项**：
1. 输入：`audit.json` + `model_relations.json` + `quality-snapshot.json`。
2. 输出：
   - `artifacts/research/research-report.md`
   - `artifacts/research/research-summary.csv`
3. 报告固定章节：结论、失败检查项、证据摘要、修复建议、追踪引用。

**验收命令**：
- `python scripts/research_report.py --audit ... --relations ... --quality ...`

**风险**：输入缺失时需优雅降级并标记不确定项。

---

### R-004（P1）CI 研究画像非阻断任务
**目标**：把研究口径变成持续可观测，而不是临时人工评审。

**建议改动文件**：
- `.github/workflows/ci.yml`
- `README.md`
- `docs/11-实施现状问题与Sprint规划.md`

**交付项**：
1. 新增 `research_audit` job（非阻断，`continue-on-error: true`）。
2. 固定产物：`research-audit-report`、`research-audit-summary`。
3. Step Summary 显示：`research_v1.status`、`research_v2.status`、`failed_checks`、关键样例计数。

**验收命令**：
- GitHub Actions 手动触发 `workflow_dispatch` 并检查 artifact。

**风险**：CI 时长上升，需控制场景数量与执行时长上限。

---

### R-005（P1）模型关系研究判定增强
**目标**：补齐 `inspect-model` 在研究语义下的检查深度。

**建议改动文件**：
- `rtos_sim/analysis/model_relations.py`
- `tests/test_model_relations.py`
- `docs/14-docx需求追踪矩阵.md`

**交付项**：
1. 新增研究向 checks（例如：时间确定性段绑定完整性、资源绑定与映射一致性强化）。
2. 为新增 checks 提供样例与失败样例测试。
3. 在追踪矩阵中增加规则映射与证据路径。

**验收命令**：
- `python -m pytest tests/test_model_relations.py -q`
- `rtos-sim inspect-model -c <config> --out-json <out>`

**风险**：规则过严可能误伤工程场景，需要分级（warn/error）。

---

### R-006（P2）文档与治理收敛
**目标**：让实现状态、验收口径、执行计划保持一致，不出现口径漂移。

**建议改动文件**：
- `docs/11-实施现状问题与Sprint规划.md`
- `docs/14-docx需求追踪矩阵.md`
- `docs/15-研究闭环验收基线.md`
- `docs/16-研究口径Issue拆解与排期.md`

**交付项**：
1. 增加“状态日期 + 对应 commit/快照命令”。
2. 固化发布前检查单（测试、覆盖率、研究画像、关系报告）。
3. 周更节奏：每周至少一次对齐四份文档。

**验收标准**：文档引用路径有效、命令可复现、状态描述与代码一致。

## 5. 迭代排期建议（2 Sprint）

### Sprint S7-1（建议 1 周）
- 必做：R-001、R-002
- 目标：先把研究闭环“证据深度”做扎实
- 出口标准：研究反例集稳定，`research_v2` 失败链路可解释，且 `research_v1` 保持兼容通过。

### Sprint S7-2（建议 1 周）
- 必做：R-003、R-004、R-005、R-006
- 目标：模板化产出 + CI 持续可观测 + 文档治理闭环
- 出口标准：评审可直接消费报告，且 CI 持续产出研究画像摘要

## 6. 执行顺序（决策已锁定）
1. 先做 R-001（反例）
2. 再做 R-002（证明资产增强）
3. 并行推进 R-003（报告）与 R-005（关系检查）
4. 随后接入 R-004（CI）
5. 最后执行 R-006（文档收敛）

## 7. 跟踪方式
- Issue 命名建议：`research/<ID>-<slug>`（如 `research/R-001-counterexample-suite`）
- 每个 Issue 必须附：
  - 变更文件清单
  - 验证命令与输出摘要
  - 风险与回滚说明
  - 对 `research_v1/research_v2` 的影响说明（新增/收紧/无影响）

## 8. 执行状态（2026-02-23）

| Issue | 状态 | 完成证据 |
|---|---|---|
| R-001 | ✅ 已完成 | `examples/research_counterexamples.json`、`scripts/research_case_suite.py`、`tests/test_research_case_suite.py` |
| R-002 | ✅ 已完成 | `rtos_sim/analysis/audit.py`、`tests/test_audit.py`（`rule_version=0.4`、`check_catalog@0.2`、`research_v2`、证明资产增强） |
| R-003 | ✅ 已完成 | `rtos_sim/analysis/research_report.py`、`scripts/research_report.py`、`rtos_sim/ui/controllers/research_report_controller.py`、`tests/test_research_report.py`、`tests/ui/test_research_report_controller.py` |
| R-004 | ✅ 已完成 | `.github/workflows/ci.yml`（`research_audit` job + artifacts） |
| R-005 | ✅ 已完成 | `rtos_sim/analysis/model_relations.py`、`tests/test_model_relations.py`（研究向 checks + profiles） |
| R-006 | ✅ 已完成 | `README.md`、`docs/11`、`docs/14`、`docs/15`、`docs/16`，并扩展同步至 `docs/18/19/22/25/26` 与 `review/02/06` |

## 9. 稳健性补强记录（2026-02-23）

- R-001 补强：`scripts/research_case_suite.py` 的匹配规则改为严格一致（新增 `unexpected_actual_checks`）；回归：`tests/test_research_case_suite.py`。
- R-003 补强：`rtos_sim/analysis/research_report.py` 对同规则多 issue 做聚合统计，新增 `issue_count` 并修正 `sample_count/sample_event_ids` 聚合口径；回归：`tests/test_research_report.py`。
- R-004 补强：`research_audit` CI Step Summary 增加 `research_v1`/`research_v2`/`engineering_v1` 显式告警与 `failed_rules` 摘要，确保非阻断策略下风险可见：`.github/workflows/ci.yml`。
- R-003 补强（第二轮）：`research_report` 新增 `non_audit_fail_details`，覆盖 `model_relations/quality` 非审计失败解释；回归：`tests/test_research_report.py`。
- R-004 补强（第二轮）：`research_audit` 新增多样例矩阵（`at01/at02/at06/at10`）与 `matrix-summary.json`，Step Summary 增加 matrix 状态与失败样例提示：`.github/workflows/ci.yml`。
- R-005 补强：`model_relations` profile 状态升级为 `pass/warn/fail`，并输出 `failed_warn_checks/failed_error_checks`；回归：`tests/test_model_relations.py`。
- R-006 补强：CLI 新增 `inspect-model --strict-on-fail`，支持关系语义严格门禁；回归：`tests/test_cli.py`，文档同步：`README.md`、`docs/11`、`docs/15`。
- R-002 补强（第三轮）：新增 `time_deterministic_ready_consistency` 与 `time_deterministic_proof_assets`，补齐 M-09 超周期相位稳定性机读证据；回归：`tests/test_audit.py`。
- R-002 补强（第四轮）：新增 `research_v2` 与 `protocol_proof_asset_completeness`，统一 `rule_version/chain_depth_stats/unclosed_category_counts/sample_event_refs/failure_samples` 的研究证明资产口径；回归：`tests/test_audit.py`、`tests/analysis/test_audit_protocol_checks.py`。



### Phase K（Phase 4 最终口径收敛）已完成（2026-03-07）
- Compare 已完成“报告结构与导出层 N-way-ready”收口：JSON 新增 `comparison_mode`、`scenario_labels`、`scenarios`、`scalar_summary`、`core_utilization_summary`，并支持 `JSON / CSV / Markdown` 导出。
- UI 已新增 `Export Research Report`，直接复用 `build_model_relations_report`、`build_audit_report`、`build_research_report_payload` 与 `render_research_report_markdown`，输出 `.md + .json + -summary.csv`。
- 文档口径已扩展同步到 `docs/18/19/22/25/26` 与 `review/02/06`，保证 30% 门禁、Compare 边界、Research Report 复用链、DAG backlog 四项表述一致。
- 当前未完成边界继续保留：Compare UI 的 ordered scenarios 闭环已完成；DAG 的基础多选 / 批量移动 / 批量删除已纳入当前实现，剩余问题集中在易用性、批量编辑体验与产品化收口。
