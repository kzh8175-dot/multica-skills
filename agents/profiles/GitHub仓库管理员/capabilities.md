# GitHub 仓库管理员 · 能力档案

> **职责**：工作室所有 GitHub 仓库事务的唯一负责人（唯一提交通道）
> **最近更新**：2026-08-17

## 核心职责
- 创建 / 维护仓库（README、.gitignore、license、基础目录），设置描述、可见性、topic
- 维护仓库：文档与 README、分支与标签、issue 整理、PR 处理、CI 状态汇报
- 与其他智能体交接 GitHub 任务，交接用 @mention 明确接收方
- 通俗汇报：做了什么 → 结果如何 → 需要你做什么 / 下一步

## 持续学习

### 2026-08-17 · KA-103 智能看板交付物入库（从 issue 评论附件拉取 → `dashboard/` 目录 + manifest 登记）
- **任务**：从 KA-98（迭代 1）/ KA-99（迭代 2）评论附件拉取 dashboard 交付物（`index.html` / `generate-dashboard-data.py` / `dashboard-data.js` / `README.md`）提交至 `kzh8175-dot/multica-skills` 新建 `dashboard/` 目录，登记 UPLOAD_MANIFEST，保持「仓库 == 生产」约定（与 `src/rating-system` 同级）。
- **新技能 / 加深的技能**：
  - **无交接分支/commit 的「附件交付」入库模式**：交付物挂在 issue 评论附件上——`multica issue comment list --roots-only --summary` 定位评论 → `--thread <id> --tail` 展开附件清单（含 attachment id / filename / size_bytes）→ `multica attachment download <id> -o <workdir>/attachments` 落盘。
  - **跨迭代版本甄别**：同一文件（generator / data js）迭代 1 与迭代 2 各附一版——以最新迭代（KA-99）为准；大小可作判据（迭代 2 generator 19621B < 迭代 1 19817B，符合「#8/#9 删死逻辑/死代码」预期）；`index.html` / `README.md` 仅迭代 1 有，直接取 KA-98。
  - **白名单检查在附件下载后执行**：逐文件归属核对（4 文件全项目代码/数据/文档，截图属验收证据不入库）→ secret 扫描（token/key/password/绝对路径）→ Python 语法编译 `py_compile` → 生成数据文件结构校验（正则截取 JSON + 计数断言 63/24/141 与交付声明一致）。
  - **入库副本与附件同源校验**：`shasum -a 256` 对照附件副本与 `dashboard/` 副本逐字节一致，确保提交版本与验收附件同源。
  - **新建顶层 `dashboard/` 目录**并同步根 README 目录结构（与 `src/` 同级，对齐生产树 `prod/dashboard` 与 `prod/rating-system` 同级约定）。
- **挑战 / 盲区**：交付物分散在多个 issue 且跨迭代版本不同，需先读评论历史确认最新版；附件下载偶发超时，需 `MULTICA_HTTP_TIMEOUT` 提升重试。
- **改进**：附件交付类任务先按 issue 定位全部候选附件并比较版本/大小，再决定取哪一版；UPLOAD_MANIFEST 上传事项注明「从附件拉取 + 迭代版本说明」便于追溯。

### 2026-08-17 · KA-100 缺陷修复入库（未提交工作区交接 + 代码审查员/资深战略领导者三方口径对齐）
- **任务**：代 开发者工具工程师 提交并推送 KA-100 缺陷修复（`--baseline` 静默空操作 + 写失败退出码契约，`src/state-change-hook.py` + `src/test-state-change-hook.py` 50→56 + `docs/state-change-hook-test-report.md` + README + 开发者工具工程师能力档案 v0.9，共 5 文件，run `a7e2cdaa` 工作副本未提交）至 `kzh8175-dot/multica-skills` 的 `main`，白名单检查 + 交付点复跑 + UPLOAD_MANIFEST 登记。
- **新技能 / 加深的技能**：
  - **未提交工作区交接的「跨 run 嵌套 checkout」定位**：交付物不在 run 根 workdir，而在其内部嵌套 checkout（`<run>/workdir/multica-rating-system/multica-skills`，本笔 run `a7e2cdaa`）——先 `find <workspace> -name <目标文件>` 按文件名定位嵌套路径，再 `git status` + `git diff --stat` 核对 5 文件与交接声明逐项吻合（145+/12- 与源码工作区完全一致）。
  - **交接已由代码审查员/终审核验时的仓库侧闭环**：终审确认「复核通过但未入库」→ 仓库侧不是重新审代码，而是按既有入库流程闭环：白名单逐文件（5 文件全项目代码/测试/文档，无敏感信息，secret 扫描零命中）+ 交付点复跑测试（钩子 56 + 全仓 165 Python + 8 bash 全绿，与交接声明一致）+ UPLOAD_MANIFEST 登记 → 回传落地 commit。非阻塞项（KA-101）已由终审立项跟踪，不入本笔。
  - **两 commit 交付模式（内容 commit + manifest/能力档案登记 commit）**：内容 commit 用交接方建议信息，manifest 登记 commit 沿用仓库既有模式（`docs: UPLOAD_MANIFEST 登记 … + GitHub 仓库管理员能力档案 v0.x`），保持 main 历史一致性。
