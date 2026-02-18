# RTOS 异构多核仿真工具：实施现状、问题清单与 Sprint 规划

## 0. 文档控制
- 版本：v0.2
- 状态：S2+（协议一致性与审计补强）
- 日期：2026-02-18
- 适用范围：`project/` 当前实现（代码 + 文档 + 测试）

## 1. 已经实现的内容（As-Is）

### 1.1 架构与工程化基线
- 已完成包结构落地（`core/events/model/schedulers/protocols/etm/overheads/metrics/io/cli/ui`）与依赖配置：`project/pyproject.toml:1`
- 已提供 CLI 入口与 UI 入口脚本：`project/pyproject.toml:31`
- 已补充运行说明与命令示例：`project/README.md:5`

### 1.2 核心仿真链路（SimPy）
- 引擎已支持 `build/run/step/pause/reset/stop` 生命周期与事件推进：`project/rtos_sim/core/engine.py:101`
- 已接入调度器、资源协议、ETM、开销模型插件点：`project/rtos_sim/core/engine.py:105`
- 已实现关键运行事件：释放、就绪、开始、结束、阻塞/唤醒、抢占、迁移、deadline miss、完成：`project/rtos_sim/core/engine.py:320`
- 已实现 deadline miss 与 `abort_on_miss` 行为分支：`project/rtos_sim/core/engine.py:623`
- 已修复 deadline 边界触发与 abort 中止隔离语义（避免中止后再次调度）：`project/rtos_sim/core/engine.py:320`
- 已统一 EDF+PCP 优先级域（运行时绝对 deadline 域），并支持运行时 ceiling 刷新：`project/rtos_sim/core/engine.py:247`、`project/rtos_sim/protocols/pcp.py:35`
- 已补齐 abort/cancel 异常路径的 `ResourceRelease` 事件：`project/rtos_sim/core/engine.py:1119`

### 1.3 配置模型与语义校验
- 已实现 `0.1 -> 0.2` 配置兼容迁移：`project/rtos_sim/io/loader.py:83`
- 已实现 Schema 校验 + Pydantic 语义校验：`project/rtos_sim/io/loader.py:38`
- 已实现关键语义约束（DAG 无环、ID 唯一、引用完整性、mapping_hint 有效性）：`project/rtos_sim/model/spec.py:138`
- 已收紧 `time_deterministic` 定点约束（多核场景需可推导/显式 mapping_hint）：`project/rtos_sim/model/spec.py:244`

### 1.4 插件化能力（MVP）
- 调度器：EDF / RM + 注册机制：`project/rtos_sim/schedulers/registry.py:15`
- 调度器参数：`tie_breaker / allow_preempt` 已生效（S3 第一阶段）：`project/rtos_sim/schedulers/base.py:55`
- 资源协议：Mutex + PIP + PCP（优先级更新语义）：`project/rtos_sim/protocols/mutex.py:10`、`project/rtos_sim/protocols/pip.py:9`、`project/rtos_sim/protocols/pcp.py:9`
- ETM：Constant（`wcet / core_speed`）：`project/rtos_sim/etm/registry.py:14`
- 开销模型：Simple 常量开销：`project/rtos_sim/overheads/registry.py:22`
- 指标聚合：响应时间、超期率、抢占（调度/强制拆分）、迁移、利用率：`project/rtos_sim/metrics/core.py:63`

### 1.5 CLI 与 PyQt6 UI
- CLI 支持 `validate/run/ui/batch-run` 命令：`project/rtos_sim/cli/main.py:95`
- `run` 支持审计报告导出 `--audit-out`（协议/异常路径一致性检查）：`project/rtos_sim/cli/main.py:81`、`project/rtos_sim/analysis/audit.py:14`
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

### 1.6 测试与样例
- 已新增 8 个样例（含 AT-06/AT-07 与批量实验矩阵）：`project/examples/at06_time_deterministic.yaml:1`、`project/examples/at07_heterogeneous_multicore.yaml:1`
- 已实现模型/引擎/CLI 自动化测试：`project/tests/test_model_validation.py:41`、`project/tests/test_engine_scenarios.py:22`、`project/tests/test_cli.py:12`
- 已新增审计模块与 UI worker 真线程/直执行回归：`project/tests/test_audit.py:1`、`project/tests/test_ui_worker.py:1`
- 当前本地测试状态：`python -m pytest -q` 通过（80 tests）
- 当前覆盖率快照：总 86%、engine 89%、loader 57%、pcp 97%、ui/worker 86%（`python -m pytest --cov=rtos_sim --cov-report=term-missing -q`）

