# RTOS 异构多核仿真工具：实施现状、问题清单与 Sprint 规划

## 0. 文档控制
- 版本：v1.0
- 状态：S7（Phase A/B/C + D/E/F + G + H 研究执行闭环）
- 日期：2026-03-01
- 适用范围：仓库根目录当前实现（代码 + 文档 + 测试）
- 实现快照：`git_sha=472319138a4e578579d646f5aef2f116a236d8c2`
- 复核命令：
  - `python -m pytest -q`
  - `python scripts/quality_snapshot.py --output artifacts/quality/quality-snapshot.json --coverage-json artifacts/quality/coverage.json`

## 1. 已经实现的内容（As-Is）

### 1.1 架构与工程化基线
- 已完成包结构落地（`core/events/model/schedulers/protocols/etm/overheads/metrics/io/cli/ui`）与依赖配置：`pyproject.toml:1`
- 已提供 CLI 入口与 UI 入口脚本：`pyproject.toml:31`
- 已补充运行说明与命令示例：`README.md:5`

### 1.2 核心仿真链路（SimPy）
- 引擎已支持 `build/run/step/pause/resume/stop/reset` 生命周期与事件推进：`rtos_sim/core/engine.py:101`
- 已接入调度器、资源协议、ETM、开销模型插件点：`rtos_sim/core/engine.py:105`
- 已实现关键运行事件：释放、就绪、开始、结束、阻塞/唤醒、抢占、迁移、deadline miss、完成：`rtos_sim/core/engine.py:320`
- 已实现 deadline miss 与 `abort_on_miss` 行为分支：`rtos_sim/core/engine.py:623`
- 已修复 deadline 边界触发与 abort 中止隔离语义（避免中止后再次调度）：`rtos_sim/core/engine.py:320`
- 已统一 EDF+PCP 优先级域（运行时绝对 deadline 域），并修复 ceiling 初值/刷新域误差导致的误阻塞：`rtos_sim/core/engine.py:247`、`rtos_sim/protocols/pcp.py:35`
- 已补齐 abort/cancel 异常路径的 `ResourceRelease` 事件：`rtos_sim/core/engine_abort.py`（`abort_job` 路径）
- 已统一异构速率口径：`effective_core_speed = core.speed_factor * processor_type.speed_factor`：`rtos_sim/core/engine.py:157`

### 1.3 配置模型与语义校验
- 已实现 `0.1 -> 0.2` 配置兼容迁移：`rtos_sim/io/loader.py:83`
- 已实现 Schema 校验 + Pydantic 语义校验：`rtos_sim/io/loader.py:38`
- 已实现关键语义约束（DAG 无环、ID 唯一、引用完整性、mapping_hint 有效性）：`rtos_sim/model/spec.py:138`
- 已收紧 `time_deterministic` 定点约束（多核场景需可推导/显式 mapping_hint）：`rtos_sim/model/spec.py:244`
- 已新增统一到达过程 `arrival_process`（`fixed/uniform/poisson/one_shot/custom`）并兼容 legacy 到达字段：`rtos_sim/model/spec.py:76`、`rtos_sim/core/engine.py:686`

### 1.4 插件化能力（MVP）
- 调度器：EDF / RM + 注册机制：`rtos_sim/schedulers/registry.py:15`
- 调度器参数：`tie_breaker / allow_preempt` 已生效（S3 第一阶段）：`rtos_sim/schedulers/base.py:55`
- 资源协议：Mutex + PIP + PCP（优先级更新语义）：`rtos_sim/protocols/mutex.py:10`、`rtos_sim/protocols/pip.py:9`、`rtos_sim/protocols/pcp.py:9`
- ETM：`Constant + table_based`（段/核查表缩放）：`rtos_sim/etm/registry.py:14`
- 开销模型：Simple 常量开销：`rtos_sim/overheads/registry.py:22`
- 到达过程生成器：`arrival.custom` 注册机制（内置 `constant_interval/uniform_interval/poisson_rate/sequence`）：`rtos_sim/arrival/registry.py:1`
- 指标聚合：响应时间、超期率、抢占（调度/强制拆分）、迁移、利用率：`rtos_sim/metrics/core.py:63`

