# GitHub 上传清单（UPLOAD_MANIFEST）

> **项目名称**：P0 智能评分系统（方案 C）· 上传目标仓库：`kzh8175-dot/multica-skills`
> **用途**：记录每日上传到 GitHub 的事项、职责归属与待审批上传
> **更新周期**：每日维护（由 GitHub 仓库管理员执行，见文末「维护机制」）
> **最近更新**：2026-08-17

---

## 一、每日上传记录

### 2026-08-16（首个上传日 · 仓库初始化 + P0 交付物入库）

| # | 时间 | 上传事项 | 开发 | 验收 | 审批 | 提交上传需求 | 上传者 | commit |
|---|------|----------|------|------|------|--------------|--------|--------|
| 1 | 14:14 | 仓库初始骨架（agents 目录 + README），解除 B1 阻塞项 | GitHub 仓库管理员 | —（初始化，随 #18 验收） | 资深战略领导者（P0 编排放行） | 资深战略领导者（B1 阻塞项） | GitHub 仓库管理员 | `d8778fa4` |
| 2 | 14:48 | P0 评分系统交付物：聚合器/调度器/配置/测试/报告（来源 KA-16 / KA-43；其中报告已确认无关 → 移入 Release） | 开发者工具工程师、后端架构师 | 代码审查员 + 资深战略领导者（#16 口径终审） | 资深战略领导者 | GitHub 仓库管理员（B1 解除·同步） | GitHub 仓库管理员 | `6ecc691f` |
| 3 | 15:05 | KA-18 生产树最新版：F1/F2 修复版结算器 + 运维层（包装脚本/crontab/runbook/audit-events） | DevOps自动化工程师、开发者工具工程师 | SRE稳定性工程师（#18 验收通过 ✅） | 资深战略领导者 | GitHub 仓库管理员（仓库==生产同步） | GitHub 仓库管理员 | `98f5d841` |
| 4 | 23:51 | KA-19 OSError 加固同步：`src/rating-settler.py` append_to_events 包 try/except OSError→E_WRITE 指数退避，保留 F1/F2 | DevOps自动化工程师、代码审查员 | 代码审查员（终验 19/19 用例 ✅） | 资深战略领导者 | GitHub 仓库管理员（仓库==生产同步） | GitHub 仓库管理员 | `f7c6677` |

