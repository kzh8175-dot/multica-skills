# 负责人评审指引（reviewer-guide）

> **所属**：智能评分系统（评分方案 C）
> **需求来源**：《开发需求清单 v1.0》P1-8（KA-73）
> **规则基准**：`rating-workflow-rulebook.md` v1.0（28 条规则）
> **文档版本**：v1.0
> **维护**：技术文档撰写者（随规则书变更同步更新）

---

## 一、文档目的与读者

本指引说明 **评审人（reviewer / 负责人）在评审时如何把行为类积分事件写入评分系统**。

评分系统（方案 C）的积分事件分两类：

| 事件类型 | 规则编号 | 写入方 | `rating.trigger` |
|----------|----------|--------|:---:|
| **行为类事件** | R-01~R-04、R-11~R-13、R-31~R-33 | 评审人（负责人）在 review 时写入 | `reviewer` |
| **自优化事件** | R-21、R-22、R-23 | 智能体任务完成后自行登记 | `agent` |

行为类事件写入后，由结算器 `rating-settler.py` 按 `pending → credited` 状态机自动入账，进入事件流水
`agents/reviews/scoring/events/{agent}/YYYY-MM.md`，最终参与月度百分制（R-41）与季度人评
（R-51~R-66）。

**读者**：资深战略领导者（最高决策者 / 规则 owner）、项目负责人、任务发起人、协作方，以及被评审的智能体
（用于明确自身权限边界）。

---

## 二、角色与权限边界

### 2.1 角色分工

| 角色 | 可写事件 | trigger | 核心职责 |
|------|----------|:---:|----------|
| **评审人**（负责人 / 任务发起人） | R-01~R-04、R-11~R-13、R-31~R-33 | `reviewer` | 按判定依据写入行为事件；季度人评（R-52/R-61~R-66）；防失真裁定（R-71/R-72） |
| **智能体**（被评审方） | 仅 R-21/R-22/R-23 | `agent` | 任务完成后提交【自评】、更新能力档案、协作好评自报 |
| **系统 / 自动化** | — | — | 事件结算（settler）、月度/季度聚合（aggregator）、季度人评触发（scheduler） |
| **最高决策者**（资深战略领导者） | 终裁权限 | — | E-01~E-07 异常终裁、`escalated` 事件处置、等级 S/D 复核、R-71/R-72 最终裁定 |

### 2.2 权限红线（必须遵守，与规则书 §6.1 及运行时边界一致）

1. **智能体严禁写入行为类事件**（R-01~R-04、R-11~R-13、R-31~R-33）；只能写入 R-21/22/23 自优化事件。
2. **任何智能体严禁设置 `rating.trigger=reviewer`**。
3. **严禁修改已 `credited` / `escalated` 状态的 metadata**。结算完成即只读；如需修正，走
   E-01~E-07 升级路径由最高决策者裁定，不得直接改写。
4. **评审人不应代写 R-21/22/23**（由智能体自行登记）；评审人负责在 review 时核验其真实性，发现虚报
   时升级裁定。

---

## 三、写入总流程（review 时写一条行为事件）

1. **判定**：对照第 4 节规则表，确定命中哪条事件（R-01~R-04 / R-11~R-13 / R-31~R-33）。
2. **准备**：确认被评审 issue 的 id；取事件发生时间（ISO8601，UTC），通常为当前评审时间。
3. **写入**：对被评审 issue 执行 5 条 `multica issue metadata set` 命令（见 3.1）。
4. **核对**：`multica issue metadata list <issue-id> --output json` 复查 5 键齐备、值正确。
5. **结算**：每日 00:30 cron 自动结算；紧急场景可手动单条结算（幂等，安全）：
   `python3 rating-settler.py --issue <issue-id>`
6. **归档**：事件进入 `agents/reviews/scoring/events/{agent}/YYYY-MM.md` 流水，供月末/季末聚合。

### 3.1 通用 metadata 命令模板（5 键）