### 1.5 CLI 与 PyQt6 UI
- CLI 支持 `validate/run/ui/batch-run/compare/inspect-model/migrate-config/plan-static/analyze-wcrt/export-os-config` 命令：`rtos_sim/cli/main.py:95`
- `validate` 新增 `--strict-id-tokens`（将内部保留分隔符告警升级为失败，便于脚本门禁）：`rtos_sim/cli/main.py:415`
- `batch-run` 支持严格失败返回码开关 `--strict-fail-on-error`：`rtos_sim/cli/main.py:193`
- `run` 支持审计报告导出 `--audit-out`（协议/异常路径一致性检查）：`rtos_sim/cli/main.py:81`、`rtos_sim/analysis/audit.py:14`
- `run` 新增 `--plan-json/--strict-plan-match`，可直接消费统一计划工件并物化 `runtime_static_windows`：`rtos_sim/cli/main.py`
- `plan-static` 统一输出 `spec_fingerprint + semantic_fingerprint + planning_context + runtime_static_windows`：`rtos_sim/api.py`、`rtos_sim/cli/handlers_planning.py`
- `analyze-wcrt` 输出新增 `metadata.assumptions/unsupported_dimensions/blocking_bound/overhead_bound/heterogeneous_speed_mode`：`rtos_sim/api.py`、`rtos_sim/planning/wcrt.py`
- WCRT 已将 `resource_blocking` 与 `dispatch/migration overhead` 纳入真实分析项，`unsupported_dimensions` 中对应条目仅保留“static plan 未直接展开”的提示：`rtos_sim/planning/wcrt.py`、`rtos_sim/planning/normalized.py`
- 离线规划与 WCRT 已进一步切换到“按核心执行成本”口径：异构核有效速度与 ETM 缩放会直接改变 `plan-static` 窗口长度与 WCRT 结果：`rtos_sim/planning/normalized.py`、`rtos_sim/planning/heuristics.py`、`rtos_sim/planning/lp_solver.py`、`rtos_sim/planning/wcrt.py`
- `release_offsets` 与 stochastic arrival 已从“单次代表性投影”升级为“按 horizon 的多次 release 展开”：时间确定性窗口按 release index 应用 offset，随机到达按 `sim.seed` 生成可复现 sample-path：`rtos_sim/planning/normalized.py`
- 已新增 arrival 分析模式切换：`planning.params.arrival_analysis_mode=sample_path|conservative_envelope`；保守包络对 `poisson/custom` 可通过 `arrival_envelope_min_intervals` 提供下界。
- `scheduler.params.static_windows[*].release_index` 已接入 runtime 匹配，可显式约束特定 release instance：`rtos_sim/core/engine_static_window.py`、`tests/test_engine_static_window_mode.py`
- `run --audit-out` 已附带 `model_relation_summary`（模型语义摘要计数），便于报告联审：`rtos_sim/cli/main.py:151`
- 审计报告新增 `rule_version` 与 `evidence`，支持跨批次追溯：`rtos_sim/analysis/audit.py:7`
- 审计报告新增 `protocol_proof_assets`，沉淀 PIP/PCP 证明辅助轨迹：`rtos_sim/analysis/audit.py:79`
- 审计报告新增 `compliance_profiles`（`engineering_v1/research_v1`），支持研究闭环机读判定：`rtos_sim/analysis/audit.py:264`
- `inspect-model` 新增 `--strict-on-fail`，可将 `status!=pass` 转为非 0 退出码（便于 CI/脚本门禁）：`rtos_sim/cli/main.py:294`
- 事件与指标导出（JSONL/JSON）已打通：`rtos_sim/cli/main.py:51`
- 事件 ID 策略支持 `deterministic/random/seeded_random`，默认 deterministic：`rtos_sim/events/bus.py:14`
- 已支持批量实验 runner（factors 参数矩阵 -> 汇总 CSV/JSON）：`rtos_sim/io/experiment_runner.py:24`
- `batch-run` 已增加输出目录边界约束：批配置文件内的 `output_dir` 不允许越出批配置所在目录；CLI 显式 `--output-dir` 仍可覆盖：`rtos_sim/io/experiment_runner.py:69`
- `batch-run` 子案例失败记录已增强可观测性：`runs[*]` 增加 `error_type` 与 `error_trace_path`，并落盘 traceback：`rtos_sim/io/experiment_runner.py:116`
- UI 已支持结构化表单与 YAML/JSON 文本双向同步：`rtos_sim/ui/app.py:209`
- UI 已支持多任务/多资源表格化增删改（表格 + 选中项详情联动）：`rtos_sim/ui/app.py:328`
- UI 已支持单任务 DAG 图形化雏形（节点/边可视化 + 侧栏增删改）：`rtos_sim/ui/app.py:350`
- UI 已支持 DAG 节点自由拖动（视图层）与自动布局重排：`rtos_sim/ui/app.py:924`
- UI 已支持 DAG 拖拽连线与循环检测即时提示（防止形成环）：`rtos_sim/ui/app.py:1030`
- UI 已支持可选 `ui_layout` 布局持久化（下次打开复用）：`rtos_sim/ui/config_doc.py:58`
- UI 已支持表格强校验（错误高亮 + Apply/Run/Validate 前阻断）：`rtos_sim/ui/app.py:1259`
- UI 已实现后台线程仿真 + 主线程渲染 + 实时 Gantt（按 CPU 泳道 + 任务图例 + 抢占断点）：`rtos_sim/ui/app.py:447`
- UI 已实现三层编码（Task 颜色 / Subtask 纹理 / Segment 边框+短标签）：`rtos_sim/ui/app.py:460`
- UI 已支持稳定悬停与点击锁定详情面板（专家字段）：`rtos_sim/ui/app.py:532`
- UI 事件增量批推送（64条或150ms）：`rtos_sim/ui/worker.py:53`
- UI 右侧采用“Gantt 上区 + 日志/详情/对比下区”分栏，Compare 默认折叠：`rtos_sim/ui/app.py:580`

