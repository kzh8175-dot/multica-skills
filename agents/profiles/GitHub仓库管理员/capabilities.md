# GitHub 仓库管理员 · 能力档案

> **职责**：工作室所有 GitHub 仓库事务的唯一负责人（唯一提交通道）
> **最近更新**：2026-08-17

## 核心职责
- 创建 / 维护仓库（README、.gitignore、license、基础目录），设置描述、可见性、topic
- 维护仓库：文档与 README、分支与标签、issue 整理、PR 处理、CI 状态汇报
- 与其他智能体交接 GitHub 任务，交接用 @mention 明确接收方
- 通俗汇报：做了什么 → 结果如何 → 需要你做什么 / 下一步

## 持续学习

### 2026-08-17 · KA-53 报告归档移至 GitHub Release（方案 B）
- **任务**：把 `reports/reports-2026-08-Q3.tar.gz`（评分报告，聚合器运行生成产物）从代码仓库移出，改为 GitHub Release 附件归档；同步更新 UPLOAD_MANIFEST。
- **新技能 / 加深的技能**：
  - 用 `gh api repos/<owner>/<repo>/contents/<path> -H "Accept: application/vnd.github.raw"` 下载仓库二进制 blob，并用 `git show :<path> | shasum -a 256` + `git hash-object <file>` 双重校验与已提交内容逐字节一致。
  - 用 `gh release create <tag> <asset> --title --notes` 创建 Release 并上传附件；用 `gh release view <tag> --json assets` 校验附件名称 / 大小 / 状态。
  - 生成产物移出仓库的标准流程：Release 归档（附件先落盘）→ `git rm` → `.gitignore` 加整目录 → 分 commit（业务变更 / 清单更新）→ push main → 更新 UPLOAD_MANIFEST 记录 Release 链接。
  - 空目录 git 不追踪：移除唯一文件后目录在仓库内消失（GitHub contents API 返回 404），符合预期，无需额外处理。
- **挑战 / 盲区**：能力档案模板 `agents/capability-system/template.md` 尚未存在（目录内仅 .gitkeep），首次按 Agent Identity 要求章节自建档案。
- **改进**：
  - Ownership 模式应在动手前先置 `in_progress`，收尾置 `in_review`（本次直接在完成后置 `in_review`）。
  - 涉及生成产物入库时，先判断是否为开发必需；非必需者直接走 Release 归档流程，减少返工。

### 2026-08-17 · KA-56 README 增加报告 Release 归档说明
- **任务**：把 README 目录结构中的 reports 段从「tar.gz 入库」更新为「生成产物不入库（已 .gitignore）」，并在「说明」前新增「报告归档（Release）」章节，指向 reports-2026-08-Q3 Release。
- **新技能 / 加深的技能**：
  - 文档与仓库实际状态一致性维护：归档移入 Release 后，README 中的目录结构/描述需同步更新，避免 README 与真实状态脱节。
  - 在 README 引用 Release 链接前，用 `gh release view <tag> --json isDraft,isPrerelease,assets` 先校验该 Release 已发布且非 draft，避免文档指向不存在的链接。
  - 遵循需求方给出的精确 diff 描述逐字落实（只改指定文件、指定行），`git diff` 自检确认无其他改动后 push。
- **挑战 / 盲区**：需求方描述的报告中「58 个」→新章节「116 份」数量不一致，按需求方给定的文案照实写入，不自行改动。
- **改进**：README 类文档变更可按任务描述直接落盘，无需额外设计流程；引用外部链接先验证可用性。

## 协作关系
- KA-53 无跨智能体协作评分（本任务由资深战略领导者提供执行方案，直接执行）。
- KA-56 无跨智能体协作评分（直接执行文档变更任务）。

## 待提升的方向
- 熟练掌握 GitHub API 二进制内容下载与一致性校验（raw + sha256 + git hash-object）。
- 每次上传后养成在 UPLOAD_MANIFEST 标注白名单检查结论的习惯。

## 更新记录

| 日期 | 版本 | 更新内容 |
|------|------|----------|
| 2026-08-17 | v0.1 | 首次建档：KA-53 任务后的能力评估与学习记录 |
| 2026-08-17 | v0.2 | 追加 KA-56：README 报告归档说明更新 + Release 链接有效性校验 |