- **挑战 / 盲区**：交接方工作区文件未 commit 未推送，需跨 run 定位嵌套 checkout 并比对 diff 与交接声明；终审把「入库动作」明确派发给仓库管理员，仓库侧须在推送后回传「落地 commit」形成闭环（回传 hash 为 main 落地 hash `9229d10`，非工作副本 hash）。
- **改进**：交接回帖声明「已核验 + 建议提交信息 + 来源 run 号」时，仓库侧可直接以建议提交信息落笔、按声明复跑核对后推送；涉及 5 文件含能力档案的交付，manifest 描述把「代码修复 + 测试 + 报告 + 档案」分层写清便于对账。

### 2026-08-17 · KA-98 #7 CLI 分页拉取入库（交接分支独立 worktree + 提交快照复跑 + cherry-pick 线性合入）
- **任务**：代 开发者工具工程师 推送并合入 KA-98 迭代 1 · #7 CLI 分页拉取（分支 `agent/agent/a8d3d955`，基于 KA-97 迭代 0 `a411267`；新增 `4362127` 分页 + `e47276f` 能力档案 v0.8）至 `kzh8175-dot/multica-skills` 的 `main`，白名单检查 + UPLOAD_MANIFEST 行 15 登记。
- **新技能 / 加深的技能**：
  - **交接分支被自己 worktree 占用时的合入路径**：交接方分支 `agent/agent/a8d3d955` 已在其 runtime worktree（`a8d3d955/workdir/...`）checkout，`git rebase`/`git checkout <branch>` 均报「already checked out at ...」——先 `git worktree add --detach /tmp/xx <commit>` 在干净快照复跑测试（feed 35/35 + 全量回归），再用「从 main 建 delivery 分支 + `git cherry-pick` 两 commit」线性合入，不动交接方分支 ref。
  - **交付基线双确认**：交接声明 commit 与实测一致（本笔 `4362127`/`e47276f` 即分支 tip），以「干净 worktree 复跑测试 + diff 逐文件比对 + merge-base 判定」为准；本笔 merge-base = `a411267`（KA-97 迭代 0 已在 main），实际增量仅 2 个 commit，UPLOAD_MANIFEST 记录 main 侧新 hash `64cfeb1`+`80054e1` 而非原 hash，避免「记录 hash 与 main 实际不一致」。
  - **main 被旧 worktree 占用时的快进更新**：`main` 已在先前 run 的 worktree（`49260984/workdir/...`）checkout，无法本地 checkout/merge——用 `git update-ref refs/heads/main <tip>` 快进 ref（非破坏性，纯前移），推送 `origin/main` 后旧 worktree 自然落后无害。
- **挑战 / 盲区**：交接分支基于 KA-97 迭代 0 `a411267` 而非 main tip `f1e64cf`（差一个 manifest 登记提交）——不能直接快进，需先判定「a411267 已在 main」再决定 cherry-pick 而非 merge；交付方建议「连同 a411267 合入」其实已满足（此前已入库），须在回传时说明避免重复合入。
- **改进**：接收基于旧 main 的交接时先查 merge-base 与 main 是否已含基底 commit；交付 hash 一律记录 main 侧落地 hash，并向交接方回传「原 hash → main hash」对照。

### 2026-08-17 · KA-97 迭代 0 #3 单一数据源收敛入库（交接后分支继续演进识别 + 交付点双重核验）
- **任务**：代 开发者工具工程师 推送并合入 KA-97 迭代 0 · #3 单一数据源收敛（分支 `agent/agent/b6bcd25e`，E-02 修复 `8fe891e` 为基底，feed 单一源 + 删 loader 分叉 + 回归，UPLOAD_MANIFEST 行 14）至 `kzh8175-dot/multica-skills` 的 `main`，白名单检查 + UPLOAD_MANIFEST hash 回填。
- **新技能 / 加深的技能**：
  - **交接后分支继续演进的识别**：交接 comment 声明 commit `f96f15f`（21 条用例），但实际推送时分支 tip 已是 amend 后的 `a411267`（22 条，新增 loader 多事件 `;` 原始串契约回归）——用 `git reflog show --date=iso agent/agent/<id>` 确认提交时间线：交接 comment（13:41）之后 13:43 仍有一次 amend，交付方 run 把工作区未提交的 loader 用例并入提交。推送**当前 tip** 而非按 comment 字面 hash，交付点以「分支 tip + 测试实测 + manifest 描述」三重一致为准。
  - **交付点双重核验**：① 交接方工作区 vs 干净 worktree 快照（`git worktree add /tmp/xx <commit>`）复跑测试——工作区含未提交改动（22 条）≠ 提交快照（21 条），以**提交快照**为准判定交付基线；② 对最新 tip 复跑 feed 22/22 + 全量回归 + secret 扫描 + 白名单逐文件（6 文件：README/manifest/能力档案/接口文档/feed/测试，全部项目文件无敏感信息）。
  - **两 commit 关联交付的合并**：E-02 修复（`8fe891e`，manifest 行 13）与 KA-97 收敛（`a411267`，行 14）同分支先后落地，main 快进 `9b04004..a411267` 一次到位，两条 manifest 记录分别回填对应 commit hash。
  - **分支 ref 与工作区 HEAD 一致性的坑**：`git branch -a` 的 ref 解析可能滞后于交接方工作区 HEAD（工作区已在最新 commit 而共享 ref 仍指向旧 hash），推送前用 `git rev-parse <branch>` + `git log -1` 双确认分支真实 tip。