### 1.6 测试与样例
- 已提供 10 个样例（新增 `at10_arrival_process`）：`examples/at06_time_deterministic.yaml:1`、`examples/at09_table_based_etm.yaml:1`、`examples/at10_arrival_process.yaml:1`
- 已实现模型/引擎/CLI 自动化测试：`tests/test_model_validation.py:41`、`tests/test_engine_scenarios.py:22`、`tests/test_cli.py:12`
- 已新增审计模块与 UI worker 真线程/直执行回归：`tests/test_audit.py:1`、`tests/test_ui_worker.py:1`
- 当前本地测试状态（2026-03-04）：`python -m pytest --maxfail=1` 通过，`404 passed`
- 当前覆盖率快照（2026-03-04）：总覆盖率 89.05%（`coverage.line_rate=89.04797521102682`，来源：`artifacts/quality/quality-snapshot.json`）
- 新增质量快照脚本（用于文档事实对齐）：`scripts/quality_snapshot.py`
  - 建议命令：`python scripts/quality_snapshot.py --output artifacts/quality/quality-snapshot.json --coverage-json artifacts/quality/coverage.json`
  - 快照字段：`pytest.passed/failed/errors`、`coverage.line_rate`、`git_sha`、`generated_at_utc`
  - 新增复用模式：`--reuse-existing-artifacts --pytest-output-file <path>`；当复用摘要解析为失败且未开启 `--allow-fail` 时，脚本返回非 0：`scripts/quality_snapshot.py:102`
  - 兼容性修复（2026-03-05）：脚本改为按文件直载 `rtos_sim/analysis/quality_snapshot.py`，避免经过 `rtos_sim.analysis.__init__` 引发额外依赖导入；CI 最小环境可直接执行：`scripts/quality_snapshot.py:15`
  - 回归测试：新增 `python -S scripts/quality_snapshot.py --help` 场景，验证无 site-packages 时入口可用：`tests/test_quality_snapshot_script.py:100`