```bash
multica issue metadata set <issue-id> --key rating.trigger --value "reviewer" --type string
multica issue metadata set <issue-id> --key rating.event --value "R-XX:事件名" --type string
multica issue metadata set <issue-id> --key rating.points --value <N> --type number
multica issue metadata set <issue-id> --key rating.status --value "pending" --type string
multica issue metadata set <issue-id> --key rating.occurred_at --value "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --type string
```

**字段约束**（结算器 `validate_event` 校验，不符合会 `escalated`）：

| 键 | 类型 | 约束 |
|----|------|------|
| `rating.trigger` | string | 仅允许 `agent` / `reviewer` |
| `rating.event` | string | 必须以 `R-` 开头（推荐 `R-XX:事件名` 风格） |
| `rating.points` | number | 必须为整数（可为负） |
| `rating.status` | string | 写 `pending`，结算器据此扫描入账 |
| `rating.occurred_at` | string | ISO8601；缺失时结算器回退当前时间 |

> **幂等**：同一 issue 的同一事件重复写入会被结算器全局去重（E_DUP）跳过，不会双计；可安全重跑。

---

## 四、行为类事件明细（评审人写入 · `trigger=reviewer`）

> 每个事件的**可复制命令**均只列出与 3.1 模板不同的两行；完整命令 = 3.1 通用模板 + 本节两行。
> `rating.points` 为负表示扣分（注意 `--type number` 与负号）。

### 4.1 任务类（R-01~R-04）

| 规则 | 事件 | 积分 | 触发判定依据 | 写入时机 |
|------|------|:---:|--------------|----------|
| R-01 | 任务按时完成 | **+20** | 任务状态=完成 且 未超截止日期（`due_date`） | 验收/关闭任务时 |
| R-02 | 任务超时完成 | **+10** | 任务状态=完成 但 超过截止日期（超时容忍=0） | 验收/关闭任务时 |
| R-03 | 任务未完成/失败 | **-15** | 任务状态=失败/取消/未完成 | 关闭任务时 |
| R-04 | 任务被退回返工 | **-10** | 状态流转 完成→in_review→退回 | 退回发生时 |

**R-01 · 任务按时完成 +20**

```bash
multica issue metadata set <issue-id> --key rating.event --value "R-01:任务按时完成" --type string
multica issue metadata set <issue-id> --key rating.points --value 20 --type number
```

**R-02 · 任务超时完成 +10**（与 R-01 互斥：按时 / 超时二选一）

```bash
multica issue metadata set <issue-id> --key rating.event --value "R-02:任务超时完成" --type string
multica issue metadata set <issue-id> --key rating.points --value 10 --type number
```

**R-03 · 任务未完成/失败 -15**

```bash
multica issue metadata set <issue-id> --key rating.event --value "R-03:任务未完成/失败" --type string
multica issue metadata set <issue-id> --key rating.points --value -15 --type number
```

**R-04 · 任务被退回返工 -10**

```bash
multica issue metadata set <issue-id> --key rating.event --value "R-04:任务被退回返工" --type string
multica issue metadata set <issue-id> --key rating.points --value -10 --type number
```

### 4.2 质量加分（R-11~R-13）

| 规则 | 事件 | 积分 | 触发判定依据 | 写入时机 |
|------|------|:---:|--------------|----------|
| R-11 | 交付物优秀/标杆 | **+15** | 评审人在评论中标记"优秀/标杆" | 评审结论为标杆时 |
| R-12 | 一次通过验收（无返工） | **+10** | 完成→in_review→直接 done，无退回 | 验收通过时 |
| R-13 | 主动发现并报告风险 | **+8** | 提前报告风险/阻塞；需人工确认 | 风险报告确认时 |

**R-11 · 交付物优秀/标杆 +15**

```bash
multica issue metadata set <issue-id> --key rating.event --value "R-11:交付物优秀/标杆" --type string
multica issue metadata set <issue-id> --key rating.points --value 15 --type number
```

**R-12 · 一次通过验收 +10**

```bash
multica issue metadata set <issue-id> --key rating.event --value "R-12:一次通过验收" --type string
multica issue metadata set <issue-id> --key rating.points --value 10 --type number
```

**R-13 · 主动发现并报告风险 +8**

```bash
multica issue metadata set <issue-id> --key rating.event --value "R-13:主动发现并报告风险" --type string
multica issue metadata set <issue-id> --key rating.points --value 8 --type number
```

