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
  --metrics-out artifacts/metrics.json

# 启动 UI（可选）
rtos-sim ui -c examples/at01_single_dag_single_core.yaml

# 批量实验（参数矩阵）
rtos-sim batch-run -b examples/batch_matrix.yaml

# 性能基线（100/300 tasks）
python scripts/perf_baseline.py --tasks 100,300 --max-wall-ms 1500,4000
```

## 测试

```bash
python -m pytest
```

## 调度参数（S3）

- `scheduler.params.tie_breaker`：`fifo`（默认）/`lifo`/`segment_key`
- `scheduler.params.allow_preempt`：是否允许抢占（默认 `true`）
- `scheduler.params.event_id_mode`：`deterministic`（默认）/`random`/`seeded_random`

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