### 1.7 已修复：UI 有指标但 Gantt 无线段
- 根因：`SimulationWorker` 在 `engine.build()` 前订阅事件，而 `build()` 内部 `reset()` 重建了事件总线，导致 UI 事件流被清空。
- 修复：引擎新增订阅者持久化，`reset()` 后自动重新挂载外部订阅者，保证 UI/外部监听不丢事件：`rtos_sim/core/engine.py:79`
- 体验增强：Gantt 支持 Task/Subtask/Segment 三层编码，避免颜色层级混乱：`rtos_sim/ui/app.py:460`
- 体验增强：悬停命中改为 scene 鼠标检测，并提供右侧详情面板（支持点击锁定）：`rtos_sim/ui/app.py:532`
- 回归：新增测试覆盖“build/reset 后订阅依然有效”：`tests/test_engine_scenarios.py:65`
- 回归：新增 UI 交互与表单同步测试（含表格 CRUD、DAG 侧栏编辑、未知字段保留）：`tests/test_ui_gantt.py:39`
- 回归：新增 DAG 拖拽连线循环检测、节点自由移动、自动布局、可选布局持久化与表格校验阻断测试：`tests/test_ui_gantt.py:344`
- 当前本地测试状态：`python -m pytest -q` 通过（以最近一次本地/CI日志为准）

### 1.8 已修复：Wayland 环境 Tooltip popup 警告风暴与 UI 崩溃
- 现象：在 Wayland 桌面下运行 `rtos-sim ui -c ...`，日志反复出现 `qt.qpa.wayland: Failed to create popup`，并在高频悬停场景可能触发 `Segmentation fault`。
- 根因：悬停提示使用 `QToolTip.showText` 时未提供 transient parent，Wayland 无法稳定创建 tooltip popup。
- 修复：改为使用 plot `viewport` 作为 tooltip parent，并按 scene 坐标映射到 viewport 全局坐标：`rtos_sim/ui/app.py:1919`
- 回归：新增 `test_ui_hover_tooltip_uses_plot_viewport_parent`，确保 tooltip 调用绑定 `window._plot.viewport()`：`tests/test_ui_gantt.py:113`
- 兼容建议：若历史环境仍出现 Wayland 图形栈兼容问题，可临时使用 `QT_QPA_PLATFORM=xcb` 启动 UI。

---

## 2. 当前存在的问题（Gap / Risk）

### 2.1 P0（需优先收敛）
1. **PCP 仍为 MVP 语义（未覆盖全部经典约束证明路径）**
   - 现状：已修复 EDF/PCP 优先级域不一致与异常路径事件缺口，但尚未形成“证明级”系统天花板分析报告。
   - 证据：`rtos_sim/protocols/pcp.py:10`、`rtos_sim/analysis/audit.py:14`
   - 影响：研究级可证明性仍需补充。

### 2.2 P1（近期应补齐）
1. **统一到达过程已落地并接入自定义生成器，但生态仍需扩展**
   - 现状：`arrival_process` 已支持 `fixed/uniform/poisson/one_shot/custom`，`custom` 通过 `params.generator` 调用注册生成器（内置 `constant_interval/uniform_interval/poisson_rate/sequence`）。
   - 证据：`rtos_sim/model/spec.py:76`、`rtos_sim/core/engine.py:686`、`rtos_sim/arrival/registry.py:1`
   - 影响：可满足插件化扩展入口；后续需补充更多分布模板与文档示例。

1. **调度器参数已从“透传”进入“基础生效”，但参数域仍需继续扩展**
   - 现状：`tie_breaker/allow_preempt` 已在 EDF/RM 生效，尚未覆盖更多算法级业务开关。
   - 证据：`rtos_sim/schedulers/base.py:55`、`rtos_sim/schedulers/edf.py:16`
   - 影响：核心参数化路径已打通，后续需补齐更细粒度策略参数。

