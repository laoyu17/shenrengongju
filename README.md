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

# 性能基线（100/300 tasks，阈值可选）
python scripts/perf_baseline.py --tasks 100,300,1000 --max-wall-ms 1500,4000,12000

# 对比两份性能报告（周报）
python scripts/perf_compare.py --base artifacts/perf/base.json --current artifacts/perf/new.json
```

## 测试

```bash
python -m pytest
```

## CI 合并门禁（S4）

- **硬门禁**：PR 必须通过 `python -m pytest -q`（Linux/Windows）
- **软门禁**：性能任务只生成报告与 artifact，不阻断合并
- 性能报告位置：CI artifact `perf-baseline`（`artifacts/perf/perf-baseline.json`）

## 调度参数（S3）

- `scheduler.params.tie_breaker`：`fifo`（默认）/`lifo`/`segment_key`
- `scheduler.params.allow_preempt`：是否允许抢占（默认 `true`）
- `scheduler.params.event_id_mode`：`deterministic`（默认）/`random`/`seeded_random`
- `scheduler.params.event_id_validation`：`warn`（默认）/`strict`
- `scheduler.params.resource_acquire_policy`：`legacy_sequential`（默认）/`atomic_rollback`

## 指标口径（S4）

- `preempt_count`：兼容保留，等于 `scheduler_preempt_count + forced_preempt_count`
- `scheduler_preempt_count`：调度器正常抢占次数
- `forced_preempt_count`：`abort_on_miss` 导致的强制抢占次数
- `jobs_aborted`：因 `abort_on_miss` 被中止的作业数

## 版本说明

- 运行配置（模型）版本：`version: "0.2"`（由 `ConfigLoader` 校验）
- 批量实验配置版本：`examples/batch_matrix.yaml` 中 `version: "0.1"`（仅用于 batch 文件结构）

## 样例

- `examples/at06_time_deterministic.yaml`：AT-06 时间确定性
- `examples/at07_heterogeneous_multicore.yaml`：AT-07 异构多核速度缩放

## UI 配置编辑（S3）

- 支持结构化表单与 YAML/JSON 文本双向同步。
- 支持多任务/多资源表格化增删改（任务/资源可直接在表格编辑）。
- 支持 DAG 雏形编辑（单任务节点/边可视化 + 侧栏增删节点与边）。
- 支持 DAG 节点自由拖动（仅视图层）与自动布局重排。
- 支持 DAG 连线（Shift+左键拖拽或右键拖拽），内置循环检测并即时提示。
- 支持可选布局持久化（`ui_layout` 元数据，下次打开可复用）。
- 支持表格单元格强校验（错误高亮 + 提交前阻断）。
- 支持 FR-13 MVP 对比区：双方案指标差分 + JSON/CSV 导出。