- **挑战 / 盲区**：交接 comment 的 commit hash 与推送时实际 tip 不一致（交接后 amend），若按字面 hash 推送会漏掉 loader 用例回归；需要从 reflog + 测试计数 + manifest 描述交叉判断「哪个才是最终交付态」。
- **改进**：涉及代码交接时不以 comment 中的 commit hash 为唯一依据，推送前始终 `git fetch` + 复核分支 tip、在干净 worktree 复跑测试并记录「comment 声明 vs 实测 tip」差异，向交接方回传最终实际 hash。

### 2026-08-17 · KA-76 P2-11 状态变更钩子入库（未提交工作区交接 + 交接声明与实测不一致校准）
- **任务**：代 开发者工具工程师 提交并推送 KA-76 P2-11 状态变更钩子（`src/state-change-hook.py` + `src/test-state-change-hook.py` 50 条用例 + `scripts/run-state-change-hook.sh` + `config/crontab-rating.conf` 第 0 项 + `docs/state-change-hook-test-report.md` + 开发者工具工程师能力档案 v0.5 + README 结构更新）至 `kzh8175-dot/multica-skills` 的 `main`，白名单检查 + UPLOAD_MANIFEST 登记。
- **新技能 / 加深的技能**：
  - **未提交工作区交接的定位与核验**：交接方声明「本地已备好」但交付物为未提交的 modified + untracked 文件、未推远程分支——先在 workspace 根 `find` 按文件名定位交接方 runtime 工作区（本次 `798d0807/workdir/multica-skills`）→ `git status` 区分 modified/untracked → `git diff HEAD` 核对改动内容与交接声明逐项吻合。
  - **分支基不一致时的合并基判定**：交接方分支基 `bc61276` 落后 origin/main 4 个 commit（KA-80/KA-79/KA-96 等）→ `git diff origin/main bc61276 -- <path>` 逐文件判定基一致（crontab / 开发者能力档案 两基相同 → 整文件 cp 无损）；README 双份改动不重叠（开发者的 src/scripts 列表 vs main 的系统报告节）→ 手工 hunk 合并，而非整文件覆盖。
  - **交接声明与实测不一致的校准**：交接回帖声称「50 条用例 / 139 Python」、README 与测试报告却写「49 / 133 / main 集成 5 条」→ 本地复跑 `test-state-change-hook.py` 实得 **50 tests OK**、回归 15+11+24+24+15+50=**139** → 推送前将 README 与测试报告校准为实测值（49→50、5→6、133→139），避免把自相矛盾的验收文档推上 main。
  - **代码类交接的验收基线**：白名单逐文件（7 文件：src×2 + scripts + docs + config + README + 开发者能力档案，全部项目代码/测试/文档，无敏感信息）+ 凭据特征 grep 零命中 + 交付点复跑 50/50 与回归 139 Python 全通过 + `--dry-run` 逻辑审查（幂等设计：last_status 跟踪 / 自动 baseline / pending 延后 / credited 去重）。
- **挑战 / 盲区**：交接方未把改动提交到分支、也未推送远程，仓库侧须跨 runtime 定位工作区；README 因 main 并发推进已含 KA-80 系统报告节，不能整文件 cp，需按 hunk 合并；测试计数文档与实际跑测不符，需以实测为准校准后才推送。
- **改进**：代码/文档交接统一要求交接方「commit 到分支并推送」或附「文件 sha256 + 基于哪个 main」；仓库侧对含测试面的交付一律复跑测试并比对交接声明中的用例数，发现不一致先校准文档再推送。

### 2026-08-17 · KA-79 P2-14 异常处理 SLA 合并定稿入库（交接版本演进识别 + 并发交付冲突合并 + 白名单检查）
- **任务**：代 技术文档撰写者 提交并推送 KA-79 P2-14 异常处理 SLA（合并定稿 v1.0，含事故响应指挥官响应侧设计：S1~S4 分级 / 响应-处置-恢复矩阵 / L1~L4 升级路径，`docs/exception-handling-sla.md` + `docs/runbook.md` §3 交叉引用 + `agents/profiles/技术文档撰写者/capabilities.md` v0.4，commit `bdb252b`）至 `main`，白名单检查 + UPLOAD_MANIFEST 登记。
- **新技能 / 加深的技能**：
  - **交接版本演进识别**：回复触发 comment 前先扫描 thread 全部评论——本任务触发评论为「初稿交付」（P1~P4 / L0~L3），但稍后同 thread 有更新的「合并定稿 v1.0」评论（S1~S4 / L1~L4）以新提交目的再次交接；以**最新权威 handoff**为准，发现已提交内容被取代即回退重建，避免把过期初稿推上 main。
  - 交接消息未附分支/commit 时定位交付物：在 workspace 根目录 `find` 定位交接方工作区内的本地 clone → `git rev-parse agent/agent/<id>` 与 `git rev-parse origin/main` 核对分支基 → `git rev-parse <branch>:<path>` 逐文件 blob 对比 base 版本 → 整文件 `cp` 无损携带修改；交付期间交接方工作区文件会被其**并行 run 继续改写**（初稿→合稿），推送前须复查 mtime 与内容，不能只信首次拷贝。
  - 纯文档交付的验收基线：白名单逐文件（全部项目文档，无 secret/隐私）+ 凭据特征 grep 扫描零命中 + 交接声明与 diff 逐项对照 + 交付文件 sha256 比对。
  - 文档类交付沿用「内容 commit +（UPLOAD_MANIFEST 登记 + 自身能力档案合并）两 commit」模式。
  - **并行交付冲突处理**：交付期间 origin/main 被同仓库其他交付（KA-80）并发推进，与本次改同一批文件（UPLOAD_MANIFEST 行号、GitHub 仓库管理员能力档案 / 技术文档撰写者能力档案）→ `git rebase origin/main` 手工合并：manifest 行重新编号（KA-79=#11、KA-80=#12，按时间序）、能力档案两份学习记录/协作记录/更新记录并留、版本号顺延（v0.11→v0.12）、并 preserve 对方已入库的 KA-80 学习记录（交接方本地文件不含，须从 main 手工并入）。