2. **UI 图形化配置已进入雏形阶段，仍需完善交互深度**
   - 现状：已支持多任务/多资源表格 CRUD、单任务 DAG 侧栏编辑、拖拽连线循环拦截、节点自由移动与自动布局；复杂 DAG 的多选编排/跨任务画布仍待实现。
   - 证据：`rtos_sim/ui/app.py:209`
   - 影响：基础建模效率明显提升，但复杂图编辑体验仍有提升空间。

3. **FR-13 对比视图已落地 MVP，仍需扩展**
   - 现状：已支持双方案指标对比与 JSON/CSV 差分导出，但尚未接入多方案聚合报告与论文模板。
   - 证据：`docs/04-详细版SRS.md:83`、`rtos_sim/ui/app.py:591`、`rtos_sim/cli/main.py:190`
   - 影响：基础对比能力可用，研究级批量分析产物仍需增强。

4. **模型关系导出已进入“基础自动判定”阶段，仍需向研究模板扩展**
   - 现状：`inspect-model` 已可导出任务/子任务/分段与核/资源双向关系表，并附带 `status/checks` 自动判定摘要。
   - 证据：`rtos_sim/analysis/model_relations.py:1`、`rtos_sim/cli/main.py:237`
   - 影响：语义闭环证据链已打通第一步，后续仍需接入更高层实验模板与自动判定规则。

### 2.3 P2（中期优化）
1. **性能治理已建立首版基线，仍需持续校准阈值**
   - 现状：已提供 `scripts/perf_baseline.py`（100/300/1000 tasks）与阈值门禁入口。
   - 证据：`scripts/perf_baseline.py:1`

2. **CI/CD 已建立回归门禁与构建产物，后续需补正式发布流水线**
   - 现状：已增加 Linux/Windows 测试 + Linux 性能报告工作流 + Python 发行包构建产物（`python-dist`）；PR 路径保留 100/300，nightly 增加 1000 非阻断趋势任务并输出昨日 delta 摘要。
   - 证据：`.github/workflows/ci.yml:1`
   - 影响：基础回归自动化已具备，仍需补打包发布链路。
   - 补充：nightly 昨日 delta 已改为按固定 `task_count` 严格匹配，避免误读其他 case 为基线（无匹配时降级 `no_base`）。

---

## 3. 已有设计参考在哪里（To-Be 依据）

### 3.1 需求与验收来源
- 需求与验收矩阵（AT-01~AT-07）：`docs/04-详细版SRS.md:61`
- SimPy 集成策略与阶段建议：`docs/07-开发评估与SimPy集成.md:8`

### 3.2 架构与接口来源
- 综合架构（模块边界、接口总览）：`docs/08-综合架构设计.md:13`
- 概要设计（模块职责、运行流程）：`docs/09-概要设计.md:24`
- 详细设计（事件字段、协议/ETM/UI约束）：`docs/10-详细设计说明书.md:74`

### 3.3 配置与数据模型来源
- Schema 基线与校验规则：`docs/05-配置文件Schema草案.md:1`
- 术语与数据模型基线：`docs/03-术语与数据模型草案.md:1`
- 时序图与类图：`docs/06-时序图与类图.md:1`

### 3.4 代码实现入口（直接参考）
- 仿真核心：`rtos_sim/core/engine.py:57`
- 配置加载：`rtos_sim/io/loader.py:29`
- CLI：`rtos_sim/cli/main.py:73`
- UI：`rtos_sim/ui/app.py:33`

---

## 4. 后续 Sprint 规划（建议 1–2 周/迭代）

