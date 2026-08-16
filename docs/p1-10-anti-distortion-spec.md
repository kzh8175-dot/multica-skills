# P1-10 防失真机制自动化 · 规则设计与状态机规格（终审修订版）

**作者**: 软件架构师 ｜ **首版**: 2026-08-17 ｜ **终审修订**: 2026-08-17（资深战略领导者规则口径终审）

对应需求：P1-10「防失真机制自动化（红线上限 C / 缺自评降档）」。
本文件是规则设计交付物：供 开发者工具工程师 实现/联调 `anti-distortion-rules.py`，
供 代码审查员 + 资深战略领导者 验收。

> **状态**：模块主体已落地（`src/anti-distortion-rules.py`，19+10+4 测试全过，
> 见 `docs/anti-distortion-rules-test-report.md`）。本修订版固化终审裁定，标注
> 「已落地」与「联调待办」；联调待办在 KA-74（P1-9）验收后进行，本阶段不提前改动
> 验收中的 P1-9 交付物。

---

## 1. 现状评审

### 1.1 当前实现

`review-scheduler.sh` 原 `check_anti_fraud()` 存在缺陷（已修复）：

| 问题 | 说明 | 状态 |
|---|---|---|
| **B1 统计范围错误** | `$(date +"%Y")-??.md` 匹配**全年**，而规则口径是**季度内** | ✅ 已修复（调度器委托新计数） |
| **B2 文本 grep 计数** | 依赖 `红线\|违规\|-20` 字面词，任何 -20 事件都会误算 | ✅ 已修复（结构化事件 ID） |
| **B3 仅标注不阻断** | `cap_note` 只写表单提示，最终等级仍由人手工判定 | ✅ 已修复（修正层强制输出 final_grade） |
| **B4 无决策留痕** | 无结构化修正记录 | ✅ 已修复（`write_decision_log`） |

### 1.2 结算状态机评审（pending→credited/escalated）

`rating-settler.py` 状态机：`pending → 结算中 → credited（成功）`、
`pending → pending（指数退避重试 ≤3 次）`、`pending → escalated（重试耗尽/不可重试）`。
R-31（-20）/R-32（-5）为 reviewer 行为事件，经同一状态机入流水，结算路径本身无阻断 ✅。

**S-1（前置修复，已合入）**：原全局去重键 `issue_id` 会拦截同一 issue 的第二个事件
（如 R-21 自评 + R-31 违规）。已改为 **`(issue_id, rating.event)`**：同一 issue 可承载
多个不同事件，同一 (issue, 事件) 只写一次，保持「跨文件不双计」的防聚合双计属性。

> **N-5 归属前提（终审确认）**：R-31/R-32 归属以**结算时 issue 归属**为准
> （`rating-settler.py resolve_agent_name`：assignee → squad → creator 兜底），
> 计数按 `events/{agent}/` 读。若 assignee 在两次结算间变更导致归属漂移成实际困扰，
> 再引入「写入时显式指定被罚 agent」增强（本阶段不实施）。

---

## 2. 目标架构（终审后）

### 2.1 流水线位置

```
[每日结算] rating-settler.py          → 事件流水 events/{agent}/YYYY-MM.md（含 R-31/R-32 负分）
[月末聚合] rating-aggregator.py       → 月度百分制 + 季度客观分
[季度人评] quarterly-review-judge.py  → auto_grade + single_reviewer（表单事实） ← P1-9 前置
[防失真修正] anti-distortion-rules.py → final_grade + corrections             ← 本任务（P1-10）
[裁定]     资深战略领导者             → 终审（override 能力）
```

> **B-1 auto_grade 语义（终审裁定）**：`auto_grade` = **未经任何防失真修正的原始等级**
> （P1-9 按 R-55 查表输出）。R-71/R-72（及 E-02）的权威归属为 **P1-10 防失真模块，唯一权威**。
> 接入契约：`final_grade = apply_anti_distortion(auto_grade, counts, single_reviewer)`，
> 由调用方（judge）写 `write_decision_log` 留痕。
> **退役**：KA-74 验收后联调时，`quarterly-review-judge.py` 的 `parse_anti_fraud()` 与
> `apply_caps()` 中 R-71/R-72 分支退役——judge 只输出原始等级 + `single_reviewer` 表单事实，
> 不再读表单文本触发标记（旧标记来自文本 grep，与事件流水计数不同源，`summarize()` 文案
> 变更会使其静默失效）。

### 2.2 模块契约 `src/anti-distortion-rules.py`（生产镜像 `agents/capability-system/`）

