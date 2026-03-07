# AGENTS.md（docs 作用域）

## 文档事实源
- 行为、CLI、配置、架构变化必须同步 `docs/` 主线文档。
- 所有 SHA、pytest、coverage、quality gate 数字，只能来自 `artifacts/quality/quality-snapshot.json`。
- 需要引用审查结论时，以 `review/02-审查总报告.md`、`review/03-问题台账.csv`、`review/06-收口执行记录.md` 为准，不手写与快照冲突的数字。

## 更新规则
- 改 CLI/行为：同步 `docs/19-用户使用说明书.md`、`docs/26-用户维护及使用手册.md`、`docs/26-测试细则.md`、`docs/26-测试报告.md`。
- 改设计/架构：同步 `docs/08-综合架构设计.md`、`docs/09-概要设计.md`、`docs/10-详细设计说明书.md`、`docs/11-实施现状问题与Sprint规划.md`。
- 纯内部重构若不影响外部行为，可不改用户手册，但必须在 `review/06-收口执行记录.md` 或相应审查记录留痕。

## 验证要求
- 改完 `docs/` 后运行：`python scripts/check_doc_baseline_consistency.py --snapshot artifacts/quality/quality-snapshot.json --docs-root docs`。
- 若改到锚点密集文档，再补：`python scripts/check_doc_reference_integrity.py --repo-root .`。