### S7（研究口径收敛）执行清单
- 研究口径可执行 Issue backlog 与工时估算见：`docs/16-研究口径Issue拆解与排期.md`
- 本节继续保留阶段性里程碑说明；具体“做什么/谁先做/何时验收”以 `docs/16` 为准

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
- `core_count` 与 `platform.cores` 实际数量强一致校验已落地：`rtos_sim/model/spec.py:135`
- `batch-run --strict-fail-on-error` 已落地，失败子运行可返回非 0：`rtos_sim/cli/main.py:193`
- 回归：`tests/test_model_validation.py:153`、`tests/test_cli.py:75`

### Phase B（P1）已完成
- 动态实时随机区间到达（`min_inter_arrival + max_inter_arrival`）已落地：`rtos_sim/core/engine.py:678`
- 审计新增等待图死锁检测规则 `wait_for_deadlock`：`rtos_sim/analysis/audit.py:219`
- 回归：`tests/test_engine_scenarios.py:136`、`tests/test_audit.py:175`

### Phase C（P2）已完成（首轮）
- 性能基线默认场景已扩展至 100/300/1000：`scripts/perf_baseline.py:122`
- CI 性能任务分层：PR 路径 100/300，nightly 非阻断 1000 + 昨日 delta 摘要：`.github/workflows/ci.yml:68`
- 文档与命令示例已同步：`README.md:42`

### Phase D（研究可复现收敛）已完成（本轮）
- 统一到达过程 `arrival_process`（`fixed/uniform/poisson/one_shot/custom`）已落地，且保持 legacy 配置兼容：`rtos_sim/model/spec.py:76`、`rtos_sim/core/engine.py:686`
- 审计新增规则：`pip_priority_chain_consistency`、`pcp_ceiling_transition_consistency`：`rtos_sim/analysis/audit.py:220`
- 回归：新增到达过程与审计规则测试：`tests/test_engine_scenarios.py:229`、`tests/test_audit.py:91`、`tests/test_model_validation.py:201`

### Phase E（语义闭环）已完成（本轮）
- 新增 `inspect-model`：导出模型关系集合（任务/子任务/分段 与 核/资源双向关系）：`rtos_sim/cli/main.py:237`
- 新增关系提取模块：`build_model_relations_report` + `model_relations_report_to_rows`：`rtos_sim/analysis/model_relations.py:1`
- 审计报告新增 `model_relation_summary` 摘要挂载：`rtos_sim/analysis/audit.py:53`
- 回归：新增模型关系与 CLI 导出测试：`tests/test_model_relations.py:1`、`tests/test_cli.py:145`

### Phase F（配置治理与趋势可靠性）已完成（本轮）
- 移除废弃参数迁移入口：新增 `rtos-sim migrate-config`，支持 `event_id_validation` 自动清理并可输出迁移报告：`rtos_sim/cli/main.py:262`
- nightly 上一日基线提取改为固定文件名 `perf-nightly-1000.json`，避免 artifact 内多 json 时误选：`.github/workflows/ci.yml:196`
- `perf_delta` 改为按目标 `task_count` 严格匹配（无匹配不再回退首 case）：`scripts/perf_delta.py:20`
- 回归：新增 delta 严格匹配与迁移命令测试：`tests/test_perf_delta.py:62`、`tests/test_cli.py:341`

### Phase G（语义闭环深化）已完成（2026-02-22）
- 到达过程新增 `custom` 类型与生成器注册机制；`params.generator` 可选择注册生成器：`rtos_sim/model/spec.py:30`、`rtos_sim/arrival/registry.py:1`、`rtos_sim/core/engine.py:712`
- 审计报告新增 `rule_version` 与 `evidence` 字段，提升审计追溯性：`rtos_sim/analysis/audit.py:7`
- 审计报告新增 `protocol_proof_assets` 与 `pip_owner_hold_consistency`，增强协议可证明性证据：`rtos_sim/analysis/audit.py`（`build_audit_report` 聚合链路）、`rtos_sim/analysis/audit_checks/protocol_checks.py`
- 模型关系报告新增 `status/checks` 自动判定摘要：`rtos_sim/analysis/model_relations.py:42`
- 新增 docx 需求追踪矩阵：`docs/14-docx需求追踪矩阵.md`
- 回归：新增 custom 到达过程、审计证据字段、关系自动判定测试：`tests/test_engine_scenarios.py:360`、`tests/test_audit.py:388`、`tests/test_model_relations.py:56`