```python
GRADES = ("S", "A", "B", "C", "D")           # 从优到劣

DEFAULT_CONFIG = {
    "r71_threshold": 2,   # 季度内 R-31 次数阈值
    "r72_threshold": 2,   # 季度内 R-32 次数阈值
    "r71_cap": "C",       # R-71 等级上限
}

def count_distortion_events(events_dir: str, agent: str,
                            quarter_months: list[str]) -> dict:
    """统计季度内 R-31/R-32 次数（只读辅助，调用方侧）。
    事件列前缀解析（正则 R-(\\d+)[：:] ，半角/全角冒号归一化，N-4）；
    多事件以 ';' 分隔；按 (issue, event_id) 去重；仅统计 quarter_months。
    文件缺失：该月计 0（fail-open）。返回 {"r31": int, "r32": int}。
    """

def apply_anti_distortion(auto_grade: str, counts: dict,
                          single_reviewer: bool = False,
                          config: dict | None = None) -> AntiDistortionResult:
    """纯函数（唯一纯核心，N-7）：E-02 → R-72 → R-71（顺序终审裁定，B-3）。
    E-02: single_reviewer=True 时封顶 A；R-72: 降一档（D 为地板）；
    R-71: 封顶 r71_cap（取更差者，不抬升）。返回 dataclass：
    auto_grade / final_grade / counts / corrections[] / config。
    无副作用；非法入参抛 ValueError。
    """

def write_decision_log(agents_root: str, agent: str, quarter: str,
                       result: AntiDistortionResult) -> str:
    """追加写 reviews/scoring/anti-distortion/{agent}/{quarter}.md（append-only）。
    幂等：同一判定（quarter + 判定签名）不重复追加；判定签名 = 判定输入的
    规范化 JSON（auto_grade+final_grade+counts+corrections）的 sha256（N-6）。
    {agent} 进入路径前需校验不含路径注入字符（N-6）。

def summarize(result: AntiDistortionResult) -> str:
    """生成人评表单「四、防失真校验」段摘要（触发/未触发 + 修正链 + 最终等级）。"""
```

**纯函数边界（N-7，终审确认）**：纯核心**仅** `apply_anti_distortion`；
`count_distortion_events` 是调用方侧的只读辅助；`write_decision_log` 是唯一写入口。

### 2.3 判定算法（终审版，顺序固定）

```
输入: auto_grade ∈ {S,A,B,C,D}；counts = {r31, r32}；single_reviewer ∈ {false,true}
1. grade ← auto_grade
2. E-02：若 single_reviewer 且 grade 优于 A → grade ← A（封顶 A，记录 E-02 修正）
3. R-72：若 r32 ≥ r72_threshold → grade ← demote(grade, 1)（D 为地板；记录 R-72）
4. R-71：若 r31 ≥ r71_threshold → grade ← cap(grade, r71_cap)（取更差者；
   S/A/B→C，C→C，D→D 不抬升；记录 R-71，作为最终硬性天花板）
5. 返回 final_grade = grade
```

### 2.4 计数口径（N-2 收紧，终审确认）

「季度内 ≥2 次」= **≥2 个不同 issue 各至少 1 次**。同一 issue 同事件在结算层
（S-1 `(issue_id, rating.event)` 去重键）已幂等去重，计数层再计重复值无意义。
`count_distortion_events` 按 `(issue, event_id)` 去重即实现该口径。

---

## 3. 边界用例（终审版 · 18 条全部通过）

> 前 10 条为原验收用例（已落地测试复现）；11–14 为代码审查 N-3 补充
> （auto=C 三场景 + 阈值=1 变体）；15–18 为 E-02 场景（终审 B-3 纳入）。

| # | 场景 | auto | sr | r31/r32 | final | 触发规则 |
|---|---|---|---|---|---|---|
| 1 | R-31×2 强制 C | S | — | 2/0 | **C** | R-71 |
| 2 | R-32×2 降一档 | S | — | 0/2 | **A** | R-72 |
| 3 | R-31×1 不触发 | S | — | 1/0 | S | — |
| 4 | R-32×1 不触发 | S | — | 0/1 | S | — |
| 5 | 混合各 1 不触发 | A | — | 1/1 | A | — |
| 6 | 正常数据（回归） | B | — | 0/0 | B | — |
| 7 | 双触发：先降后封顶 | S | — | 2/2 | **C** | R-72, R-71 |
| 8 | R-31×2 且 auto=D 不抬升 | D | — | 2/0 | D | R-71 |
| 9 | R-32×2 且 auto=D 撞地板 | D | — | 0/2 | D | R-72（触发 E-04） |
| 10 | R-31×1+R-32×2 仅降档 | A | — | 1/2 | **B** | R-72 |
| 11 | auto=C 双触发 | C | — | 2/2 | **D** | R-72, R-71 |
| 12 | auto=C 仅 R-31（封顶 no-op） | C | — | 2/0 | C | R-71 |
| 13 | auto=C 仅 R-32 | C | — | 0/2 | **D** | R-72 |
| 14 | 阈值=1 变体（config） | S | — | 1/0 | **C** | R-71（`r71_threshold=1`） |
| 15 | 单评分人 封顶 A | S | ✓ | 0/0 | **A** | E-02 |
| 16 | 单评分人 + R-32×2 | S | ✓ | 0/2 | **B** | E-02, R-72 |
| 17 | 单评分人 + R-31×2 | S | ✓ | 2/0 | **C** | E-02, R-71 |
| 18 | 单评分人 + 双触发 | S | ✓ | 2/2 | **C** | E-02, R-72, R-71 |

