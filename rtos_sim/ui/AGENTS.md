# AGENTS.md（UI 作用域）

## 分层边界
- 不要继续把新功能堆进 `rtos_sim/ui/app.py`；`app.py` 只保留装配、状态持有、信号连接与委托。
- 新的 UI 行为优先下沉到 `controllers/`、`compare_io.py`、`worker.py`、`panel_state.py`、`panel_builders.py`。
- 复用既有报告 schema / 导出链路，除非需求明确要求，不新增一套平行协议。

## 回归要求
- UI 行为变更必须补对应回归：优先 `tests/ui/`，必要时补 `tests/test_ui_gantt.py`、`tests/test_ui_compare_io.py`。
- 涉及 Compare / Gantt / RunController 的状态契约变化，测试要覆盖“无数据提示”“成功路径”“导出路径”。
