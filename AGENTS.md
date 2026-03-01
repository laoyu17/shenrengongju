# AGENTS.md（项目级 Codex 协作与 GitHub 规则）

## 0. 项目仓库基线（截至 2026-02-14）
- 本地仓库路径：`/mnt/hgfs/_code/simpytool/project`
- 远端仓库：`git@github.com:laoyu17/shenrengongju.git`
- 默认分支：`main`
- 当前基线提交：`d1ceb0b`

> 说明：后续 Codex 对话默认以本文件为 Git 协作规则与状态同步规则。

---

## 1. 每次 Codex 开始工作前必须执行
1. 同步远端信息：
   - `git fetch origin`
2. 检查本地状态：
   - `git status --short`
   - `git branch --show-current`
   - `git log --oneline --decorate -n 5`
3. 检查与远端分支差异：
   - `git rev-list --left-right --count origin/main...HEAD`

若发现本地落后 `origin/main`，先执行拉取再开始开发（见第 2 节）。

---

## 2. 拉取（Pull）规则
### 2.1 在 `main` 分支开发时
- 工作区干净：`git pull --rebase origin main`
- 工作区不干净：先提交本地改动，再 `pull --rebase`

### 2.2 在功能分支开发时
- 先同步主干：
  - `git fetch origin`
  - `git rebase origin/main`

### 2.3 禁止行为
- 禁止无明确指令时执行破坏性命令：`git reset --hard`、`git clean -fd`
- 禁止覆盖他人远端提交（除非用户明确要求并确认）

---

## 3. 提交（Commit）规则
### 3.1 提交格式（Conventional Commits）
- 格式：`type(scope): summary`
- 常用 type：
  - `feat`：新功能
  - `fix`：缺陷修复
  - `refactor`：重构（无行为变化）
  - `docs`：文档更新
  - `test`：测试补充/修复
  - `chore`：工程化杂项

示例：
- `feat(core): add deadline miss handling for abort_on_miss`
- `docs(architecture): align module boundaries with implemented code`

### 3.2 提交粒度
- 一次提交只做一类逻辑变更（单主题）
- 代码、测试、文档尽量同提交闭环
- 提交前至少运行：
  - `python -m pytest -q`

### 3.3 提交前检查清单
- 代码可运行、测试通过
- 无临时调试代码/无敏感信息
- 无无关文件变更

---

## 4. 推送（Push）规则
### 4.1 默认推荐流程（功能分支）
1. 新建分支：
   - `git checkout -b feat/<topic>`
2. 提交后推送：
   - `git push -u origin feat/<topic>`
3. 在 GitHub 发起 PR 合并到 `main`

### 4.2 直接推送 `main`（仅在用户明确要求时）
- `git push -u origin main`

### 4.3 推送失败排查（SSH）
1. `ssh -T git@github.com`
2. `ssh-add -l`
3. 无身份时：
   - `eval "$(ssh-agent -s)"`
   - `ssh-add ~/.ssh/id_ed25519`

---

## 5. 文档同步规则（保持后续对话“可感知最新状态”）
发生以下情况时，必须同步更新文档：
1. 架构边界、接口签名变化  
   - 更新：`docs/08-综合架构设计.md`、`docs/09-概要设计.md`、`docs/10-详细设计说明书.md`
2. 实施状态/问题/Sprint 变化  
   - 更新：`docs/11-实施现状问题与Sprint规划.md`
3. 配置结构或校验规则变化  
   - 更新：`docs/05-配置文件Schema草案.md`

---

## 6. 建议的 Codex 会话结束动作
1. 输出本次改动摘要（含文件与行号）
2. 说明测试执行结果
3. 若已提交，给出 commit hash
4. 若已推送，给出远端分支名

