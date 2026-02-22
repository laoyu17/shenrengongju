# RTOS 异构多核仿真工具：实施现状、问题清单与 Sprint 规划

## 0. 文档控制
- 版本：v0.6
- 状态：S6（Phase A/B/C + D/E/F + G 语义闭环深化）
- 日期：2026-02-22
- 适用范围：`project/` 当前实现（代码 + 文档 + 测试）

## 1. 已经实现的内容（As-Is）

### 1.1 架构与工程化基线
- 已完成包结构落地（`core/events/model/schedulers/protocols/etm/overheads/metrics/io/cli/ui`）与依赖配置：`project/pyproject.toml:1`
- 已提供 CLI 入口与 UI 入口脚本：`project/pyproject.toml:31`
- 已补充运行说明与命令示例：`project/README.md:5`

### 1.2 核心仿真链路（SimPy）
- 引擎已支持 `build/run/step/pause/resume/stop/reset` 生命周期与事件推进：`project/rtos_sim/core/engine.py:101`
- 已接入调度器、资源协议、ETM、开销模型插件点：`project/rtos_sim/core/engine.py:105`
- 已实现关键运行事件：释放、就绪、开始、结束、阻塞/唤醒、抢占、迁移、deadline miss、完成：`project/rtos_sim/core/engine.py:320`
- 已实现 deadline miss 与 `abort_on_miss` 行为分支：`project/rtos_sim/core/engine.py:623`
- 已修复 deadline 边界触发与 abort 中止隔离语义（避免中止后再次调度）：`project/rtos_sim/core/engine.py:320`
- 已统一 EDF+PCP 优先级域（运行时绝对 deadline 域），并修复 ceiling 初值/刷新域误差导致的误阻塞：`project/rtos_sim/core/engine.py:247`、`project/rtos_sim/protocols/pcp.py:35`
- 已补齐 abort/cancel 异常路径的 `ResourceRelease` 事件：`project/rtos_sim/core/engine.py:1119`
- 已统一异构速率口径：`effective_core_speed = core.speed_factor * processor_type.speed_factor`：`project/rtos_sim/core/engine.py:157`

### 1.3 配置模型与语义校验
- 已实现 `0.1 -> 0.2` 配置兼容迁移：`project/rtos_sim/io/loader.py:83`
- 已实现 Schema 校验 + Pydantic 语义校验：`project/rtos_sim/io/loader.py:38`
- 已实现关键语义约束（DAG 无环、ID 唯一、引用完整性、mapping_hint 有效性）：`project/rtos_sim/model/spec.py:138`
- 已收紧 `time_deterministic` 定点约束（多核场景需可推导/显式 mapping_hint）：`project/rtos_sim/model/spec.py:244`
- 已新增统一到达过程 `arrival_process`（`fixed/uniform/poisson/one_shot/custom`）并兼容 legacy 到达字段：`project/rtos_sim/model/spec.py:76`、`project/rtos_sim/core/engine.py:686`

### 1.4 插件化能力（MVP）
- 调度器：EDF / RM + 注册机制：`project/rtos_sim/schedulers/registry.py:15`
- 调度器参数：`tie_breaker / allow_preempt` 已生效（S3 第一阶段）：`project/rtos_sim/schedulers/base.py:55`
- 资源协议：Mutex + PIP + PCP（优先级更新语义）：`project/rtos_sim/protocols/mutex.py:10`、`project/rtos_sim/protocols/pip.py:9`、`project/rtos_sim/protocols/pcp.py:9`
- ETM：`Constant + table_based`（段/核查表缩放）：`project/rtos_sim/etm/registry.py:14`
- 开销模型：Simple 常量开销：`project/rtos_sim/overheads/registry.py:22`
- 到达过程生成器：`arrival.custom` 注册机制（内置 `constant_interval/uniform_interval/poisson_rate/sequence`）：`project/rtos_sim/arrival/registry.py:1`
- 指标聚合：响应时间、超期率、抢占（调度/强制拆分）、迁移、利用率：`project/rtos_sim/metrics/core.py:63`

