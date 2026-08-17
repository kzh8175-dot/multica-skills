# anti-distortion-rules.py 验收测试报告（P1-10 / KA-75 · 联调版）

**任务**: KA-75 P1-10 防失真机制自动化（红线上限C / 缺自评降档）
**执行人**: 开发者工具工程师
**日期**: 2026-08-17
**脚本**: `agents/capability-system/anti-distortion-rules.py`（仓库 `src/anti-distortion-rules.py`）
**测试**: `agents/capability-system/tests/test-anti-distortion-rules.py`（仓库 `src/test-anti-distortion-rules.py`）

---

## 一、交付物

| 文件 | 说明 |
|---|---|
| `anti-distortion-rules.py` | 防失真修正层纯函数模块（Python3；`count_distortion_events` / `apply_anti_distortion` / `write_decision_log` / `summarize` + CLI） |
| `test-anti-distortion-rules.py` | 验收测试套件（unittest，**24** 条用例全通过；含终审版 18 条边界用例） |
| `rating-settler.py`（修改） | **前置修复 S-1**：去重键 `issue_id` → `(issue_id, rating.event)`；联调 **N-4**：事件 ID 半/全角冒号归一化后比对 |
| `test-rating-settler.py`（修改） | 新增 S-1 去重键 4 条 + N-4 全角冒号归一化 1 条（原 6 条 + 5 条 = **11** 条全通过） |
| `quarterly-review-judge.py`（修改） | **联调（spec 6.2）**：接入 `final_grade = apply_anti_distortion(auto_grade, counts, single_reviewer)`，由 judge 调 `write_decision_log`；`parse_anti_fraud()`/`apply_caps()` R-71/R-72 分支退役 |
| `test-quarterly-review-judge.py`（修改） | judge 联调测试（**24** 条全通过；`test_apply_caps` 预期更新 S+单评分人+R-32：A→B） |
| `review-scheduler.sh`（修改，首版已合入） | `check_anti_fraud()` 委托新计数（季度范围 + 结构化事件 ID） |
| `test-anti-fraud-scheduler.sh` | 调度器集成测试（4 项验收点全通过） |

> 说明：生产环境脚本位于 `agents/capability-system/`，本仓库镜像于 `src/`（与 P1-9 `quarterly-review-judge.py` 同约定）。

## 二、规则口径（spec 2.3 终审版）

| 步骤 | 规则 | 实现 |
|---|---|---|
| 1 | grade ← auto_grade（∈ S/A/B/C/D，**原始等级**，B-1） | `apply_anti_distortion` 入参 |
| 2 | single_reviewer 且 grade 优于 A → **封顶 A**（E-02，置于最前） | E-02 修正（cap） |
| 3 | r32 ≥ r72_threshold(2) → 降一档（D 为地板） | R-72 修正（demote） |
| 4 | r31 ≥ r71_threshold(2) → 封顶 r71_cap(C)（不抬升更差等级） | R-71 修正（cap），**R-71 为最终硬性上限** |
| 顺序 | **E-02 → R-72 → R-71**（终审 B-3） | 单评分人 + 缺自评同时触发须劣于仅单评分人（#16 得 B） |

计数（`count_distortion_events`）：事件列前缀解析 `R-31:违反约束` / `R-31：违反约束` → `R-31`
（**N-4：半角/全角冒号归一化**，正则 `R-(\d+)[：:]`）；多事件以 `;` 分隔；按
`(issue, event_id)` 去重；仅统计季度内月份；文件缺失按 0 计（fail-open）。

决策日志（`write_decision_log`）：append-only，幂等签名 = 判定输入规范化 JSON 的
**sha256** 全量摘要（**N-6**：原 sha1 截断 12 位已对齐）。

## 三、验收标准核对

| # | 验收标准 | 结果 |
|---|---------|------|
| 1 | spec 3 边界用例 **18 条**全部通过（含 E-02 四场景 + auto=C 三场景 + 阈值=1） | ✅ 18/18 |
| 2 | 计数：季度范围 / 结构化事件 ID / (issue,event) 去重 / 同 issue 多事件 / **全角冒号归一化** / fail-open | ✅ 7 条用例 |
| 3 | 决策日志：append-only、幂等（同判定不重复）、不同判定可追加、**sha256 签名** | ✅ 3 条用例 |
| 4 | `summarize` 输出含触发/未触发/最终等级/E-02 | ✅ 2 条用例 |
| 5 | CLI count/check/apply 子命令（含 `--single-reviewer` E-02） | ✅ 5 条用例（含非法月份 exit 2） |
| 6 | S-1 + N-4：同一 issue 两事件不再 E_DUP，同 (issue,事件) 仍幂等（含全角冒号） | ✅ 5 条用例（settler） |
| 7 | judge 联调：接入 `apply_anti_distortion`、写决策日志、`test_apply_caps` 预期 A→B | ✅ 见 quarterly-review-judge 报告（24 条） |
| 8 | 回归：正常数据 final == auto（用例 6）；聚合器 15 条、判定器 24 条、调度器 4 项全通过 | ✅ |

## 四、spec 3 边界用例验证（18/18）