- **挑战 / 盲区**：交接方把三处变更留在自己工作区、未推远程分支，且初稿→合稿、main 并发推进多重并发叠加，需多次核对 base 与内容归属，判定「哪个文件版本才是最新权威」。
- **改进**：文档类交接可要求交接方在定稿后统一交接（附「基于哪个 main 生成」+ 文件 sha256），并在 thread 显式宣告「以此为准」；仓库侧推送前复查交接方工作区 mtime 与最新评论。

### 2026-08-17 · KA-80 P2-15 系统报告整合入库（纯文档交付的验收基线 + 分支/main 双推送）
- **任务**：代 技术文档撰写者 提交并推送 KA-80 P2-15 系统报告整合（`docs/system-report-spec.md` 统一输出规范 + `docs/report-templates/` 三份模板 + README「系统报告」节重写 + 技术文档撰写者能力档案 v0.3，commit `edb8d27`，分支 `agent/agent/e4bfafab`）至 `main`，白名单检查 + UPLOAD_MANIFEST 登记。
- **新技能 / 加深的技能**：
  - **纯文档交付（无代码/测试面）的验收基线**：分支基判定（交付 commit 父 == origin/main HEAD → 直接快进保原 hash，本次 `edb8d27` 父即 `bc61276`）+ 白名单逐文件核对（6 文件：docs 规范 ×1 + 模板 ×3 + README + 交接方能力档案，全部项目文档/模板，无敏感信息）+ 全 diff secret 扫描干净 → 推送 → 清单登记 hash；文档交付无需复跑测试，但须核对内容口径「只引用不复制」——规范引用 `docs/runbook.md` §6 与 `docs/dashboard-data-interface.md` §3，未内嵌重复口径。
  - **交接含「目标分支」时的双推送**：先 `git push origin agent/agent/<id>` 保留交接分支（本次为新分支），再 `git push origin agent/agent/<id>:main` 快进 main（`bc61276..edb8d27`），保原 commit hash、追溯链完整。
  - **报告产物 vs 规范/模板的归档二分**：README「系统报告」节落地「产物不入库（`reports/` gitignore → Release tag `reports-{YYYY}-Q{n}`）、规范/模板/索引入库」——仓库侧后续收到报告产物交接时按 Release 归档流程处理，不放入代码仓库。
- **挑战 / 盲区**：纯文档交付无测试基线可复跑，验收以「文件清单 + 内容口径引用关系 + secret 扫描」为限；模板中「升级时限」标注「P2-14 交付后并入 SLA 表」属前置依赖占位（P2-14 KA-79 运行中），非未落地断言，放行。
- **改进**：文档交付类交接统一「分支基判定 → 白名单逐文件 + secret 扫描 → 双推送（分支 + main 快进）→ 清单登记」流程；报告产物类交接后续走 Release 归档，区分「入库」与「Release」两类交付物。

### 2026-08-17 · KA-96 看板只读数据接口入库（交接分支本地定位 + 交付点快照复跑 + 清单 hash 回填闭环）
- **任务**：代 开发者工具工程师 推送 KA-96 里程碑 1 看板只读数据接口（commit `0093c62`，分支 `agent/agent/72131425`：`src/dashboard-data-feed.py` 只读 JSON 接口 + `src/test-dashboard-data-feed.py` 15 条用例 + `docs/dashboard-data-interface.md` Schema v1.0 + README 结构更新 + 能力档案 v0.4 + UPLOAD_MANIFEST 登记行）至 `main`，白名单检查 + 清单 hash 回填。
- **新技能 / 加深的技能**：
  - 交接分支未推远程时的本地定位：`git branch -a` 确认本地 object store 内存在 `agent/agent/<id>` 分支 → `git cat-file -t <commit>` 确认 commit 可达 → `git log --oneline <branch>` 核对基与内容——本任务分支基恰为当前 main（`bb8f6ce`），单 commit 直接快进 push（`git push origin agent/agent/<id>:main`）。
  - 只读接口类交付的验收基线：白名单逐文件核对（6 文件：src×2 + docs + README + UPLOAD_MANIFEST + 开发者能力档案，全部项目代码/测试/文档，无敏感信息）+ **交付点快照复跑**（`git worktree add --detach 0093c62` 上跑 `python3 src/test-dashboard-data-feed.py` 15/15 OK）+ 全 diff secret 扫描干净 + `git merge-base` 分支基核对（merge-base == origin/main HEAD）。
  - UPLOAD_MANIFEST「待推送回填」闭环：交接方登记行预留 hash 占位 → 仓库侧推送后回填真实 commit（`0093c62`），并同步将分支推进到新 main 后 `--ff-only` 对齐本地，保持清单追溯链完整。
