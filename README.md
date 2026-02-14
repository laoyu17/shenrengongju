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
```

## 测试

```bash
python -m pytest
```
