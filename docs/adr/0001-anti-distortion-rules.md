# ADR-0001 防失真修正层作为独立纯函数模块（P1-10）

## 状态
accepted（2026-08-17 经资深战略领导者规则口径终审修订；修订点见文末「修订记录」）

## 背景

评分系统方案 C 的防失真规则（R-71 红线上限 C / R-72 缺自评降档）此前只在
`review-scheduler.sh` 的 `check_anti_fraud()` 中以「文本标注」形式实现：对季度人评表单
追加一行提示（如「等级上限C」），最终等级仍由人评负责人手工判定，规则不产生实际阻断。
P1-10 要求将规则升级为「实际阻断/强制」：`季度等级 = apply_anti_distortion(自动判定, 事件流水)`。

P1-9（`src/quarterly-review-judge.py`）已实现自动判定（R-55 查表输出原始等级），
并在其 `apply_caps()` 中先行实现了 R-71/R-72/E-02 的叠加。经代码审查（B-1）与
规则口径终审，为避免「判定层与修正层双重应用」，R-71/R-72（及 E-02）的权威归属
统一定为本模块。

## 决策

1. **新建独立纯函数模块 `src/anti-distortion-rules.py`**（仓库布局；生产镜像为
   `agents/capability-system/anti-distortion-rules.py`），与 P1-9
   `src/quarterly-review-judge.py` 输出串联。**纯核心仅 `apply_anti_distortion()`**：
   接受 `(auto_grade, counts, single_reviewer, config)`，返回 `(final_grade, corrections)`；
   模块自身无副作用。IO（读季度流水计数 `count_distortion_events`、写决策日志
   `write_decision_log`）为调用方侧的只读辅助 / 唯一写入口。
2. **修正动作必须留痕**：`write_decision_log` 追加写 `reviews/scoring/anti-distortion/{agent}/{quarter}.md`
   （append-only 决策日志），与季度人评表单解耦。幂等签名 = 判定输入的规范化 JSON 的
   sha256（N-6 口径；当前实现为 sha1 截断，联调时对齐为 sha256）。
3. **计数按结构化事件 ID**：从事件列前缀解析 `R-31` / `R-32`（正则 `R-(\d+)[：:]`，
   **半角/全角冒号均归一化**，N-4），按 `(issue, event_id)` 去重，只统计**季度内**
   3 个月份。「季度内 ≥2 次」的口径 = **≥2 个不同 issue 各至少 1 次**（N-2）：
   同一 issue 同事件在结算层已幂等去重，重复计数无意义。
4. **修正顺序（关键）**：**E-02（单评分人封顶 A）→ R-72（降一档）→ R-71（封顶 C）**。
   R-71 为最终硬性天花板（最后施加）；E-02 与 R-72 针对不同问题（评审置信度 vs
   行为合规），各自独立生效。

## 权衡

- **纯函数 vs 与调度器耦合**：纯函数可单测、可复用、幂等、无副作用，代价是调用方需
  多写一层 IO 包装；耦合实现（在 `review-scheduler.sh` 内就地算）更省事但不可测、易回归。
  选纯函数——验收标准要求边界用例可单测，纯函数是唯一能廉价满足的结构。
- **结构化事件计数 vs 文本 grep**：事件列已是 `R-31:违反约束` 这种结构化前缀，
  按前缀计数准确、抗描述措辞变化；文本 grep 依赖字面词、且把 `-20` 当触发词会误伤
  未来任何同为 -20 的非 R-31 事件。代价是需要与 `rating-settler.py` 的写流水格式
  维持契约（事件列首字段恒为 `R-xx:`，多事件以 `;` 分隔）。
- **独立决策日志 vs 写回季度表单**：表单是给人评负责人看的，混入机器修正记录会让
  表单变噪；独立日志 append-only，天然审计。
- **顺序决策（终审修订）**：先封顶再降档会把 S 双触发打成 D（过度双罚）；
  **先降档后封顶得 C**——R-71 作为最终硬性天花板，保证双触发时等级不超过 C。
  E-02 置于最前：单评分人 + 缺自评同时触发须劣于仅单评分人
  （S + 单评分人 + R-32≥2 → E-02 至 A → R-72 至 **B**）。

## 失败模式与恢复

| 失败模式 | 检测 | 恢复 |
|---|---|---|
| 季度事件流水文件缺失 | 计数为 0 + `E_MISS` 标记（fail-open，不冤枉） | 补记流水后重算（幂等） |
| 同一 R-31/R-32 跨月重复 | `(issue, event_id)` 去重 | `audit-events.py --reconcile` 清重后重算 |
| 同一 issue 含 R-21 与 R-31 两事件被旧 `E_DUP` 拦截 | 结算日志 E_DUP | **S-1 已修复**：结算器去重键 `issue_id` → `(issue_id, rating.event)` |
| R-72 降档撞 D 地板 | `final=D`，corrections 留痕 | 触发 E-04：升级最高决策者专项复盘 |
| 误记 R-31/R-32 | 裁定复核 | 资深战略领导者 override 并留痕 |
| 事件归属漂移（assignee 在两次结算间变更） | 裁定复核 | N-5 前提：以结算时 issue 归属为准；如成实际困扰再引入「写入时显式指定被罚 agent」 |

## 后果

- 正向：规则从「提示」变为「强制」；修正可追溯；边界可单测；阈值/上限可配置演进；
  判定层（P1-9）与修正层（P1-10）单一权威，规避双重应用。
- 反向：P1-9 `quarterly-review-judge.py` 的 `parse_anti_fraud()` 与 `apply_caps()`
  中 R-71/R-72 分支需在 KA-74 验收后**退役**（judge 只输出原始等级 + `single_reviewer`
  表单事实）；`apply_caps` 测试预期同步更新（S+单评分人+R-32：A → B）。
- 依赖：本 ADR 生效依赖 P1-7（自评块字段，R-32 检测基础）与 P1-9（自动判定输出）。
  模块已独立开发测试（纯函数），季度链路接入待 P1-9 验收后联调。

## 修订记录

- **2026-08-17（终审修订）**：B-1 auto_grade 语义（原始等级，未经防失真修正）；
  B-2 模块命名（`src/quarterly-review-judge.py` / `src/anti-distortion-rules.py`，
  更正原 `rating-form-evaluator.py` 表述）；B-3 E-02 纳入修正层且顺序
  E-02→R-72→R-71；N-1 权衡理由重写（demote 方向）；N-2 计数口径收紧；N-4 冒号归一化；
  N-6 决策日志签名 sha256；N-7 纯函数边界（仅 `apply_anti_distortion`）。

## 相关

- 需求：P1-10（《开发需求清单》v1.0）；终审：资深战略领导者（2026-08-17）
- 规格：`docs/p1-10-anti-distortion-spec.md`
- 实施与测试：`src/anti-distortion-rules.py`、`docs/anti-distortion-rules-test-report.md`（已入库）
