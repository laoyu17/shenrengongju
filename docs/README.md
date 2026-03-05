# 文档导航与治理规则

## 1. 主线文档（Active）
以下文档作为当前版本的权威入口，持续维护并与代码实现同步：

- `01-需求规格说明书提纲.md`
- `02-架构图草案与模块接口定义.md`
- `03-术语与数据模型草案.md`
- `04-详细版SRS.md`
- `05-配置文件Schema草案.md`
- `06-时序图与类图.md`
- `07-开发评估与SimPy集成.md`
- `08-综合架构设计.md`
- `09-概要设计.md`
- `10-详细设计说明书.md`
- `11-实施现状问题与Sprint规划.md`
- `14-docx需求追踪矩阵.md`
- `15-研究闭环验收基线.md`
- `16-研究口径Issue拆解与排期.md`
- `18-综合审查报告-2026-02-24.md`
- `19-用户使用说明书.md`
- `20-审查问题台账.csv`
- `21-全量基线一致性校验记录-2026-02-24.md`
- `22-分阶段验收报告.md`
- `23-uml-fullstack.md`
- `24-高标准论文图件规划-混合模式.md`
- `25-设计方案报告全量追踪矩阵.md`
- `26-严格Docx验收矩阵.md`
- `26-需求分析报告.md`
- `26-测试细则.md`
- `26-测试报告.md`
- `26-用户维护及使用手册.md`
- `26-研制总结报告.md`
- `26-用户培训记录.md`
- `26-交付清单.md`

## 2. 归档文档（Archive）
阶段性评审与历史过程文档统一归档到 `docs/archive/`，默认只读，不作为当前主线结论依据。

当前归档目录：
- `archive/2026-02/12-docx基线实施审查报告-2026-02-18.md`
- `archive/2026-02/13-Phase实施与回归记录.md`
- `archive/2026-02/17-双基线综合审查报告-2026-02-23.md`
- `archive/2026-02/22-全量深审执行报告-2026-02-24.md`

## 3. 事实源与更新规则
- 主线文档涉及测试数、覆盖率、`git_sha` 时，统一以 `artifacts/quality/quality-snapshot.json` 为事实源。
- 历史阶段数字仅保留在归档文档，避免主线文档口径混杂。
- 文档中的代码引用优先使用稳定锚点（文件路径 + 函数/模块名）；对于频繁变动文件，避免依赖高风险行号。

## 4. UML 资产规则
- `docs/uml-src/*.puml` 是 UML 权威源。
- `docs/uml-src/png` 与 `docs/uml-src/svg` 视为可再生产物，不作为权威事实源。

## 5. 推荐复核命令

```bash
python scripts/quality_snapshot.py --output artifacts/quality/quality-snapshot.json \
  --coverage-json artifacts/quality/coverage.json
python scripts/check_doc_baseline_consistency.py --snapshot artifacts/quality/quality-snapshot.json \
  --docs-root docs
```