- **挑战 / 盲区**：交接方本地分支未推远程（远程仅 main 与历史 agent 分支），commit 只在 `multica repo checkout` 拉取的本地共享 object store 内可达，需先定位再推送；能力档案改动文件是交接方自己的 `agents/profiles/开发者工具工程师/capabilities.md`（非仓库管理员档案），白名单按同样标准核对内容。
- **改进**：代码交付类交接统一「分支基判定（ff vs cherry-pick）→ 交付点快照复跑测试 → 白名单逐文件 → secret 扫描 → 推送 → 清单回填 hash」流程；测试命令与预期结果随交接文档可复现。

### 2026-08-17 · KA-75 P1-10 联调落地入库（多 commit 交付组装：快进 + cherry-pick）
- **任务**：代 开发者工具工程师 推送 KA-75 P1-10 联调落地（spec §6.2 四项待办，commit `98b4aa1`，分支 `agent/agent/40cb306a`）+ 登记 软件架构师 spec/ADR 终审修订版（commit `bc7d1d6`，分支 `agent/agent/d1398c19`）至 `main`，白名单检查 + UPLOAD_MANIFEST 登记。
- **新技能 / 加深的技能**：
  - **一次交付、两份交接的组装**：代码 commit（`98b4aa1`）父 commit 恰为当前 main（`d9e3641`）→ `git merge --ff-only` 保原 hash；文档 commit（`bc7d1d6`）基于旧 main `55b422e`、main 已推进 → `git cherry-pick` 重放（docs-only 无冲突），UPLOAD_MANIFEST 登记以重放后 hash（`7e5eba7`）为准、附注原 commit 便于追溯。
  - 联调类交付的验收基线：测试面更广（防失真 24 / judge 24 / settler 11 / 聚合器 15 = 74 Python + 调度器 8 项 bash），逐套复跑与交接声明逐项吻合后才推送；关键行为变更（S+单评分人+R-32 → B）从测试断言与端到端冒烟双向确认。
  - 白名单检查对「联调改动既有生产模块」的重点：`git show --stat` 文件清单 + 全 diff secret 扫描 + diff 与交接声明四项待办（签名扩展 / judge 退役 / 冒号归一化 / sha256）逐条对照，确认改动面收敛、无无关文件。
- **挑战 / 盲区**：交接方本地分支均未推远程（远程仅 main 与历史 agent 分支），需先在工作区共享 object store 内定位两 commit；两份交付基不同（一为 main 快进、一为旧 main 重放），组装顺序与清单 hash 引用分别处理。
- **改进**：多 commit 交付入库统一「判定分支基（ff vs cherry-pick）→ 组装 → 全套测试复跑 → 白名单 → 清单登记真实 hash」流程；交接回帖注明文档 commit 原 hash。

### 2026-08-17 · KA-92 审核返工入库（返工交付的基线复跑 + 交付 commit 与权限边界核对）
- **任务**：代 开发者工具工程师 提交并推送 KA-92 审核返工（等级表 ☑ 残留修复 + 规则编号订正 R-61/R-62~R-66 + P2 同修 4 项，judge 22/22）至 `main`，白名单检查 + UPLOAD_MANIFEST 登记。
- **新技能 / 加深的技能**：
  - 返工交付的验收基线：除白名单检查外，在**交付 commit 快照**（`git worktree add --detach <commit>`）上复跑全部测试再入库——本任务在提交点复现 judge 22/22 + 聚合器15/结算器10/防失真19/调度器category 4 + anti-fraud 4 全通过，与交接声明逐项吻合后才推送；避免只在「主分支最新」上跑测试而漏验交付点内容。
  - 权限边界核对：交接方已是唯一开发者时，先确认其职责与 commit 内容一致（等级表纯函数化 / 规则编号以 rulebook v1.0 为基准订正 / P2 四项），且提交目的与 commit message 对应，再放行推送；返工类交付仍走 main 直接快进（本任务分支基即当前 main `55b422e`，无需 cherry-pick）。
  - 白名单检查对「能力档案类」文件（`agents/profiles/*/capabilities.md`）与代码类文件一视同仁：看内容是否含 secret/隐私/无关文件——本任务 6 文件全部为 src/docs/README/能力档案，无敏感信息。
- **挑战 / 盲区**：交接含「单评分人标注（E-02，非平均）」等文案改动，须从测试断言与报告行确认改动确已生效（`git diff` + 测试断言逐项对照），不能只看文件数。
- **改进**：返工/修复类交接统一「交付点快照复跑测试 + 白名单逐文件核对 + 权限边界确认」三步后再入库。