### 1.5 CLI 与 PyQt6 UI
- CLI 支持 `validate/run/ui/batch-run/compare/inspect-model/migrate-config` 命令：`project/rtos_sim/cli/main.py:95`
- `batch-run` 支持严格失败返回码开关 `--strict-fail-on-error`：`project/rtos_sim/cli/main.py:193`
- `run` 支持审计报告导出 `--audit-out`（协议/异常路径一致性检查）：`project/rtos_sim/cli/main.py:81`、`project/rtos_sim/analysis/audit.py:14`
- `run --audit-out` 已附带 `model_relation_summary`（模型语义摘要计数），便于报告联审：`project/rtos_sim/cli/main.py:151`
- 审计报告新增 `rule_version` 与 `evidence`，支持跨批次追溯：`project/rtos_sim/analysis/audit.py:7`
- 审计报告新增 `protocol_proof_assets`，沉淀 PIP/PCP 证明辅助轨迹：`project/rtos_sim/analysis/audit.py:79`
- 审计报告新增 `compliance_profiles`（`engineering_v1/research_v1`），支持研究闭环机读判定：`project/rtos_sim/analysis/audit.py:727`
- 事件与指标导出（JSONL/JSON）已打通：`project/rtos_sim/cli/main.py:51`
- 事件 ID 策略支持 `deterministic/random/seeded_random`，默认 deterministic：`project/rtos_sim/events/bus.py:14`
- 已支持批量实验 runner（factors 参数矩阵 -> 汇总 CSV/JSON）：`project/rtos_sim/io/experiment_runner.py:24`
- UI 已支持结构化表单与 YAML/JSON 文本双向同步：`project/rtos_sim/ui/app.py:209`
- UI 已支持多任务/多资源表格化增删改（表格 + 选中项详情联动）：`project/rtos_sim/ui/app.py:328`
- UI 已支持单任务 DAG 图形化雏形（节点/边可视化 + 侧栏增删改）：`project/rtos_sim/ui/app.py:350`
- UI 已支持 DAG 节点自由拖动（视图层）与自动布局重排：`project/rtos_sim/ui/app.py:924`
- UI 已支持 DAG 拖拽连线与循环检测即时提示（防止形成环）：`project/rtos_sim/ui/app.py:1030`
- UI 已支持可选 `ui_layout` 布局持久化（下次打开复用）：`project/rtos_sim/ui/config_doc.py:58`
- UI 已支持表格强校验（错误高亮 + Apply/Run/Validate 前阻断）：`project/rtos_sim/ui/app.py:1259`
- UI 已实现后台线程仿真 + 主线程渲染 + 实时 Gantt（按 CPU 泳道 + 任务图例 + 抢占断点）：`project/rtos_sim/ui/app.py:447`
- UI 已实现三层编码（Task 颜色 / Subtask 纹理 / Segment 边框+短标签）：`project/rtos_sim/ui/app.py:460`
- UI 已支持稳定悬停与点击锁定详情面板（专家字段）：`project/rtos_sim/ui/app.py:532`
- UI 事件增量批推送（64条或150ms）：`project/rtos_sim/ui/worker.py:53`
- UI 右侧采用“Gantt 上区 + 日志/详情/对比下区”分栏，Compare 默认折叠：`project/rtos_sim/ui/app.py:580`

### 1.6 测试与样例
- 已提供 10 个样例（新增 `at10_arrival_process`）：`project/examples/at06_time_deterministic.yaml:1`、`project/examples/at09_table_based_etm.yaml:1`、`project/examples/at10_arrival_process.yaml:1`
- 已实现模型/引擎/CLI 自动化测试：`project/tests/test_model_validation.py:41`、`project/tests/test_engine_scenarios.py:22`、`project/tests/test_cli.py:12`
- 已新增审计模块与 UI worker 真线程/直执行回归：`project/tests/test_audit.py:1`、`project/tests/test_ui_worker.py:1`
- 当前本地测试状态（2026-02-22）：`python -m pytest --maxfail=1` 通过，`211 passed`
- 当前覆盖率快照（2026-02-22）：总覆盖率 87%（`python -m pytest --cov=rtos_sim --cov-report=term-missing -q`）
- 新增质量快照脚本（用于文档事实对齐）：`project/scripts/quality_snapshot.py`
  - 建议命令：`python scripts/quality_snapshot.py --output artifacts/quality/quality-snapshot.json --coverage-json artifacts/quality/coverage.json`
  - 快照字段：`pytest.passed/failed/errors`、`coverage.line_rate`、`git_sha`、`generated_at_utc`

