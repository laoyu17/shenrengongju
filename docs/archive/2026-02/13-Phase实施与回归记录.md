# Phase 实施与回归记录

- 记录日期：2026-02-18
- 目标：按 Phase A/B/C 连续实施并在每个阶段完成验证、回归、提交

## Phase A（P0）

### 变更项
- 增加 `processor_types.core_count` 与 `platform.cores` 数量一致性校验
- 增加 `batch-run --strict-fail-on-error`（存在失败子运行时返回非 0）

### 关键文件
- `rtos_sim/model/spec.py`
- `rtos_sim/cli/main.py`
- `tests/test_model_validation.py`
- `tests/test_cli.py`

### 阶段验证
- `python -m pytest tests/test_model_validation.py tests/test_cli.py -q`
- `python -m pytest -q`

### 提交记录
- commit: `8f5863a`

---

## Phase B（P1）

### 变更项
- 动态实时任务新增随机区间到达能力：`min_inter_arrival + max_inter_arrival`
- 审计模块新增等待图死锁检测：`wait_for_deadlock`
- 补充随机到达与死锁检测回归测试

### 关键文件
- `rtos_sim/model/spec.py`
- `rtos_sim/io/schema.py`
- `rtos_sim/core/engine.py`
- `rtos_sim/analysis/audit.py`
- `rtos_sim/protocols/mutex.py`
- `tests/test_engine_scenarios.py`
- `tests/test_audit.py`

### 阶段验证
- `python -m pytest tests/test_model_validation.py tests/test_engine_scenarios.py tests/test_audit.py tests/test_cli.py -q`
- `python -m pytest -q`
- `python -m pytest --cov=rtos_sim --cov-report=term-missing -q`

### 提交记录
- commit: `66a458b`

---

## Phase C（P2）

### 变更项
- 性能基线默认场景扩展至 `100/300/1000`
- CI 性能任务同步扩展到 `100/300/1000`
- README / 现状文档同步更新

### 关键文件
- `scripts/perf_baseline.py`
- `.github/workflows/ci.yml`
- `README.md`
- `docs/11-实施现状问题与Sprint规划.md`
- `docs/05-配置文件Schema草案.md`
- `docs/10-详细设计说明书.md`

### 阶段验证
- `python scripts/perf_baseline.py --tasks 100,300,1000 --threshold-version phase-c-2026-02-18 --output artifacts/perf/perf-baseline-phasec.json`
- `python -m pytest -q`

### 提交记录
- commit: `HEAD（phase-c 当前提交）`

---

## Phase D（研究可复现收敛）

### 变更项
- 引入统一到达过程 `arrival_process`：`fixed/uniform/poisson/one_shot`，并兼容 legacy 到达字段
- 审计新增协议一致性规则：`pip_priority_chain_consistency`、`pcp_ceiling_transition_consistency`
- 补充到达过程/审计规则回归测试与样例 `examples/at10_arrival_process.yaml`

### 关键文件
- `rtos_sim/model/spec.py`
- `rtos_sim/io/schema.py`
- `rtos_sim/core/engine.py`
- `rtos_sim/analysis/audit.py`
- `tests/test_model_validation.py`
- `tests/test_engine_scenarios.py`
- `tests/test_audit.py`
- `examples/at10_arrival_process.yaml`

### 阶段验证
- `python -m pytest tests/test_model_validation.py tests/test_engine_scenarios.py tests/test_audit.py -q`
- `python -m pytest -q`

### 提交记录
- commit: `HEAD（phase-d 当前提交）`