### 4.3 纪律与风控扣分（R-31~R-33）

| 规则 | 事件 | 积分 | 触发判定依据 | 写入时机 |
|------|------|:---:|--------------|----------|
| R-31 | 违反约束（超范围/后台进程） | **-20** | 交付物检查发现纪律红线（超范围执行、后台进程等） | 违规确认时 |
| R-32 | 未提交自评 | **-5** | 任务完成但无【自评】块 | 任务关闭时核验 |
| R-33 | 重大问题未升级 | **-15** | 问题发生后倒查，重大风险/异常未及时升级 | 倒查确认时 |

**R-31 · 违反约束 -20**（⚠️ 季度内 ≥2 次触发 R-71：等级上限 C）

```bash
multica issue metadata set <issue-id> --key rating.event --value "R-31:违反约束" --type string
multica issue metadata set <issue-id> --key rating.points --value -20 --type number
```

**R-32 · 未提交自评 -5**（⚠️ 季度内 ≥2 次触发 R-72：等级降一档）

```bash
multica issue metadata set <issue-id> --key rating.event --value "R-32:未提交自评" --type string
multica issue metadata set <issue-id> --key rating.points --value -5 --type number
```

**R-33 · 重大问题未升级 -15**

```bash
multica issue metadata set <issue-id> --key rating.event --value "R-33:重大问题未升级" --type string
multica issue metadata set <issue-id> --key rating.points --value -15 --type number
```

---

## 五、自优化事件（智能体写入 · `trigger=agent`）

| 规则 | 事件 | 积分 | 判定依据 | 写入方 |
|------|------|:---:|----------|--------|
| R-21 | 高质量【自评】 | **+5** | 回复含【自评】且含 ≥2 项内容（新技能/挑战/改进） | 智能体 |
| R-22 | 更新能力档案 | **+5** | `capabilities.md` 有更新记录 | 智能体 |
| R-23 | 协作好评 | **+5** | 协作评分 ≥ 4/5 | 智能体 |

**评审人的角色**：核验这些事件是否属实——季度人评时复核自评质量、能力档案更新记录、协作评分来源。
发现虚报或不符合判定依据 → 走 E-01~E-07 升级路径，由最高决策者裁定撤销或更正事件。

> 自优化事件由智能体按自身运行时边界写入（`trigger=agent`），评审人**不得**代写，也不得要求智能体
> 以 `trigger=reviewer` 写入。

---

## 六、操作示例

### 6.1 示例：验收按时完成任务（R-01）

任务 KA-100 完成并通过验收、无退回、未超期。**主事件写 R-01**：

```bash
# 1) 写 R-01 任务按时完成（trigger=reviewer，一个 issue 一条事件）
multica issue metadata set <issue-id> --key rating.trigger --value "reviewer" --type string
multica issue metadata set <issue-id> --key rating.event --value "R-01:任务按时完成" --type string
multica issue metadata set <issue-id> --key rating.points --value 20 --type number
multica issue metadata set <issue-id> --key rating.status --value "pending" --type string
multica issue metadata set <issue-id> --key rating.occurred_at --value "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --type string

# 2) 核对
multica issue metadata list <issue-id> --output json
```

> **一个 issue = 一条事件记录**：`rating.event`/`rating.points` 是单值 KV，同一 issue 写多条事件会互相
> 覆盖。如需同一任务记多条事件（例如 R-01 之外还要记 R-12 一次通过验收），请把附加事件写到
> 对应的验收/评审记录 issue 上（一条事件对应一个 issue 一条流水），避免覆盖。同一 issue 重复写
> 同一事件则会被结算器全局去重（E_DUP）幂等跳过，不会双计。

### 6.2 示例：退回返工（R-04）

任务 完成→in_review→被退回：

```bash
multica issue metadata set <issue-id> --key rating.trigger --value "reviewer" --type string
multica issue metadata set <issue-id> --key rating.event --value "R-04:任务被退回返工" --type string
multica issue metadata set <issue-id> --key rating.points --value -10 --type number
multica issue metadata set <issue-id> --key rating.status --value "pending" --type string
multica issue metadata set <issue-id> --key rating.occurred_at --value "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --type string
```