### 1.7 已修复：UI 有指标但 Gantt 无线段
- 根因：`SimulationWorker` 在 `engine.build()` 前订阅事件，而 `build()` 内部 `reset()` 重建了事件总线，导致 UI 事件流被清空。
- 修复：引擎新增订阅者持久化，`reset()` 后自动重新挂载外部订阅者，保证 UI/外部监听不丢事件：`project/rtos_sim/core/engine.py:79`
- 体验增强：Gantt 支持 Task/Subtask/Segment 三层编码，避免颜色层级混乱：`project/rtos_sim/ui/app.py:460`
- 体验增强：悬停命中改为 scene 鼠标检测，并提供右侧详情面板（支持点击锁定）：`project/rtos_sim/ui/app.py:532`
- 回归：新增测试覆盖“build/reset 后订阅依然有效”：`project/tests/test_engine_scenarios.py:65`
- 回归：新增 UI 交互与表单同步测试（含表格 CRUD、DAG 侧栏编辑、未知字段保留）：`project/tests/test_ui_gantt.py:39`
- 回归：新增 DAG 拖拽连线循环检测、节点自由移动、自动布局、可选布局持久化与表格校验阻断测试：`project/tests/test_ui_gantt.py:344`
- 当前本地测试状态：`python -m pytest -q` 通过（以最近一次本地/CI日志为准）

---

## 2. 当前存在的问题（Gap / Risk）

### 2.1 P0（需优先收敛）
1. **PCP 仍为 MVP 语义（未覆盖全部经典约束证明路径）**
   - 现状：已修复 EDF/PCP 优先级域不一致与异常路径事件缺口，但尚未形成“证明级”系统天花板分析报告。
   - 证据：`project/rtos_sim/protocols/pcp.py:10`、`project/rtos_sim/analysis/audit.py:14`
   - 影响：研究级可证明性仍需补充。

### 2.2 P1（近期应补齐）
1. **统一到达过程已落地并接入自定义生成器，但生态仍需扩展**
   - 现状：`arrival_process` 已支持 `fixed/uniform/poisson/one_shot/custom`，`custom` 通过 `params.generator` 调用注册生成器（内置 `constant_interval/uniform_interval/poisson_rate/sequence`）。
   - 证据：`project/rtos_sim/model/spec.py:76`、`project/rtos_sim/core/engine.py:686`、`project/rtos_sim/arrival/registry.py:1`
   - 影响：可满足插件化扩展入口；后续需补充更多分布模板与文档示例。

1. **调度器参数已从“透传”进入“基础生效”，但参数域仍需继续扩展**
   - 现状：`tie_breaker/allow_preempt` 已在 EDF/RM 生效，尚未覆盖更多算法级业务开关。
   - 证据：`project/rtos_sim/schedulers/base.py:55`、`project/rtos_sim/schedulers/edf.py:16`
   - 影响：核心参数化路径已打通，后续需补齐更细粒度策略参数。

2. **UI 图形化配置已进入雏形阶段，仍需完善交互深度**
   - 现状：已支持多任务/多资源表格 CRUD、单任务 DAG 侧栏编辑、拖拽连线循环拦截、节点自由移动与自动布局；复杂 DAG 的多选编排/跨任务画布仍待实现。
   - 证据：`project/rtos_sim/ui/app.py:209`
   - 影响：基础建模效率明显提升，但复杂图编辑体验仍有提升空间。

3. **FR-13 对比视图已落地 MVP，仍需扩展**
   - 现状：已支持双方案指标对比与 JSON/CSV 差分导出，但尚未接入多方案聚合报告与论文模板。
   - 证据：`project/docs/04-详细版SRS.md:83`、`project/rtos_sim/ui/app.py:591`、`project/rtos_sim/cli/main.py:190`
   - 影响：基础对比能力可用，研究级批量分析产物仍需增强。

4. **模型关系导出已进入“基础自动判定”阶段，仍需向研究模板扩展**
   - 现状：`inspect-model` 已可导出任务/子任务/分段与核/资源双向关系表，并附带 `status/checks` 自动判定摘要。
   - 证据：`project/rtos_sim/analysis/model_relations.py:1`、`project/rtos_sim/cli/main.py:237`
   - 影响：语义闭环证据链已打通第一步，后续仍需接入更高层实验模板与自动判定规则。

### 2.3 P2（中期优化）
1. **性能治理已建立首版基线，仍需持续校准阈值**
   - 现状：已提供 `scripts/perf_baseline.py`（100/300/1000 tasks）与阈值门禁入口。
   - 证据：`project/scripts/perf_baseline.py:1`

