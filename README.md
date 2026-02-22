# rtos-sim

RTOS 异构多核调度仿真工具（SimPy + Pydantic + PyQt6）。

## 快速开始

```bash
python -m pip install -e .[dev]
```

可选安装 UI 依赖：

```bash
python -m pip install -e .[ui]
```

## CLI 用法

```bash
# 校验配置
rtos-sim validate -c examples/at01_single_dag_single_core.yaml

# 运行仿真并导出事件/指标
rtos-sim run -c examples/at01_single_dag_single_core.yaml \
  --events-out artifacts/events.jsonl \
  --metrics-out artifacts/metrics.json \
  --audit-out artifacts/audit.json

# 启动 UI（可选）
rtos-sim ui -c examples/at01_single_dag_single_core.yaml

# 批量实验（参数矩阵）
rtos-sim batch-run -b examples/batch_matrix.yaml

# 批量实验严格模式：任一子运行失败则返回非 0
rtos-sim batch-run -b examples/batch_matrix.yaml --strict-fail-on-error

# 对比两份指标文件（FR-13 MVP）
rtos-sim compare --left-metrics artifacts/base_metrics.json --right-metrics artifacts/new_metrics.json \
  --out-json artifacts/compare.json --out-csv artifacts/compare.csv

# 导出模型关系集合（任务/子任务/分段 与 核/资源）
rtos-sim inspect-model -c examples/at02_resource_mutex.yaml \
  --out-json artifacts/model_relations.json --out-csv artifacts/model_relations.csv

# 迁移旧配置并移除废弃参数（如 scheduler.params.event_id_validation）
rtos-sim migrate-config --in examples/at01_single_dag_single_core.yaml --out artifacts/migrated.yaml \
  --report-out artifacts/migrate_report.json

# 性能基线（100/300/1000 tasks，阈值可选）
python scripts/perf_baseline.py --tasks 100,300,1000 --max-wall-ms 1500,4000,12000

# 对比两份性能报告（周报）
python scripts/perf_compare.py --base artifacts/perf/base.json --current artifacts/perf/new.json

# 生成 nightly 昨日 delta 摘要（CI 同款）
python scripts/perf_delta.py --current artifacts/perf/perf-nightly-1000.json \
  --base artifacts/perf/perf-nightly-1000.base.json --out artifacts/perf/perf-delta-summary.json

# 生成测试/覆盖率质量快照（用于文档与评审同步）
python scripts/quality_snapshot.py --output artifacts/quality/quality-snapshot.json \
  --coverage-json artifacts/quality/coverage.json
```

## 测试

```bash
python -m pytest
```

## CI 合并门禁（S4）

- **硬门禁**：PR 必须通过 `python -m pytest -q`（Linux/Windows）
- **软门禁**：PR 性能任务默认跑 100/300 并产出报告；nightly 追加 1000 非阻断趋势任务与昨日 delta 摘要
- 性能报告位置：CI artifact `perf-baseline-pr`（`artifacts/perf/perf-baseline.json`）
- nightly 产物：`perf-nightly-1000`（原始报告）+ `perf-nightly-delta`（昨日对比摘要）

## 模型语义审查产物（S5）

- `inspect-model` 产出 docx 对齐关系表：
  - 任务/子任务/分段到核关系（含 `unbound`）
  - 任务/子任务/分段到资源关系
  - 核/资源反向关联集合
- 报告附带语义判定摘要：`status`（`pass/warn/fail`）+ `checks`（含规则级结果）
- 适用于“建模语义闭环”审查，不涉及性能优化目标。
- 需求追踪矩阵：`docs/14-docx需求追踪矩阵.md`（Docx 条目到代码/测试/审计规则映射）
- 研究闭环验收基线：`docs/15-研究闭环验收基线.md`（`compliance_profiles` 机读判定口径）

## 调度参数（S3）

- `scheduler.params.tie_breaker`：`fifo`（默认）/`lifo`/`segment_key`
- `scheduler.params.allow_preempt`：是否允许抢占（默认 `true`）
- `scheduler.params.event_id_mode`：`deterministic`（默认）/`random`/`seeded_random`
- `scheduler.params.event_id_validation`：已移除；请使用 `migrate-config` 清理旧字段
- `scheduler.params.resource_acquire_policy`：`legacy_sequential`（默认）/`atomic_rollback`
- `scheduler.params.etm`：`constant`（默认）/`table_based`
- `scheduler.params.etm_params`：ETM 参数对象（`table_based` 支持 `table` 与 `default_scale`）

## 核心速度口径

- 核运行速度采用乘积口径：`effective_core_speed = core.speed_factor * processor_type.speed_factor`
- 默认建议：`processor_type` 表示平台族速度，`core` 表示单核微调系数

## 指标口径（S4）

- `preempt_count`：兼容保留，等于 `scheduler_preempt_count + forced_preempt_count`
- `scheduler_preempt_count`：调度器正常抢占次数
- `forced_preempt_count`：`abort_on_miss` 导致的强制抢占次数
- `jobs_aborted`：因 `abort_on_miss` 被中止的作业数

## 版本说明

- 运行配置（模型）版本：`version: "0.2"`（由 `ConfigLoader` 校验）
- 批量实验配置版本：`examples/batch_matrix.yaml` 中 `version: "0.1"`（仅用于 batch 文件结构）
- 到达过程配置：新增 `tasks[*].arrival_process`（`fixed/uniform/poisson/one_shot/custom`），兼容旧字段 `arrival_model/min_inter_arrival/max_inter_arrival`
- `arrival_process.type=custom` 通过 `params.generator` 选择已注册生成器（内置 `constant_interval/uniform_interval/poisson_rate/sequence`）
- 配置迁移命令：`rtos-sim migrate-config --in <old> --out <new>`（会移除已废弃字段并可输出迁移报告）

## 样例

- `examples/at06_time_deterministic.yaml`：AT-06 时间确定性
- `examples/at07_heterogeneous_multicore.yaml`：AT-07 异构多核速度缩放
- `examples/at09_table_based_etm.yaml`：AT-09 表驱动 ETM 缩放
- `examples/at10_arrival_process.yaml`：统一到达过程（Poisson + One-shot）

## UI 配置编辑（S3）

- 支持结构化表单与 YAML/JSON 文本双向同步。
- 支持多任务/多资源表格化增删改（任务/资源可直接在表格编辑）。
- 支持 DAG 雏形编辑（单任务节点/边可视化 + 侧栏增删节点与边）。
- 支持 DAG 节点自由拖动（仅视图层）与自动布局重排。
- 支持 DAG 连线（Shift+左键拖拽或右键拖拽），内置循环检测并即时提示。
- 支持可选布局持久化（`ui_layout` 元数据，下次打开可复用）。
- 支持表格单元格强校验（错误高亮 + 提交前阻断）。
- 支持 FR-13 MVP 对比区：双方案指标差分 + JSON/CSV 导出。
- 右侧可视化区采用上下分栏（Gantt 与日志/对比分离），FR-13 对比区默认折叠。