### Phase H（研究执行闭环）已完成（2026-02-22）
- R-001：研究反例基准集已落地（6 组 fail/fix 对照，共 12 案例）：
  - `examples/research_counterexamples.json`
  - `scripts/research_case_suite.py`
  - `tests/test_research_case_suite.py`
- R-002：审计证明资产与规则说明增强：
  - `rule_version` 升级至 `0.4`，新增 `check_catalog` 与失败事件定位字段：`rtos_sim/analysis/audit.py`
  - 新增证明资产统计（链深、owner 覆盖率、ceiling 未闭环比率）：`rtos_sim/analysis/audit.py`
- R-003：研究模板化报告生成能力已落地：
  - `rtos_sim/analysis/research_report.py`
  - `scripts/research_report.py`
  - `tests/test_research_report.py`
- R-004：CI 新增研究口径非阻断任务与产物：
  - workflow job `research_audit`：`.github/workflows/ci.yml`
  - artifacts：`research-audit-report`、`research-audit-summary`
- R-005：`inspect-model` 研究语义判定增强：
  - 新增 `resource_bound_core_consistency`、`time_deterministic_segment_binding_strict`
  - 新增 `compliance_profiles`（engineering_v1/research_v1）：`rtos_sim/analysis/model_relations.py`
  - 回归：`tests/test_model_relations.py`
- R-006：文档与追踪矩阵已同步至 S7：
  - `README.md`
  - `docs/14-docx需求追踪矩阵.md`
  - `docs/15-研究闭环验收基线.md`
  - `docs/16-研究口径Issue拆解与排期.md`

### Phase H-1（研究口径稳健性补强）已完成（2026-02-22）
- `research_case_suite` 匹配规则已收紧为严格一致：除 `missing_expected_checks` 外，新增 `unexpected_actual_checks` 作为失败信号，避免“额外失败项被忽略”。
- `research_report` 对同一 rule 多 issue 的聚合已完善：输出 `issue_count`、聚合后的 `sample_count` 与 `sample_event_ids`，避免仅取首条 issue 造成低估。

### Phase H-2（文档与可维护性收敛）已完成（2026-02-23）
- 文档事实快照已统一更新：主线文档统一以 `artifacts/quality/quality-snapshot.json` 作为事实源（当前基线 `404 passed / 89.05%`）。
- 历史首轮审查文档新增醒目提示，避免误读历史测试统计为当前状态：`docs/12-docx基线实施审查报告-2026-02-18.md`。
- `research_audit` Step Summary 增加 `research_v1`/`engineering_v1` 显式告警与失败规则摘要（保持 non-blocking）：`.github/workflows/ci.yml`。
- UI 可维护性低风险收敛：DAG 自动布局与表格校验逻辑拆分为独立模块，并新增对应单测：
  - `rtos_sim/ui/dag_layout.py`
  - `rtos_sim/ui/table_validation.py`
  - `tests/test_ui_helpers.py`

### Phase H-3（研究审计口径一致性收敛）已完成（2026-02-23）
- 研究报告补充 `non_audit_fail_details`，解决“总体失败但失败检查为空”可解释性问题：`rtos_sim/analysis/research_report.py`
- 模型关系 profile 状态语义升级为 `pass/warn/fail`，并区分 `failed_warn_checks/failed_error_checks`：`rtos_sim/analysis/model_relations.py`
- `inspect-model` 新增 `--strict-on-fail`：`status!=pass` 时可返回退出码 `2`：`rtos_sim/cli/main.py`
- CI `research_audit` 升级为多样例矩阵（`at01/at02/at06/at10`）并产出 `matrix-summary.json`：`.github/workflows/ci.yml`
- 回归：`tests/test_research_report.py`、`tests/test_model_relations.py`、`tests/test_cli.py`