2. **CI/CD 已建立首版回归门禁，后续需补发布流水线**
   - 现状：已增加 Linux/Windows 测试 + Linux 性能报告工作流；PR 路径保留 100/300，nightly 增加 1000 非阻断趋势任务并输出昨日 delta 摘要。
   - 证据：`project/.github/workflows/ci.yml:1`
   - 影响：基础回归自动化已具备，仍需补打包发布链路。
   - 补充：nightly 昨日 delta 已改为按固定 `task_count` 严格匹配，避免误读其他 case 为基线（无匹配时降级 `no_base`）。

---

## 3. 已有设计参考在哪里（To-Be 依据）

### 3.1 需求与验收来源
- 需求与验收矩阵（AT-01~AT-07）：`project/docs/04-详细版SRS.md:61`
- SimPy 集成策略与阶段建议：`project/docs/07-开发评估与SimPy集成.md:8`

### 3.2 架构与接口来源
- 综合架构（模块边界、接口总览）：`project/docs/08-综合架构设计.md:13`
- 概要设计（模块职责、运行流程）：`project/docs/09-概要设计.md:24`
- 详细设计（事件字段、协议/ETM/UI约束）：`project/docs/10-详细设计说明书.md:74`

### 3.3 配置与数据模型来源
- Schema 草案与校验规则：`project/docs/05-配置文件Schema草案.md:1`
- 术语与数据模型草案：`project/docs/03-术语与数据模型草案.md:1`
- 时序图与类图：`project/docs/06-时序图与类图.md:1`

### 3.4 代码实现入口（直接参考）
- 仿真核心：`project/rtos_sim/core/engine.py:57`
- 配置加载：`project/rtos_sim/io/loader.py:29`
- CLI：`project/rtos_sim/cli/main.py:73`
- UI：`project/rtos_sim/ui/app.py:33`

---

## 4. 后续 Sprint 规划（建议 1–2 周/迭代）

### Sprint S1（已完成）— MVP 内核打通
- 范围：核心引擎、基础插件、CLI/UI MVP、样例与测试基线。
- 完成判定：CLI 可运行，UI 可展示，`pytest` 通过。

### Sprint S2（已完成，P0 主体收敛）— 协议与实验框架
- 目标：
  - 实现真实 `PIP/PCP` 协议；
  - 增加批量实验 runner（参数矩阵 -> 批跑 -> 汇总）。
- 关键交付：
  - `protocols/pip.py`、`protocols/pcp.py`；
  - `io/experiment_runner.py` + CLI 子命令（如 `batch-run`）。
- 验收标准：
  - 资源协议对比场景可复现；
  - 批量实验可输出统一报告（CSV/JSON）。
  - 当前状态：已完成（PIP/PCP 为 MVP 语义，后续继续增强证明能力）。

### Sprint S3（P1 收敛）— 可配置性与 UI 易用性
- 目标：
  - 调度器参数生效（策略参数化）；
  - UI 从“纯文本编辑”提升为“结构化表单 + 校验提示”。
- 关键交付：
  - 调度器参数解析与生效测试；
  - UI 表单化编辑器（至少平台/资源/任务基本字段）。
- 验收标准：
  - 参数变更可导致预期调度差异；
  - UI 无需手写 YAML 也可完成基础配置。

### Sprint S4（质量与性能）— 回归与门禁
- 目标：
  - 建立性能基线（100–300 tasks）；
  - 建立 CI（lint/test/样例回归 + 性能报告）。
- 关键交付：
  - 压测脚本与基准报告；
  - CI 配置（至少 Linux + Windows，测试硬门禁 + 性能软门禁）。
- 验收标准：
  - 主干提交自动回归；
  - 性能结果可持续追踪（报告产物可追溯，不阻断合并）。

### Sprint S5（发布与扩展）— 交付化
- 目标：
  - Windows 首发打包；
  - 增加算法对比与报告模板（面向实验/论文使用）。
- 关键交付：
  - 安装包与用户手册；
  - 对比实验模板（EDF/RM/协议差异）。
- 验收标准：
  - 非开发人员可独立运行；
  - 样例实验可一键生成结果报告。

---

## 5. 建议的管理节奏（执行建议）
- 每个 Sprint 固定输出：`设计变更记录 + 代码 + 测试 + 验收报告`
- 问题清单按 `P0/P1/P2` 每周滚动复盘一次
- 文档与代码强绑定：接口变更必须同步更新 `08/09/10` 三份设计文档