关键语义确认：封顶不抬升 D（#8/#11）；降档撞 D 地板（#9/#11/#13）；
双触发最终 C（#7/#18，R-71 为最终天花板）；E-02 与 R-72 独立叠加（#16 得 B，
区别于仅单评分人的 #15 得 A —— 终审 B-3 的行为变更，联调时同步更新
`test_apply_caps` 预期）。

---

## 4. 失败模式与恢复

| 失败模式 | 检测 | 恢复 |
|---|---|---|
| 季度流水文件缺失 | `count_distortion_events` 该月计 0，调用方带 `E_MISS` 标记 | 补记后重算（纯函数幂等） |
| 同 R-31/R-32 跨月重复 | `(issue, event_id)` 去重 | `audit-events.py --reconcile` 后重算 |
| 同一 issue 多事件被旧 `E_DUP` 拦截 | 结算日志 E_DUP 计数异常 | **S-1 已修复**：去重键 `(issue_id, rating.event)` |
| R-72 撞 D 地板 | `final=D` + 修正记录 | 按 E-04 升级资深战略领导者专项复盘 |
| 误记 R-31/R-32 | 裁定复核 | 负责人 override：决策日志留 override 记录，重算终审等级 |
| 归属漂移（assignee 变更） | 裁定复核 | N-5 前提成立；如成实际困扰再引入显式指定被罚 agent |
| 重复运行/手动重跑 | 纯函数 + 原子写 + 日志签名去重 | 幂等，输出一致 |

**fail-open 原则**：事件数据缺失/异常时防失真**不惩罚**（按 0 计），仅在报告中标记；
惩罚必须建立在可信计数之上。反向风险（应罚未罚）由负责人裁定兜底。

---

## 5. 可扩展性

- 阈值/上限全部走 `config`（`r71_threshold` / `r72_threshold` / `r71_cap`），
  未来 R-71 收紧（如 ≥1 触发，用例 #14）或封顶调整为 B 均无需改代码。
- 新增规则在 `apply_anti_distortion` 追加一个分支 + 一条 correction，`corrections`
  结构与决策日志格式不变（E-02 已示范：作为修正层内规则与 R-71/R-72 并列）。
- 决策日志与季度表单解耦，表单演进不影响审计链。

---

## 6. 实施状态与联调待办

### 6.1 已落地（HEAD `c2d1cff`，测试全过）

- `src/anti-distortion-rules.py`：`count` / `apply` / `summarize` / `write_decision_log` + CLI
- `src/rating-settler.py`：S-1 去重键 `(issue_id, rating.event)`（含 4 条新测试）
- `src/review-scheduler.sh`：`check_anti_fraud()` 委托新计数（季度范围 + 结构化事件 ID）
- 测试：`src/test-anti-distortion-rules.py`（19）/ `src/test-rating-settler.py`（10）/
  `src/test-anti-fraud-scheduler.sh`（4 项），全过；报告 `docs/anti-distortion-rules-test-report.md`

### 6.2 联调待办（KA-74 验收后，由开发者工具工程师执行）

1. **B-3 签名扩展**：`apply_anti_distortion(auto_grade, counts, single_reviewer, config)`
   纳入 E-02；顺序 E-02 → R-72 → R-71（本 spec 2.3/3）。
2. **judge 退役**：`quarterly-review-judge.py` 的 `parse_anti_fraud()` 与 `apply_caps()`
   中 R-71/R-72 分支移除；judge 只输出原始等级 + `single_reviewer`；接入
   `final_grade = apply_anti_distortion(auto_grade, counts, single_reviewer)`，
   由 judge 调用 `write_decision_log`。同步更新 `test_apply_caps` 预期
   （S+单评分人+R-32：A → B）。
3. **N-4 冒号归一化**：事件前缀解析正则改为 `R-(\d+)[：:]`，S-1 去重键用归一化 event_id。
4. **N-6 日志签名**：决策日志幂等签名对齐 sha256（当前实现 sha1 截断；不阻塞，随联调统一）。

### 6.3 依赖

P1-7（自评块字段，R-32 检测数据基础）与 P1-9（自动判定）均未上线时，模块已独立
开发测试（纯函数）；**接入季度链路需等 P1-9 验收后联调**（关键路径 P1-6→P1-9→P1-10）。
