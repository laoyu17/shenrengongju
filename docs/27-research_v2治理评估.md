# research_v2 治理评估（2026-03-08）

## 1. 结论

- 当前 `research_v2` 适合作为**增强证据 + 可见性门禁**，暂不升级为硬性 merge gate。
- 本轮先完成两件事：
  - 在 `.github/workflows/ci.yml` 的 `Research Audit (non-blocking)` Step Summary 中显式展示 `research_v2` 状态。
  - 固化一套可复核的升级条件 / 不升级条件 / 复评时点，避免后续再靠口头判断。

## 2. 当前事实

### 2.1 已具备的基础

- `rtos_sim/analysis/research_report.py` 已将 `research_v2` 纳入 `statuses` 与 `profiles`，并把它并入 overall status 计算。
- `rtos_sim/analysis/audit.py` 已定义 `research_v2` 所需检查集合，说明它不是临时概念，而是已有明确规则的 profile。
- `Research Audit` CI job 已稳定产出以下产物：
  - `artifacts/research/research-report.json`
  - `artifacts/research/research-case-summary.json`
  - `artifacts/research/matrix/matrix-summary.json`

### 2.2 当前仍不足以升为硬 gate 的点

- `.github/workflows/ci.yml` 中 `Research Audit` 仍显式设置为 `continue-on-error: true`，当前治理定位仍是 non-blocking。
- 本轮改动前，CI Step Summary 只展示 `research_v1` / `engineering_v1`，没有把 `research_v2` 暴露给主线审阅者；失败时可见性不足。
- multi-case matrix 产物虽然已有 `report_status`，但此前没有把每个 case 的 `research_v2` 状态显式写进 summary；出现失败时，定位成本仍偏高。
- 当前仓库里没有现成的“连续稳定通过窗口”与“失败样本可解释性”升级标准，因此直接升为硬 gate 会让门槛与证据不对称。

## 3. 升级条件

只有当下面条件**同时满足**时，才建议把 `research_v2` 从 non-blocking 升级为更强 gate：

1. **可见性条件**
   - CI Step Summary 持续展示 `research_v2` 当前状态。
   - matrix summary 能指出 `research_v2` 未通过的 case 名称，失败后无需额外翻 JSON 才能初步定位。

2. **稳定性条件**
   - 自 2026-03-08 这轮可见性增强落地后，`main` 分支至少积累 **7 次连续非 schedule 的成功 CI 运行**。
   - 在这 7 次运行中，`Research Audit` job 虽保持 non-blocking，但 `research_v2` 在主报告和 matrix 中都为 `pass`。

3. **解释性条件**
   - 当 `research_v2` 不通过时，summary / artifacts 能同时提供：
     - 失败规则名；
     - 失败 case 名；
     - 对应审计产物位置（通过现有 `research-report.json` / matrix 产物即可追到）。
   - 失败结果不能表现为“只知道 fail，但不知道为什么 fail”。

4. **样本质量条件**
   - counterexample suite 与 multi-case matrix 在同一观察窗口内都保持可解释的稳定结果。
   - 不存在反复出现、但无法复现或无法归因的 flaky fail。

## 4. 不升级条件

只要出现下面任一情况，就不建议把 `research_v2` 升为硬 gate：

- `Research Audit` 仍需要依赖 `continue-on-error: true` 才能避免误伤主线开发效率。
- `research_v2` 虽被计算，但主线 summary 仍不能直接告诉审阅者它是否失败、失败在哪个 case。
- matrix 仍只能给出总体 `report_status`，但不能快速定位到 `research_v2` 维度的失败样本。
- 观察窗口内出现无法稳定复现的失败，或失败样本缺少足够解释性。
- 升级后会让主线 merge 被研究型证据误阻断，而仓库还没有形成对应的排障流程与责任归属。

## 5. 复评时点

- **最早复评日期：2026-03-22**。
- 复评前提：到该日期时，或在该日期之后的最近一次评估时点，已经满足“自 2026-03-08 起累计 7 次连续非 schedule `main` CI 运行成功”的观察窗口。
- 若到 2026-03-22 仍未形成足够观察窗口，则继续维持 non-blocking，并顺延到下一次满足窗口后的评估时点复核。

## 6. 本轮决策

- 本轮只把 `research_v2` 提升到“**必须可见、必须可解释**”的层级，不提升到硬 gate。
- 这样做的原因不是否定 `research_v2`，而是先补齐“看得见 + 说得清 + 能复盘”的治理前提，再决定是否让它直接阻断合并。

## 7. 最小验收方式

执行下面检查即可复核本评估是否落地：

1. 查看 `.github/workflows/ci.yml` 的 `Add research summary` 步骤，确认 summary 中显式输出 `research_v2`。
2. 查看 `.github/workflows/ci.yml` 的 matrix 汇总逻辑，确认每个 case 会写入 `research_v2` 状态，且 summary 能列出 `matrix.research_v2_failed_cases`。
3. 查看 `docs/27-research_v2治理评估.md`，确认存在：
   - 升级条件；
   - 不升级条件；
   - 复评时点；
   - 本轮保持 non-blocking 的明确结论。