### 2026-08-17 · KA-75 P1-10 防失真机制自动化入库（代码交付类交接的验收基线复跑）
- **任务**：代 开发者工具工程师 提交并推送 KA-75 P1-10 防失真机制自动化实现（`src/anti-distortion-rules.py` + S-1 结算器去重键修复 + 调度器接入 + 测试套件）至 `main`，白名单检查 + UPLOAD_MANIFEST 登记。
- **新技能 / 加深的技能**：
  - 代码交付类交接的验收基线：除文件清单 + secret 扫描外，**本地复跑全套测试**再入库——本任务交付承诺「68 条 Python + 8 项 bash 全通过」，逐一执行 `test-anti-distortion-rules.py`(19)/`test-rating-settler.py`(10)/`test-rating-aggregator.py`(15)/`test-quarterly-review-judge.py`(20)/`test-anti-fraud-scheduler.sh`(4)/`test-review-scheduler-category.sh`(4) 全部复现 OK 后才推送；测试报告文档与实测结果互相印证。
  - 交接分支与 main 的「干净快进」判定：`git log --oneline agent/agent/<id> -N` 看父 commit 是否即 origin/main HEAD——本任务分支基恰为当前 main（`ebd31a6`），单 commit 直接快进 push，无需 cherry-pick 重放（对比 KA-84 落后 main 需重放的情形）。
  - 修改既有生产文件（rating-settler.py / review-scheduler.sh）的入库前核对：看 diff 是否与交接声明一致（S-1 去重键 `(issue_id, rating.event)`、B1/B2 修复委托新计数），改动面收敛、无无关变更。
- **挑战 / 盲区**：交付物含「修复既有测试仓库布局路径」的旁支改动（test-*.py 路径引用），初看与 KA-75 主题无关，实为使全套测试在本仓库可跑的前置修复——判定依据：改动仅 2 行路径引用，且必须随代码一并入库否则测试不可运行。
- **改进**：代码交付统一先跑测试基线再白名单放行；测试命令与预期结果写进交付回帖的验收口径，推送后核对一次 main 状态。

### 2026-08-17 · KA-84 项目负责人能力档案入库（交接分支落后 main 的 cherry-pick 重放）
- **任务**：代 项目负责人 提交并推送 KA-84 P1 立项确认会能力档案（`agents/profiles/项目负责人/capabilities.md` v0.1，R-42 execution + 六章节）至 `main`，白名单检查 + UPLOAD_MANIFEST 登记。
- **新技能 / 加深的技能**：
  - 交接分支（`agent/agent/<id>`）基于旧 main 时不能直接快进 push——先 `git log origin/main..<branch>` + `git merge-base` 判断祖先关系：本任务交接 commit `6148615` 的父是 `13b7d80`，而 origin/main 已推进到 `a5092c9`（含 KA-74 三个 commit），直接推送会回退 main；正确做法是 `git checkout -b <new> origin/main` → `git cherry-pick <commit>` 重放交付。
  - 能力档案类交付白名单检查要点：`git show --stat <commit>` 核对文件清单 + secret 扫描（password/token/key/绝对路径/`.env`）+ 确认目标路径远程不存在（`git ls-tree origin/main -- <path>`，本任务为项目负责人首次建档，纯新增无冲突）；能力档案属项目文档，允许入库。
  - 三 commit 落地模式：内容 commit（cherry-pick 交付）→ UPLOAD_MANIFEST 登记 commit（引用重放后真实 hash）→ 自身能力档案更新 commit（KA 学习记录）。
- **挑战 / 盲区**：交接消息只给「本地分支 + commit」，本地 commit hash 在 main 推进后无法原样上 main；需自行核对分支基与 origin/main 的祖先关系，决定重放方式，且清单登记的 hash 以重放后为准。
- **改进**：交接方给的 branch/commit 一律视为「基于其 run 时 main 的本地快照」；推送前 `git fetch` + `git rev-parse origin/main` 复核，再决定快进 / cherry-pick 重放。

### 2026-08-17 · KA-74 P1-9 季度人评自动判定脚本入库（并发 main 推进 + UPLOAD_MANIFEST 冲突处理）
- **任务**：代 开发者工具工程师 提交并推送 P1-9 季度人评表单自动判定脚本（`src/quarterly-review-judge.py` + 测试 + 测试报告，20/20 通过）至 `main`，白名单检查 + UPLOAD_MANIFEST 登记。
- **新技能 / 加深的技能**：
  - 交接交付物校验流程：`git show --stat <commit>` 核对文件清单 → 逐文件白名单检查 → 跑验收测试 → secret 扫描（password/token/key/绝对路径）→ 再入库。UPLOAD_MANIFEST 行内字段（开发/验收/审批/提交上传需求）按 RACI 口径逐列填齐，并追加「——已通过白名单检查（…）」。
  - 交付 commit 内已含 UPLOAD_MANIFEST 行（「待提交」占位）时的标准做法：cherry-pick 时**丢弃该行**（保留 main 版本），内容 commit 与清单登记分两个 commit——内容 commit 落 src/docs/README，清单登记 commit 引用内容 commit 真实 hash（沿用 KA-71/KA-73 既定两 commit 模式）。
  - 并行 run 会推进 main：本次 checkout 后 `origin/main` 从 `87dff7f` 推进到 `13b7d80`（同角色 KA-71 run 补录能力档案 v0.4）。`git diff origin/main HEAD` 多出「非本次改动的文件」时，先 `git rev-parse <ref>:<path>` 逐 ref 比对 blob，再用 `git branch -a --contains <commit>` 定位新 commit，确认是远程推进而非本地意外改动。
  - push 前必做 `git fetch origin` 复核 `origin/main`；发现推进即 `git rebase origin/main`，rebase 后 commit hash 变化 → **amend 更新 UPLOAD_MANIFEST 行内引用的内容 commit hash 与登记 commit 消息**，避免清单指向旧 hash。