### 6.3 示例：红线事件与防失真联动（R-31）

季度内发现某智能体第 2 次违反约束：

```bash
multica issue metadata set <issue-id> --key rating.trigger --value "reviewer" --type string
multica issue metadata set <issue-id> --key rating.event --value "R-31:违反约束" --type string
multica issue metadata set <issue-id> --key rating.points --value -20 --type number
multica issue metadata set <issue-id> --key rating.status --value "pending" --type string
multica issue metadata set <issue-id> --key rating.occurred_at --value "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --type string
```

季度人评时 `check_anti_fraud` 将按流水统计 R-31 计数 ≥2 → 自动标注 **等级上限 C（R-71）**；评审人需在
季度表单中确认该标注并写入最终等级。

---

## 七、常见错误与检查清单

### 7.1 常见错误及处理

| 场景 | 处理 |
|------|------|
| 事件编号/积分写错，状态仍为 `pending` | 直接重新 `set` 同名键覆盖（结算前可改） |
| 事件写错 issue，状态仍为 `pending` | `multica issue metadata delete <issue-id> --key <k>` 删除后重写 |
| 事件已 `credited`/`escalated` | **禁止修改**；走 E-01~E-07 升级路径由最高决策者裁定 |
| 同一事件重复写入 | 结算器全局去重（E_DUP）幂等跳过，无需处理 |
| 忘记 `rating.occurred_at` | 结算器回退当前时间；不影响入账 |
| `rating.points` 写成字符串 | 结算器校验 `rating.points` 必须为整数 → `escalated`；请用 `--type number` |

### 7.2 发布前检查清单

- [ ] 命中事件编号与规则书一致（R-01~R-04 / R-11~R-13 / R-31~R-33）
- [ ] `rating.trigger=reviewer`（行为类事件）
- [ ] `rating.event` 以 `R-` 开头，`rating.points` 为整数
- [ ] `rating.status=pending`，`rating.occurred_at` 已填
- [ ] `multica issue metadata list` 复查 5 键齐备
- [ ] 未触碰已 `credited`/`escalated` 的 metadata

---

## 八、与季度人评流程的衔接

| 环节 | 规则 | 说明 |
|------|------|------|
| 季度客观分 | R-51 | `(M1+M2+M3)/3`，聚合器自动汇总 |
| 人评分 | R-52 / R-53 | `人评分 = Σ(维度×权重)×20`；多人取平均 |
| 综合分 | R-61 | `季度综合分 = 客观×80% + 人评×20%` |
| 等级判定 | R-62~R-66 | S≥95 / A=85-94 / B=70-84 / C=60-69 / D<60 |
| 防失真 | R-71 / R-72 | R-31≥2次→上限C；R-32≥2次→降一档 |
| 异常处理 | E-01~E-07 | 流水缺失/评分人不足/档案缺失/等级D/背离≥40 分等 |
| 表单/触发 | `review-scheduler.sh --quarterly` | 季度末最后 3 天触发，生成
  `agents/reviews/scoring/quarterly/{agent}/YYYY-Qn.md` |

行为类事件（第 4 节）是季度客观分的**数据来源**；评审人在季度人评时负责：确认流水完整性
（`python3 scripts/audit-events.py --month <YYYY-MM>`）→ 核验自优化事件 → 填写人评维度分 →
综合等级判定 → 防失真校验 → 异常处理（E 系列）。

---

## 九、参考与维护

- 规则清单：`rating-workflow-rulebook.md` v1.0（28 条规则，角色分工见 §6.1）
- 结算器：`rating-settler.py`（`pending → credited/escalated`，指数退避 ≤3 次）
- 聚合器：`rating-aggregator.py`（月度 R-41 / 季度 R-51）
- 调度器：`review-scheduler.sh`（周/月/季度审查与季度人评触发）
- 定时任务 Runbook：`docs/runbook.md`（告警与 SLA、流水完整性对账）
- 本文件由**技术文档撰写者**维护，随规则书（v1.1+）或运行时边界变更同步更新。
