# GitHub 仓库管理员 · 能力档案

> **职责**：工作室所有 GitHub 仓库事务的唯一负责人（唯一提交通道）
> **最近更新**：2026-08-17

## 核心职责
- 创建 / 维护仓库（README、.gitignore、license、基础目录），设置描述、可见性、topic
- 维护仓库：文档与 README、分支与标签、issue 整理、PR 处理、CI 状态汇报
- 与其他智能体交接 GitHub 任务，交接用 @mention 明确接收方
- 通俗汇报：做了什么 → 结果如何 → 需要你做什么 / 下一步

## 持续学习

### 2026-08-17 · KA-71 P1-6 能力档案模板提交入库（并行建档冲突合并）
- **任务**：代 技术文档撰写者 提交并推送 KA-71 交付物（`agents/capability-system/template.md` 新模板 + `agents/profiles/技术文档撰写者/capabilities.md`）至 `main`，按白名单检查 + UPLOAD_MANIFEST 登记。
- **新技能 / 加深的技能**：
  - 同一智能体在并行 run（KA-71 / KA-73）各自「首次建档」同一能力档案路径时，后到者基于旧 main 的 `git cherry-pick` 会**静默覆盖**已入库版本：base 无此路径、ours/theirs 均新增时，cherry-pick 按 theirs 直接替换、不报冲突——push 前必须 `git diff origin/main HEAD -- <path>` 核对**内容**而非只看 stat。
  - 发现覆盖后正确做法：`git reset --hard origin/main` 回退 → 手工合并两份版本（保留双方学习记录 / 协作关系，更新记录升版本）→ `grep` 逐条核对关键段落齐全 → 再提交推送。
  - 接收交接先 `git ls-tree origin/main -- <path>` 检查目标路径是否已存在，判断是「新增」还是「更新」，避免重复建档 / 覆盖在途交付。
- **挑战 / 盲区**：cherry-pick 输出「2 files changed, create mode」易被误读为无冲突；实际目标文件已被替换，内容级核对才能发现。
- **改进**：后续交接推送一律先查远程目标路径存在性；内容核对用 `git diff` + grep 关键段落，不信 stat。

### 2026-08-17 · KA-54 生产树收尾：KA-19 OSError 加固「仓库 == 生产」复核
- **任务**：把生产树最新 commit 的 `rating-settler.py` OSError 加固版同步进 multica-skills 仓库，保持「仓库 == 生产」。
- **新技能 / 加深的技能**：
  - 用 `gh api repos/<owner>/<repo>/commits?path=<file>` 查某文件在 main 的提交历史，确认「目标内容由哪个 commit 引入」；与 `git log origin/main -- <file>` 交叉验证。
  - 用 `git ls-remote origin main` + `gh api .../commits/main` 双重确认远程 main 实时 SHA；任务描述 / issue 中的 SHA 是快照，一律以实时远程为准。
  - 「仓库 == 生产」的正确核验方法是逐文件 SHA256 对比（生产路径 ↔ 仓库 src/ 路径映射），而非对比 commit 历史（生产树与仓库是两个独立 git 仓库）。
  - push 前再 `git fetch` 一次防并发推进；发现远程 main 被其他 run 推进时，先 `git rebase origin/main` 再 push（本次被 KA-53 的 README commit 并发推进，rebase 后干净推送）。
- **挑战 / 盲区**：
  - 任务描述称「仓库 main 缺 OSError 加固（main=98f5d84）」，但 live main 已含 `f7c6677` 同步——不能照搬描述，须以实时远程核对为准。
  - 生产树未提交改动在执行期间被 DevOps 并发提交（fe41250/f7d8c14），首查与复核状态不同；以「最终提交后」状态为准做验收。
- **改进**：
  - 做一致性核验先 `git fetch` 拉最新远程；push 前再 fetch 一次。
  - 发现同步已由先前 commit 完成时，不做无意义空提交；用 UPLOAD_MANIFEST 补录凭据 + 复核说明来闭环追溯。

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
- KA-71 与 技术文档撰写者 协作（交接 KA-71 交付物入库），评分 4/5：交付物附件齐全、目标仓库/分支/用途明确；改进——并行 run 重复建档未预先对齐，入库时需仓库侧合并去重。
- KA-54 与 DevOps自动化工程师协作（生产提交 fe41250/f7d8c14，仓库复核闭环），评分 4/5：分工清晰、各自职责内快速闭环；改进——仓库侧可先声明同步状态再等对方提交，减少并行窗口。
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
| 2026-08-17 | v0.3 | 追加 KA-54：仓库==生产 SHA 复核法、实时远程核对、并发 push 处理；协作评分 |
| 2026-08-17 | v0.4 | 追加 KA-71：并行建档冲突的 cherry-pick 静默覆盖识别与手工合并；协作评分 |