- **挑战 / 盲区**：`git diff --stat origin/main HEAD` 出现 capabilities.md 的 11 行删除，初看像本地误改；实为 `origin/main` 远程引用已推进（我的分支仍基于旧 main）。判定要点：先确认本地是否真的改过该文件（`git log origin/main..HEAD -- <path>` 为空即非本地改动），再 fetch 对齐远程。
- **改进**：所有推送前统一 `git fetch` + `git rev-parse origin/main` 与本地 base 比对；交付物入库前先跑一遍验收测试 + secret 扫描再 cherry-pick。

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
- KA-103 与 前端工程师 协作（交接 dashboard 交付物入库），评分 5/5：交付物以 issue 评论附件形式齐全提供（index.html / generate-dashboard-data.py / dashboard-data.js / README，迭代 1+2 各一版，版本/大小可甄别，截图证据 9 张），交付说明覆盖每项 P1 改动要点、测试基线（feed 15/15 + dashboard↔feed 24/24 一致）与渲染验证；改进——交接可直接附「以最新迭代版本为准」的版本选择提示，减少仓库侧跨 issue 甄别成本。
- KA-100 与 开发者工具工程师 + 代码审查员 + 资深战略领导者 协作（代提交 KA-100 缺陷修复入库，三方口径对齐），评分 5/5：终审给出明确入库指令（来源 run `a7e2cdaa` 工作副本 5 文件 + 建议提交信息 + 交付点复跑要求），代码审查员已独立实跑核验（baseline 写路径 / 退出码契约 / 56+165+8 全绿），仓库侧按既有入库流程闭环即可；改进——若终审能同时给出「待推送确认后置 done」的收口条件，交付闭环更明确。
- KA-98 #7 与 开发者工具工程师 协作（交接 KA-98 CLI 分页拉取入库），评分 5/5：交付清单四要素（文件/分支 `a8d3d955`/两 commit/提交目的）齐全、测试基线明确（feed 22→35 + 全量回归 + 生产实跑等价验证）、交接时说明基线（基于 KA-97 迭代 0）便于仓库侧判定增量；改进——交接注明「基于 KA-97 迭代 0」的同时可确认该基底是否已合 main，仓库侧可直接按「剩两 commit」准备合入，减少一次 merge-base 核验。
- KA-76 与 开发者工具工程师 协作（交接 KA-76 P2-11 状态变更钩子入库），评分 4/5：交付清单四要素（文件/提交目的/目标仓库）齐全、幂等设计与事件映射文档完备、测试基线声明明确（50 用例 / 139 Python）；改进——改动未 commit 未推送（仅留在交接方工作区），且 README/测试报告的用例数与交接声明、实测不符，仓库侧需定位工作区、复跑校准后才推送。
- KA-79 与 技术文档撰写者 协作（交接 P2-14 异常处理 SLA 文档入库），评分 4/5：交付物清单明确（3 处变更 + 目标仓库 + 提交目的），交接方工作区定位与 base 核对成本低（分支基即当前 main，整文件拷贝即可）；改进——交接未附 commit/分支与文件校验和，仓库侧需先在 workspace 内定位工作区并逐文件 blob 对比 base。
- KA-80 与 技术文档撰写者 协作（交接 KA-80 P2-15 系统报告整合入库），评分 5/5：交付清单四要素（文件/分支/commit/提交目的）齐全、目标仓库明确、纯文档交付无歧义，分支基即当前 main 可直接快进双推送（分支 + main），白名单检查前置完成；改进——纯文档交付可附内容口径引用清单（引用了 runbook/接口契约哪一节），仓库侧核对「只引用不复制」更省力。
- KA-96 与 开发者工具工程师 协作（交接 KA-96 里程碑 1 看板只读数据接口入库），评分 5/5：交付清单（文件/分支/commit）+ 测试基线（15/15）+ 生产实跑验证（59 agents / 34 事件行 / 7 预算项 / pending 22）明确，分支基即当前 main 可直接快进，UPLOAD_MANIFEST 预留「待推送回填」占位便于仓库侧闭环回填；改进——测试命令已在接口契约文档注明，仓库侧可直接复跑。
- KA-75 联调落地与 开发者工具工程师 + 软件架构师 协作（交接 P1-10 联调落地代码 + spec/ADR 终审修订版文档入库），评分 5/5：代码 commit 基即当前 main 可直接快进、文档 commit 独立标注原 hash 便于重放，测试基线 74 Python + 8 bash 明确可复现；改进——交接可注明两份交付的 commit 各自基于哪个 main，减少仓库侧判定组装方式（ff/cherry-pick）的成本。
- KA-92 与 开发者工具工程师 协作（交接 KA-92 审核返工入库），评分 5/5：交付清单（文件/分支/commit）+ 测试基线（judge 22/22 + 全量回归）明确，提交点在快照上复跑全部复现，分支基即当前 main 可直接快进；改进——返工类交接附「修复后新增用例」说明，仓库侧可对照断言核验改动确已生效。
- KA-75 与 开发者工具工程师 协作（交接 KA-75 P1-10 防失真机制自动化入库），评分 5/5：交付清单（文件/分支/commit）+ 测试基线（68 条 Python + 8 项 bash）明确，本地复跑全部复现，分支基即当前 main 可直接快进；改进——测试命令可一并附在交接回帖，减少仓库侧从测试报告反查命令的成本。
- KA-84 与 项目负责人 协作（委派 KA-84 能力档案入库），评分 4/5：交付物路径/分支/commit 明确、白名单检查前置完成；改进——交接 commit 基于旧 main，仓库侧需按当前 main 重放（cherry-pick）而非直接快进推送，交接时可注明分支基。
- KA-74 与 开发者工具工程师 协作（交接 KA-74 P1-9 季度人评自动判定脚本入库），评分 4/5：交付物清单明确（src/测试/报告 + commit hash + 目标分支），测试 20/20 前置通过；改进——交付 commit 内嵌 UPLOAD_MANIFEST「待提交」占位行与 main 既有行冲突，仓库侧需在 cherry-pick 时拆分处理。
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
| 2026-08-17 | v0.17 | 追加 KA-103：issue 评论附件拉取入库模式（`attachment download` + 跨迭代版本甄别 + `shasum` 同源校验）、白名单检查后置落盘、新建顶层 `dashboard/` 目录 + 根 README 目录同步；协作评分 5/5 |
| 2026-08-17 | v0.16 | 追加 KA-100：未提交工作区交接的跨 run 嵌套 checkout 定位（find 文件名 → git status/diff 逐项吻合）、交接已由审查员/终审核验时仓库侧按既有流程闭环（白名单 + 交付点复跑 56+165+8 + manifest 登记 + 回传落地 commit）、两 commit 交付模式（内容 commit + manifest/档案登记 commit）；协作评分 5/5 |
| 2026-08-17 | v0.14 | 追加 KA-97：交接后分支继续演进的识别（comment hash f96f15f vs 实际 tip a411267，reflog 时间线判定）、交付点双重核验（工作区未提交改动 vs 提交快照，以提交快照为准）、两 commit 关联交付合并 + manifest 双行回填、分支 ref 与工作区 HEAD 一致性检查；协作评分 4/5 |
| 2026-08-17 | v0.13 | 追加 KA-76：未提交工作区交接的定位与核验（跨 runtime find + git status + diff 逐项吻合）、分支基不一致的合并基判定（crontab/能力档案整文件 cp + README hunk 合并）、交接声明与实测不一致校准（50/139 复跑为准修正 README 与测试报告）；协作评分 4/5 |
| 2026-08-17 | v0.12 | 追加 KA-79：纯文档交付的交接方工作区定位（未附分支/commit）、分支基 + blob 一致性核对、两 commit 落地、并行交付冲突合并（KA-80 并发 main 推进）；协作评分 4/5 |
| 2026-08-17 | v0.11 | 追加 KA-80：纯文档交付的验收基线（分支基判定 + 白名单逐文件 + secret 扫描 + 分支/main 双推送）、报告产物/规范模板归档二分；协作评分 5/5 |
| 2026-08-17 | v0.10 | 追加 KA-96：交接分支本地定位（未推远程）、交付点快照复跑（15/15）、UPLOAD_MANIFEST hash 回填闭环；协作评分 5/5 |
| 2026-08-17 | v0.8 | 追加 KA-92：返工交付的交付点快照复跑基线、权限边界核对、能力档案类文件白名单检查；协作评分 |
| 2026-08-17 | v0.1 | 首次建档：KA-53 任务后的能力评估与学习记录 |
| 2026-08-17 | v0.2 | 追加 KA-56：README 报告归档说明更新 + Release 链接有效性校验 |
| 2026-08-17 | v0.3 | 追加 KA-54：仓库==生产 SHA 复核法、实时远程核对、并发 push 处理；协作评分 |
| 2026-08-17 | v0.4 | 追加 KA-71：并行建档冲突的 cherry-pick 静默覆盖识别与手工合并；协作评分 |
| 2026-08-17 | v0.5 | 追加 KA-74：交付物入库校验流程（测试+secret 扫描）、并发 main 推进的 blob 比对诊断、rebase 后清单 hash amend；协作评分 |
| 2026-08-17 | v0.6 | 追加 KA-84：交接分支落后 main 的 cherry-pick 重放、能力档案白名单检查、三 commit 落地模式；协作评分 |
| 2026-08-17 | v0.7 | 追加 KA-75：代码交付类交接的测试基线复跑、干净快进判定、既有生产文件改动面核对；协作评分 |