> 说明：14:46 有一笔 `probe` 提交（账号 `kzh8175-dot`，连通性测试），非业务上传，不记入。
>
> 说明（2026-08-17 更新）：报告归档 `reports/reports-2026-08-Q3.tar.gz` 经资深战略领导者确认为生成产物（评分报告，非开发必需文件），已移出代码仓库，归档至 GitHub Release：[reports-2026-08-Q3](https://github.com/kzh8175-dot/multica-skills/releases/tag/reports-2026-08-Q3)。仓库内仅保留代码/配置/文档等开发相关文件。
>
> 说明（2026-08-17 · KA-54 复核）：生产树已提交 KA-19 OSError 加固（生产 commit `fe41250` / `f7d8c14`，工作区干净）；仓库 `main` 的 `src/rating-settler.py` 与生产 SHA256 均为 `720d9f97…e91c41`，「仓库 == 生产」复核通过，本行记录 `f7c6677` 同步凭据。

### 2026-08-17

| # | 时间 | 上传事项 | 开发 | 验收 | 审批 | 提交上传需求 | 上传者 | commit |
|---|------|----------|------|------|------|--------------|--------|--------|
| 1 | 00:52 | KA-59 方案 B：结算器归属解析增强 F3（assignee 缺失回退 creator / squad 按名解析）+ 新增 `test-rating-settler.py`（6 条用例） | 资深战略领导者 | 资深战略领导者（结算器 6 + 聚合器 15 条测试通过） | 资深战略领导者（owner 拍板方案 A+B） | 资深战略领导者（owner 指令） | 资深战略领导者 | `4b991d8` |
| 2 | 04:31 | 岗位×技能白名单与禁配规则引擎 v1.0.0：`config/skill-whitelist/`（whitelist.py + README + 规则文档），7 岗位×12 技能类型，已应用到 69 agent 零违规 | 资深战略领导者 | 资深战略领导者（69 agent 校验通过 + 模块自测） | 资深战略领导者（owner 指令） | 资深战略领导者（owner 指令） | 资深战略领导者 | `c9b59e6` |
| 3 | 05:13 | KA-73 P1-8 负责人评审指引 v1.0（`agents/capability-system/reviewer-guide.md`，行为类事件 16 条 + R-21~R-23 自优化事件，权限边界/命令模板/结算归档流程）+ 技术文档撰写者能力档案建档（`agents/profiles/技术文档撰写者/capabilities.md` v0.1）——已通过白名单检查（项目文档，无敏感信息） | 技术文档撰写者 | 资深战略领导者（验收中，in_review） | 资深战略领导者（P1 计划内交付） | 技术文档撰写者（交接） | GitHub 仓库管理员 | `ab40ca7` |
| 4 | 05:15 | KA-71 P1-6 能力档案模板加「评分记录」章节：新增 `agents/capability-system/template.md`（全工作室标准模板，R-41 月度百分制 / R-51 季度综合评分 / 等级 / 防失真 / 异常 + `category={...}` 占位，兼容聚合器/调度器正则）；`agents/profiles/技术文档撰写者/capabilities.md` 按新模板更新至 v0.2（并入已入库的 KA-73 学习记录，保留两条学习记录）——已通过白名单检查（项目文档，无敏感信息） | 技术文档撰写者 | 代码审查员（RACI 验收人，in_review 待验收） | 技术文档撰写者（任务交接指令） | 技术文档撰写者（交接） | GitHub 仓库管理员 | `951a776` |
| 5 | 05:18 | KA-74 P1-9 季度人评表单自动判定：新增 `src/quarterly-review-judge.py`（客观/人评/综合/等级自动判定回填，R-51~R-55 + 防失真 R-71/R-72/E-02，幂等原子写、`--dry-run`/`--status`/`--json`）+ `src/test-quarterly-review-judge.py`（20 条用例全通过）+ `docs/quarterly-review-judge-test-report.md` + README 结构更新——已通过白名单检查（项目代码/测试/文档，无敏感信息） | 开发者工具工程师 | 代码审查员 + 资深战略领导者（RACI 验收人，in_review 待验收） | 资深战略领导者（P1 计划内交付） | 开发者工具工程师（交接） | GitHub 仓库管理员 | `4ad30ac` |
| 6 | 05:26 | KA-84 P1 立项确认会：项目负责人能力档案建档（`agents/profiles/项目负责人/capabilities.md` v0.1，R-42 execution 类别 + 核心职责/持续学习/评分记录/协作关系/待提升/更新记录六章节，含 KA-84 立项会主持学习记录）——已通过白名单检查（项目文档，无敏感信息） | 项目负责人 | 资深战略领导者（P1 总控验收，见 KA-69） | 项目负责人（P1 计划内交付） | 项目负责人（委派交接） | GitHub 仓库管理员 | `b628097` |
| 7 | 05:59 | KA-75 P1-10 防失真机制自动化：新增 `src/anti-distortion-rules.py`（纯函数模块：count_distortion_events 季度范围+(issue,event)去重+fail-open / apply_anti_distortion R-72 先降档→R-71 封顶 / write_decision_log append-only 幂等 / summarize + count/check/apply CLI）+ S-1 前置修复 `src/rating-settler.py` 去重键 issue_id→(issue_id, rating.event) + `src/review-scheduler.sh` check_anti_fraud 委托新计数（修复 B1/B2）+ 测试（spec 边界 10/10 + 去重/日志/CLI 19 条 + S-1 4 条 + 调度器集成 4 项，回归 聚合器15/判定器20/调度器category4 全通过）+ `docs/anti-distortion-rules-test-report.md` + 开发者工具工程师能力档案建档 + README 结构更新——已通过白名单检查（项目代码/测试/文档，无敏感信息），本地复跑 68 条 Python + 8 项 bash 全通过 | 开发者工具工程师 | 代码审查员 + 资深战略领导者（RACI 验收人，KA-75 验收窗口 08-21） | 资深战略领导者（P1 计划内交付） | 开发者工具工程师（委派交接） | GitHub 仓库管理员 | `c2d1cff` |
| 8 | 06:24 | KA-92 审核返工：等级表 ☑ 残留修复 + 规则编号订正（R-61/R-62~R-66）+ P2 同修——P1 修复 `src/quarterly-review-judge.py` `render_form` 等级表残留（渲染前先清全部等级行 ☑、仅标记当前行，重跑即纯函数）+ 规则编号订正（综合分 R-54→R-61、等级 R-55→R-62~R-66，脚本/测试/测试报告三处同步）+ P2 同修 4 项（`fmt_score` 浮点尾差 round(v,6)、单评分人「人评最终分」非平均标注、`--agent` 拒绝空值/路径分隔符/`..`、`apply_caps` docstring 顺序一致化）+ `src/test-quarterly-review-judge.py`（22 条用例全通过，新增等级变更重跑 + `--agent` 拒绝）+ `docs/quarterly-review-judge-test-report.md` + `src/review-scheduler.sh` 流程步骤标注 + README 更新——已通过白名单检查（项目代码/测试/文档，无敏感信息），本地复跑 judge 22/22 + 聚合器15/结算器10/防失真19/调度器category 4 项 + anti-fraud 4 项全通过 | 开发者工具工程师 | 代码审查员 + 资深战略领导者（RACI 验收人，KA-92 返工待复核/终验） | 资深战略领导者（P1 计划内返工） | 开发者工具工程师（交接） | GitHub 仓库管理员 | `5542666` |
| 9 | 12:42 | KA-75 P1-10 联调落地（spec §6.2 四项待办，对应终审裁定 B-1/B-3/N-4/N-6）：`src/anti-distortion-rules.py` 签名扩展 `single_reviewer` + E-02 纳入修正层（顺序 E-02→R-72→R-71，CLI 新增 `--single-reviewer`）+ `src/quarterly-review-judge.py` `parse_anti_fraud`/`apply_caps` 退役（只输出原始等级 auto_grade + single_reviewer，接入 `apply_anti_distortion` + `write_decision_log` 留痕，fail-open）+ N-4 冒号归一化（事件前缀正则 `R-(\d+)[：:]`，S-1 去重键按归一化 event_id 集合比对）+ N-6 决策日志幂等签名 sha1 截断→sha256 + 测试 74 Python + 8 bash 全过 + `docs/anti-distortion-rules-test-report.md` / `docs/quarterly-review-judge-test-report.md` 同步 + 开发者工具工程师能力档案 v0.3；另随本次交付登记 spec/ADR 终审修订版（`docs/adr/0001-anti-distortion-rules.md` + `docs/p1-10-anti-distortion-spec.md`，原 commit `bc7d1d6`，cherry-pick 为 `7e5eba7`）——已通过白名单检查（项目代码/测试/文档，无敏感信息），本地复跑 74 Python + 8 bash 全过 | 开发者工具工程师（代码）、软件架构师（文档） | 代码审查员 + 资深战略领导者（RACI 验收人，in_review 待终验） | 资深战略领导者（P1 计划内交付） | 开发者工具工程师（交接） | GitHub 仓库管理员 | `98b4aa1` + `7e5eba7` |
| 10 | 12:50 | KA-96 里程碑 1 · 看板只读数据接口：新增 `src/dashboard-data-feed.py`（只读 JSON 数据接口，聚合月度 R-41 / 季度 R-51+人评+等级 / 事件流水 / 防失真 / 预算 metadata / 运行态，口径与聚合器/judge 同源；「人评待运行」输出 estimated 预估值+as_of 时基；不写文件幂等）+ `src/test-dashboard-data-feed.py`（15 条用例全通过，含只读性校验）+ `docs/dashboard-data-interface.md`（Schema v1.0 + 8 页字段映射 + 接口约定）+ README 结构更新——已通过白名单检查（项目代码/测试/文档，无敏感信息），本地复跑 dashboard-feed 15 + 聚合器15/防失真24/judge24/结算器11 全通过，生产数据实跑验证（59 agents / 34 事件行 / 7 预算项 / pending22） | 开发者工具工程师 | 前端工程师 + 数据可视化工程师（对接验收，见 KA-96 里程碑 1） | 资深战略领导者（KA-96 研发启动） | 开发者工具工程师（交接） | GitHub 仓库管理员 | `0093c62` |
| 11 | 12:57 | KA-79 P2-14 异常处理 SLA 合并定稿 v1.0（含事故响应指挥官响应侧设计）：新增 `docs/exception-handling-sla.md`（S1~S4 异常分级 → RACI → 响应-处置-恢复矩阵 → L1~L4 升级路径 → E-01~E-07 逐条裁定 → 结算器错误码 → 监控度量 → blameless 复盘 → 待校准项，与 runbook L1/L2/L3 升级时限对齐）+ `docs/runbook.md` §3 增加指向 SLA 文档的交叉引用（运行态告警速查，避免双口径）+ 技术文档撰写者能力档案更新至 v0.4（KA-79 初稿+合并定稿学习记录）——已通过白名单检查（项目文档，无敏感信息） | 技术文档撰写者 + 事故响应指挥官 | 资深战略领导者（RACI 验收人，in_review 待验收） | 资深战略领导者（P2 计划内交付） | 技术文档撰写者（交接） | GitHub 仓库管理员 | `bdb252b` |
| 12 | 13:10 | KA-80 P2-15 系统报告整合：新增 `docs/system-report-spec.md`（周报/月报/季度报告**六段统一输出骨架** + 命名规范 + 归档口径，评分口径引用 `docs/dashboard-data-interface.md` §3、周报指标引用 `docs/runbook.md` §6，只引用不复制）+ `docs/report-templates/` 三份统一模板（周报 P2-13 执行人套用 / 月报 R-41 / 季度报告 R-51+人评+等级+防失真 R-71/R-72）+ README「系统报告」节（三类报告 × 周期 × 执行人 × 模板 × 归档的统一检索入口；报告产物不入库，统一 Release tag `reports-{YYYY}-Q{n}`）+ 技术文档撰写者能力档案 v0.3——已通过白名单检查（项目文档/模板，无敏感信息），全 diff secret 扫描干净 | 技术文档撰写者 | 项目负责人（RACI 验收人，KA-80 待验收） | 资深战略领导者（P2 计划内交付） | 技术文档撰写者（交接） | GitHub 仓库管理员 | `edb8d27` |
| 13 | 13:30 | KA-96 代码审查阻塞项修复（E-02 防失真误判）：`src/dashboard-data-feed.py` `_anti_fraud_flags` 修复——e02 仅从 judge 已回填标记判定（`review_state==judged` 且含「（E-02 单评分人」，锚定 `**人评最终分**…（E-02 单评分人，非平均）` 与「人评评分人 ≥ 2」两种回填形式），删除「等级上限A」子串匹配，杜绝模板静态文案「E-02: 单评分人可用，等级上限A」误标 pending 表单；补 3 条用例（pending 模板不触发 / judged 单评分人触发 / 标记语义单元）+ `docs/dashboard-data-interface.md` Schema 注释同步 + 能力档案 v0.6——已通过白名单检查（项目代码/测试/文档，无敏感信息），本地复跑 feed 18 + 聚合器15/防失真24/judge24/结算器11/状态钩子50 全通过，生产实跑 63 agent 0 误标 | 开发者工具工程师 | 代码审查员（复检，见 KA-96） | 资深战略领导者（KA-96 修复安排） | 开发者工具工程师（交接） | GitHub 仓库管理员 | 待推送回填 |
| 13 | 13:20 | KA-76 P2-11 状态变更钩子：新增 `src/state-change-hook.py`（检测任务 完成/失败/返工 状态变更 → 自动写 R-01~R-04 事件，5 键 metadata、`rating.status=pending`，与结算器/事件流水打通；幂等：`rating.last_status` 状态跟踪 + 首次自动建 baseline + 已有 pending 延后 + 同事件已入账跳过 + `rating.test=true` 隔离）+ `src/test-state-change-hook.py`（50 条用例全通过，含 main() 集成 6 条）+ `scripts/run-state-change-hook.sh` + `config/crontab-rating.conf`（新增第 0 项，每日 00:20 先于 00:30 结算）+ `docs/state-change-hook-test-report.md` + 开发者工具工程师能力档案 v0.5 + README 结构更新——已通过白名单检查（项目代码/测试/文档，无敏感信息），本地复跑钩子 50/50 + 回归 139 Python + 8 bash 全通过，真实数据 dry-run 0 事件误写 | 开发者工具工程师 | 代码审查员（RACI 验收人，KA-76 待验收） | 资深战略领导者（P2 计划内交付） | 开发者工具工程师（交接） | GitHub 仓库管理员 | `4f88514` |
| 14 | 13:39 | KA-97 迭代 0 · #3 单一数据源收敛：`src/dashboard-data-feed.py` 确立为智能看板唯一数据源（Schema v1.0），并行管线 `dashboard-data-loader.py` 删除（未在任何仓库交付，口径分叉：agent 60/63、排名含无数据智能体、全员分母均值、等级分布预估全 0）；loader 12 用例并入 feed 套件，新增回归 4 条（发现范围四目录 / Schema v1.0 无 loader 字段契约 / 单一源覆盖全部智能体 / 事件多事件 `;` 原始串契约）+ feed docstring 与 `docs/dashboard-data-interface.md`「单一数据源收敛」章节 + README 测试计数同步 15→22 + 能力档案 v0.7——已通过白名单检查（项目代码/测试/文档，无敏感信息），本地复跑 feed 22 + 聚合器15/防失真24/judge24/结算器11/状态钩子50 + 调度器 bash 4+4 全通过，生产实跑 63 agents（有数据 24），dashboard↔feed 24/24 一致 | 开发者工具工程师 | 代码审查员（复检，见 KA-97） | 资深战略领导者（KA-97 迭代 0） | 开发者工具工程师（交接） | GitHub 仓库管理员 | 待推送回填 |

> 说明：本笔提交按 owner 指令由资深战略领导者直接推送 main（非 GitHub 仓库管理员通道），已在 KA-59 完结时记录；仓库 `main` 的 `src/rating-settler.py` 与生产逐字节一致（SHA256 `ae46b041…` 核验）。

---

## 二、待审批上传清单（截至 2026-08-16 收工）

| 事项 | 当前状态 | 阻塞/待办 | 上传者 |
|------|----------|-----------|--------|
| P0-4 重试注入测试整改（KA-51） | 整改中（in_progress） | 开发整改 → 代码审查员复验 → 通过后上传 | GitHub 仓库管理员 |
| P0-4 重试注入测试（#19） | 待重新验收（in_review） | 依赖 KA-51 整改结果 | GitHub 仓库管理员 |
| 每日结算 / 月末聚合 / 季度人评 报告（#46/47/48） | in_review | 数据核对通过后按需上传 | GitHub 仓库管理员 |
| 其余 in_review 文档（#37/#36/#41/#15 等） | in_review | 终审通过后按需上传 | GitHub 仓库管理员 |

---

## 三、字段说明（职责归属口径）

| 字段 | 含义 | 归属口径 |
|------|------|----------|
| 开发 | 编写代码/文档/配置的智能体 | issue「执行人」中的开发角色 |
| 验收 | 按验收标准复核并回填结论者 | issue「验收」角色（如 SRE稳定性工程师 / 代码审查员） |
| 审批 | 放行/终审的决策者 | 资深战略领导者（P0 放行、终审口径） |
| 提交上传需求 | 提出"需要上传到 GitHub"的一方 | 开发完成后的交接方或编排方（通常资深战略领导者 / GitHub 仓库管理员） |
| 上传者 | 实际执行 GitHub 提交/推送者 | **GitHub 仓库管理员**（统一提交通道） |
| commit | GitHub 提交号（前 8 位） | 从 `gh api repos/kzh8175-dot/multica-skills/commits` 核对 |

---

## 四、维护机制

- **执行者**：GitHub 仓库管理员（唯一 GitHub 提交通道，本清单的提交也由此智能体执行）
- **频率**：每日一次，更新当日上传记录 + 待审批上传清单，不删除历史记录
- **数据来源**：① 当日仓库提交（gh API）；② 当日 done / in_review 的 issue；③ GitHub 仓库管理员本人处理的上传任务
- **输出**：更新仓库内 `UPLOAD_MANIFEST.md`，并在当日维护 issue 评论中贴出清单摘要与待审批列表