| # | 场景 | auto | sr | r31/r32 | final | 触发规则 | 结果 |
|---|---|---|---|---|---|---|---|
| 1 | R-31×2 强制 C | S | — | 2/0 | **C** | R-71 | ✅ |
| 2 | R-32×2 降一档 | S | — | 0/2 | **A** | R-72 | ✅ |
| 3 | R-31×1 不触发 | S | — | 1/0 | S | — | ✅ |
| 4 | R-32×1 不触发 | S | — | 0/1 | S | — | ✅ |
| 5 | 混合各 1 不触发 | A | — | 1/1 | A | — | ✅ |
| 6 | 正常数据（回归） | B | — | 0/0 | B | — | ✅ |
| 7 | 双触发：先降后封顶 | S | — | 2/2 | **C** | R-72, R-71 | ✅ |
| 8 | R-31×2 且 auto=D 不抬升 | D | — | 2/0 | D | R-71 | ✅ |
| 9 | R-32×2 且 auto=D 撞地板 | D | — | 0/2 | D | R-72（触发 E-04 升级） | ✅ |
| 10 | R-31×1+R-32×2 仅降档 | A | — | 1/2 | **B** | R-72 | ✅ |
| 11 | auto=C 双触发 | C | — | 2/2 | **D** | R-72, R-71 | ✅ |
| 12 | auto=C 仅 R-31（封顶 no-op） | C | — | 2/0 | C | R-71 | ✅ |
| 13 | auto=C 仅 R-32 | C | — | 0/2 | **D** | R-72 | ✅ |
| 14 | 阈值=1 变体（config） | S | — | 1/0 | **C** | R-71（`r71_threshold=1`） | ✅ |
| 15 | 单评分人 封顶 A | S | ✓ | 0/0 | **A** | E-02 | ✅ |
| 16 | 单评分人 + R-32×2 | S | ✓ | 0/2 | **B** | E-02, R-72 | ✅ |
| 17 | 单评分人 + R-31×2 | S | ✓ | 2/0 | **C** | E-02, R-71 | ✅ |
| 18 | 单评分人 + 双触发 | S | ✓ | 2/2 | **C** | E-02, R-72, R-71 | ✅ |

## 五、口径说明

1. **纯函数边界（N-7）**：`apply_anti_distortion` 是唯一纯核心；`count_distortion_events` 是调用方侧只读辅助；`write_decision_log` 是唯一写入口。
2. **E-02 语义（B-3）**：单评分人封顶 A，置于修正链最前——与 R-72 独立叠加（#16 S+单评分人+R-32×2 → E-02 至 A → R-72 至 **B**，区别于仅单评分人 #15 得 A）；E-02 不抬升 A/B/C/D。
3. **顺序决策**：E-02 → R-72 → R-71；R-71 为最终硬性天花板（双触发得 C，不双罚至 D）。
4. **fail-open**：事件数据缺失/异常时防失真不惩罚（按 0 计），惩罚必须建立在可信计数之上；反向风险（应罚未罚）由负责人裁定兜底。
5. **冒号归一化（N-4）**：事件前缀解析正则 `R-(\d+)[：:]`；结算器 S-1 去重键按归一化 event_id 比对（'R-31:' 与 'R-31：' 视为同一事件，防重复结算双计）。
6. **sha256 签名（N-6）**：决策日志幂等签名 = 判定输入（auto_grade+final_grade+counts+corrections）规范化 JSON 的 sha256 全量摘要；同判定重复运行不重复追加。
7. **阈值可配置**：`r71_threshold` / `r72_threshold` / `r71_cap` 全部走 config，未来收紧无需改代码。

## 六、运行命令

```bash
# 单元测试（仓库布局）
python3 src/test-anti-distortion-rules.py
python3 src/test-rating-settler.py
python3 src/test-quarterly-review-judge.py
bash src/test-anti-fraud-scheduler.sh

# CLI 用法
python3 src/anti-distortion-rules.py count  --events-dir <events> --agent <名> --months 2026-07,2026-08,2026-09
python3 src/anti-distortion-rules.py check   --events-dir <events> --agent <名> --months 2026-07,2026-08,2026-09
python3 src/anti-distortion-rules.py apply   --auto-grade S [--single-reviewer] --events-dir <events> --agent <名> --months 2026-07,2026-08,2026-09
```

## 七、季度链路联动（spec 6.2 联调已完成）

- **S-1 前置修复**已合入 `rating-settler.py`（去重键 `(issue_id, rating.event)`），R-31/R-32 行为类负分事件正常入流水；**N-4** 冒号归一化后，全/半角冒号事件幂等识别。
- **judge 联调（spec 6.2 第 2 项）**：`quarterly-review-judge.py` 退役 `parse_anti_fraud()`/`apply_caps()` R-71/R-72 分支，只输出原始等级 + `single_reviewer`；接入 `final_grade = apply_anti_distortion(auto_grade, counts, single_reviewer)`，由 judge 调用 `write_decision_log` 留痕；`test_apply_caps` 预期同步更新（S+单评分人+R-32：A → B）。
- 调度器 `review-scheduler.sh --quarterly` 生成人评表单时，「四、防失真校验」区渲染新计数摘要（季度范围 + 结构化事件 ID）。