### Phase H-4（官方样例语义口径收敛）已完成（2026-02-23）
- `segment_core_binding_coverage` 口径调整：对“迁移导向且无资源约束”的 `unbound` 仅记为 advisory，不再直接降级 `status`：`rtos_sim/analysis/model_relations.py`
- 官方样例 `at01~at10` 现已满足 `inspect-model --strict-on-fail` 全通过（语义门禁与迁移样例并存）：`examples/`
- 回归：`tests/test_model_relations.py`、`tests/test_cli.py`

### Phase H-5（M-09 证明级资产收敛）已完成（2026-02-23）
- 审计新增 `time_deterministic_ready_consistency`，用于校验 `SegmentReady.time` 与 `deterministic_ready_time` 对齐、以及跨超周期窗口的相位稳定性：`rtos_sim/analysis/audit.py`
- 审计新增 `time_deterministic_proof_assets`（`max_ready_lag/max_phase_jitter/issue_samples`），用于研究复现实验取证：`rtos_sim/analysis/audit.py`
- `research_v1` 合规画像新增必过项 `time_deterministic_ready_consistency`，补齐 M-09 机读门禁：`rtos_sim/analysis/audit.py`
- 回归：`tests/test_audit.py` 新增通过/失败双场景测试（稳定相位通过、相位抖动失败）。

### Phase I（论文图件生产与混合模式）已完成（2026-03-03）
- 缺口重定义：当前缺口不在产品功能，而在“可投稿级图件生产流水线”与文档落地规范。
- 边界约束：不改 `rtos_sim/core|model|cli|ui` 能力，仅新增离线科研图件脚本与提示词资产。
- 新增离线图件流水线（主文图 8 张 + 附录图 6 张，统一导出 PDF/PNG）：`scripts/paper_assets/build_dataset.py`、`scripts/paper_assets/plot_main_figures.py`、`scripts/paper_assets/plot_appendix_figures.py`、`scripts/paper_assets/style.py`
- 新增图件/数据可追溯清单导出（含哈希）：`scripts/paper_assets/export_manifest.py`
- 新增 Nano Banana Pro 概念图 Prompt 包（Graphical Abstract，含负向提示与版式约束）：`scripts/paper_assets/prompt_nano_banana.md`
- 混合模式执行口径：
  - 核心科研图（结果图/消融图/流程证据图）由本地脚本直接生成；
  - 封面感/概念图由外部绘图模型生成，并通过 Prompt 包做风格增强与约束。

### Phase J（工程治理深化：UI 第三刀 + CLI 二次拆分）已完成（2026-03-05）
- UI 继续去高聚合：
  - `rtos_sim/ui/panel_state.py`：面板状态集中化（compare/telemetry）。
  - `rtos_sim/ui/controllers/telemetry_controller.py`：hover/click/legend/state/reset 统一下沉。
  - `rtos_sim/ui/controllers/gantt_style_controller.py`：Gantt 样式与图例缓存逻辑下沉。
  - `rtos_sim/ui/panel_builders.py`：Planning/Compare 面板装配独立化。
- CLI 分层进一步收敛：
  - `rtos_sim/cli/parser_builder.py`：参数定义与命令绑定集中构建。
  - `rtos_sim/cli/handlers_planning.py`：`plan-static` / `analyze-wcrt` / `export-os-config` 三处理器独立。
  - `rtos_sim/cli/main.py` 当前约 `532` 行（已满足 `<700` 目标）。
- 防回退门禁：
  - 新增 `tests/test_ci_strict_plan_match_gate.py`，静态校验 CI 脚本中 WCRT/导出命令必须携带 `--strict-plan-match`。
- 本轮回归结果：
  - `python -m pytest --maxfail=1`：`404 passed`
  - 主链路命令（`validate` / `inspect-model --strict-on-fail` / `benchmark-sched-rate`）均通过。
