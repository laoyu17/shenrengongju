# AGENTS.md（仓库级开发约束）

## 项目关键不变量
- `run`、`analyze-wcrt`、`export-os-config` 在消费 `--plan-json` 时，默认按 `spec_fingerprint + semantic_fingerprint` 严格校验；仅 `--allow-plan-mismatch` 可显式放行。
- 正式 freeze 只承认 clean workspace 产物；dirty workspace 只能生成“历史证据型快照”，且必须显式标记 `dirty_workspace=true`。
- 对外行为、CLI、配置结构、架构边界变化必须同步主线文档；纯内部重构若不改外部行为，可只更新审查/执行记录。
- 所有 SHA、pytest、coverage、quality gate 数字，以 `artifacts/quality/quality-snapshot.json` 为唯一事实源。

## 变更前检查
- 先执行：`git fetch origin`、`git status --short`、`git branch --show-current`、`git log --oneline --decorate -n 5`。
- 先查最近作用域的 `AGENTS.md`；更细目录规则优先于本文件。
- 避免把新逻辑继续堆进巨型入口文件；UI 优先下沉到 `controller/helper/state`，CLI 优先复用已有 handler。

## 文档同步规则
- 行为/CLI/配置/架构变化：同步 `docs/` 对应设计、说明书、测试/交付文档。
- 风险状态、freeze 口径、交付事实变化：同步 `review/03-问题台账.csv` 与 `review/06-收口执行记录.md`，必要时同步 `review/02-审查总报告.md`。
- 改完主线文档后，运行 `python scripts/check_doc_baseline_consistency.py --snapshot artifacts/quality/quality-snapshot.json --docs-root docs`。

## 验证矩阵
- 先跑最小相关测试，再视影响面补 `python -m pytest -q`。
- 改 planning/CLI：至少覆盖 `tests/test_cli_planning_commands.py` 与相关脚本门禁测试。
- 改 UI 行为：至少覆盖 `tests/ui/` 或 `tests/test_ui_*.py` 对应回归。
- 改 freeze / review 证据链：至少验证脚本行为、quality snapshot、文档基线一致性。

## Git 极简规则
- 允许常规只读命令：`fetch`、`status`、`log`、`diff`。
- 禁止破坏性命令：`git reset --hard`、`git clean -fd`；未经明确要求，不直接推送 `main`。
- 如需访问 GitHub 远端，默认使用 SSH over 443 的现有环境配置；仓库内不维护大段连接排障说明。