---

## 6. Phase 实施追踪（2026-02-18）

### Phase A（P0）已完成
- `core_count` 与 `platform.cores` 实际数量强一致校验已落地：`project/rtos_sim/model/spec.py:135`
- `batch-run --strict-fail-on-error` 已落地，失败子运行可返回非 0：`project/rtos_sim/cli/main.py:193`
- 回归：`project/tests/test_model_validation.py:153`、`project/tests/test_cli.py:75`

### Phase B（P1）已完成
- 动态实时随机区间到达（`min_inter_arrival + max_inter_arrival`）已落地：`project/rtos_sim/core/engine.py:678`
- 审计新增等待图死锁检测规则 `wait_for_deadlock`：`project/rtos_sim/analysis/audit.py:219`
- 回归：`project/tests/test_engine_scenarios.py:136`、`project/tests/test_audit.py:175`

### Phase C（P2）已完成（首轮）
- 性能基线默认场景已扩展至 100/300/1000：`project/scripts/perf_baseline.py:122`
- CI 性能任务分层：PR 路径 100/300，nightly 非阻断 1000 + 昨日 delta 摘要：`project/.github/workflows/ci.yml:68`
- 文档与命令示例已同步：`project/README.md:42`

### Phase D（研究可复现收敛）已完成（本轮）
- 统一到达过程 `arrival_process`（`fixed/uniform/poisson/one_shot/custom`）已落地，且保持 legacy 配置兼容：`project/rtos_sim/model/spec.py:76`、`project/rtos_sim/core/engine.py:686`
- 审计新增规则：`pip_priority_chain_consistency`、`pcp_ceiling_transition_consistency`：`project/rtos_sim/analysis/audit.py:220`
- 回归：新增到达过程与审计规则测试：`project/tests/test_engine_scenarios.py:229`、`project/tests/test_audit.py:91`、`project/tests/test_model_validation.py:201`

### Phase E（语义闭环）已完成（本轮）
- 新增 `inspect-model`：导出模型关系集合（任务/子任务/分段 与 核/资源双向关系）：`project/rtos_sim/cli/main.py:237`
- 新增关系提取模块：`build_model_relations_report` + `model_relations_report_to_rows`：`project/rtos_sim/analysis/model_relations.py:1`
- 审计报告新增 `model_relation_summary` 摘要挂载：`project/rtos_sim/analysis/audit.py:53`
- 回归：新增模型关系与 CLI 导出测试：`project/tests/test_model_relations.py:1`、`project/tests/test_cli.py:145`

### Phase F（配置治理与趋势可靠性）已完成（本轮）
- 移除废弃参数迁移入口：新增 `rtos-sim migrate-config`，支持 `event_id_validation` 自动清理并可输出迁移报告：`project/rtos_sim/cli/main.py:262`
- nightly 上一日基线提取改为固定文件名 `perf-nightly-1000.json`，避免 artifact 内多 json 时误选：`project/.github/workflows/ci.yml:196`
- `perf_delta` 改为按目标 `task_count` 严格匹配（无匹配不再回退首 case）：`project/scripts/perf_delta.py:20`
- 回归：新增 delta 严格匹配与迁移命令测试：`project/tests/test_perf_delta.py:62`、`project/tests/test_cli.py:341`

### Phase G（语义闭环深化）已完成（2026-02-22）
- 到达过程新增 `custom` 类型与生成器注册机制；`params.generator` 可选择注册生成器：`project/rtos_sim/model/spec.py:30`、`project/rtos_sim/arrival/registry.py:1`、`project/rtos_sim/core/engine.py:712`
- 审计报告新增 `rule_version` 与 `evidence` 字段，提升审计追溯性：`project/rtos_sim/analysis/audit.py:7`
- 审计报告新增 `protocol_proof_assets` 与 `pip_owner_hold_consistency`，增强协议可证明性证据：`project/rtos_sim/analysis/audit.py:79`、`project/rtos_sim/analysis/audit.py:653`
- 模型关系报告新增 `status/checks` 自动判定摘要：`project/rtos_sim/analysis/model_relations.py:42`
- 新增 docx 需求追踪矩阵：`project/docs/14-docx需求追踪矩阵.md`
- 回归：新增 custom 到达过程、审计证据字段、关系自动判定测试：`project/tests/test_engine_scenarios.py:360`、`project/tests/test_audit.py:388`、`project/tests/test_model_relations.py:56`