### 1.7 已修复：UI 有指标但 Gantt 无线段
- 根因：`SimulationWorker` 在 `engine.build()` 前订阅事件，而 `build()` 内部 `reset()` 重建了事件总线，导致 UI 事件流被清空。
- 修复：引擎新增订阅者持久化，`reset()` 后自动重新挂载外部订阅者，保证 UI/外部监听不丢事件：`project/rtos_sim/core/engine.py:79`
- 体验增强：Gantt 支持 Task/Subtask/Segment 三层编码，避免颜色层级混乱：`project/rtos_sim/ui/app.py:460`
- 体验增强：悬停命中改为 scene 鼠标检测，并提供右侧详情面板（支持点击锁定）：`project/rtos_sim/ui/app.py:532`
- 回归：新增测试覆盖“build/reset 后订阅依然有效”：`project/tests/test_engine_scenarios.py:65`
- 回归：新增 UI 交互与表单同步测试（含表格 CRUD、DAG 侧栏编辑、未知字段保留）：`project/tests/test_ui_gantt.py:39`
- 回归：新增 DAG 拖拽连线循环检测、节点自由移动、自动布局、可选布局持久化与表格校验阻断测试：`project/tests/test_ui_gantt.py:344`
- 当前本地测试状态：`python -m pytest -q` 通过（80 tests）

---

## 2. 当前存在的问题（Gap / Risk）

### 2.1 P0（需优先收敛）
1. **PCP 仍为 MVP 语义（未覆盖全部经典约束证明路径）**
   - 现状：已修复 EDF/PCP 优先级域不一致与异常路径事件缺口，但尚未形成“证明级”系统天花板分析报告。
   - 证据：`project/rtos_sim/protocols/pcp.py:10`、`project/rtos_sim/analysis/audit.py:14`
   - 影响：研究级可证明性仍需补充。

### 2.2 P1（近期应补齐）
1. **调度器参数已从“透传”进入“基础生效”，但参数域仍需继续扩展**
   - 现状：`tie_breaker/allow_preempt` 已在 EDF/RM 生效，尚未覆盖更多算法级业务开关。
   - 证据：`project/rtos_sim/schedulers/base.py:55`、`project/rtos_sim/schedulers/edf.py:16`
   - 影响：核心参数化路径已打通，后续需补齐更细粒度策略参数。

2. **UI 图形化配置已进入雏形阶段，仍需完善交互深度**
   - 现状：已支持多任务/多资源表格 CRUD、单任务 DAG 侧栏编辑、拖拽连线循环拦截、节点自由移动与自动布局；复杂 DAG 的多选编排/跨任务画布仍待实现。
   - 证据：`project/rtos_sim/ui/app.py:209`
   - 影响：基础建模效率明显提升，但复杂图编辑体验仍有提升空间。

3. **FR-13 对比视图仍未落地**
   - 现状：当前 UI 具备 Gantt 与指标文本，但尚无多方案并列对比视图。
   - 证据：`project/docs/04-详细版SRS.md:83`、`project/rtos_sim/ui/app.py:447`
   - 影响：实验分析与论文取证仍依赖离线脚本/外部表格对比。

### 2.3 P2（中期优化）
1. **性能治理已建立首版基线，仍需持续校准阈值**
   - 现状：已提供 `scripts/perf_baseline.py`（100/300 tasks）与阈值门禁入口。
   - 证据：`project/scripts/perf_baseline.py:1`

2. **CI/CD 已建立首版回归门禁，后续需补发布流水线**
   - 现状：已增加 Linux/Windows 测试 + Linux 性能报告工作流（软门禁）。
   - 证据：`project/.github/workflows/ci.yml:1`
   - 影响：基础回归自动化已具备，仍需补打包发布链路。

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
