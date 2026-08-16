# anti-distortion-rules.py 验收测试报告（P1-10 / KA-75）

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
| `test-anti-distortion-rules.py` | 验收测试套件（unittest，19 条用例全通过） |
| `rating-settler.py`（修改） | **前置修复 S-1**：结算器去重键 `issue_id` → `(issue_id, rating.event)` |
| `test-rating-settler.py`（修改） | 新增 S-1 去重键 4 条用例（原 6 条 + 新增 4 条 = 10 条全通过） |
| `review-scheduler.sh`（修改） | `check_anti_fraud()` 委托新计数（季度范围 + 结构化事件 ID）；人评表单「四、」渲染 `summarize()` 输出 |
| `test-anti-fraud-scheduler.sh` | 调度器集成测试（4 项验收点全通过） |

> 说明：生产环境脚本位于 `agents/capability-system/`，本仓库镜像于 `src/`（与 P1-9 `quarterly-review-judge.py` 同约定）。调度器 `check_anti_fraud` 引用同目录 `anti-distortion-rules.py`，两套布局均成立。

## 二、规则口径（spec 2.3）

| 步骤 | 规则 | 实现 |
|---|---|---|
| 1 | grade ← auto_grade（∈ S/A/B/C/D） | `apply_anti_distortion` 入参 |
| 2 | r32 ≥ r72_threshold(2) → 降一档（D 为地板） | R-72 修正（demote） |
| 3 | r31 ≥ r71_threshold(2) → 封顶 r71_cap(C)（不抬升更差等级） | R-71 修正（cap），**R-71 为最终硬性上限** |
| 顺序 | **R-72 先降档 → R-71 最后封顶** | 保证双触发时等级不超过 C（ADR-0001 权衡） |

计数（`count_distortion_events`）：事件列前缀解析 `R-31:违反约束` → `R-31`，多事件以 `;` 分隔；按 `(issue, event_id)` 去重；仅统计季度内月份；文件缺失按 0 计（fail-open）。

## 三、验收标准核对

| # | 验收标准 | 结果 |
|---|---------|------|
| 1 | spec 3 边界用例 10 条全部通过 | ✅ 10/10 |
| 2 | 计数：季度范围 / 结构化事件 ID / (issue,event) 去重 / 同 issue 多事件 / fail-open | ✅ 6 条用例 |
| 3 | 决策日志：append-only、幂等（同判定不重复）、不同判定可追加 | ✅ 2 条用例 |
| 4 | `summarize` 输出含触发/未触发/最终等级 | ✅ 2 条用例 |
| 5 | CLI count/check/apply 子命令 | ✅ 4 条用例（含非法月份 exit 2） |
| 6 | S-1 前置修复：同一 issue 两事件不再 E_DUP，同 (issue,事件) 仍幂等 | ✅ 4 条用例（settler） |
| 7 | 调度器接入：check_anti_fraud 委托新计数、触发/未触发/fail-open | ✅ 4 项（bash） |
| 8 | 回归：正常数据 final == auto（用例 6）；聚合器 15 条、判定器 20 条、调度器 4 项全通过 | ✅ |

## 四、spec 3 边界用例验证（10/10）

| # | 场景 | auto | counts r31/r32 | final | 触发规则 | 结果 |
|---|---|---|---|---|---|---|
| 1 | R-31×2 强制 C | S | 2/0 | **C** | R-71 | ✅ |
| 2 | R-32×2 降一档 | S | 0/2 | **A** | R-72 | ✅ |
| 3 | R-31×1 不触发 | S | 1/0 | S | — | ✅ |
| 4 | R-32×1 不触发 | S | 0/1 | S | — | ✅ |
| 5 | 混合各 1 不触发 | A | 1/1 | A | — | ✅ |
| 6 | 正常数据（回归） | B | 0/0 | B | — | ✅ |
| 7 | 双触发：先降后封顶 | S | 2/2 | **C** | R-72, R-71 | ✅ |
| 8 | R-31×2 且 auto=D 不抬升 | D | 2/0 | D | R-71 | ✅ |
| 9 | R-32×2 且 auto=D 撞地板 | D | 0/2 | D | R-72（触发 E-04 升级） | ✅ |
| 10 | R-31×1+R-32×2 仅降档 | A | 1/2 | **B** | R-72 | ✅ |

## 五、口径说明

1. **纯函数边界**：`apply_anti_distortion` / `count_distortion_events` 无副作用；`write_decision_log` 是唯一写入口，由调用方（季度人评判定模块或调度器 `--quarterly` 包装）调用。
2. **fail-open**：事件数据缺失/异常时防失真不惩罚（按 0 计），惩罚必须建立在可信计数之上；反向风险（应罚未罚）由负责人裁定兜底。
3. **触发状态以计数为准**：`summarize` 对 counts-only 结果（调度器表单预检，无 auto_grade）也正确报告 R-71/R-72 是否触发。
4. **S-1 对齐**：结算器去重键改为 `(issue_id, rating.event)` 后，同一 issue 的 R-21 自评与 R-31 违规均可入流水，防失真计数不再漏记；同 (issue, 事件) 跨文件仍 E_DUP（防聚合双计）。
5. **顺序决策**：双触发时先 R-72 降档再 R-71 封顶，R-71 严格支配 R-72（违反约束比缺自评更严重）。
6. **阈值可配置**：`r71_threshold` / `r72_threshold` / `r71_cap` 全部走 config，未来收紧无需改代码。

## 六、运行命令

```bash
# 单元测试（仓库布局）
python3 src/test-anti-distortion-rules.py
python3 src/test-rating-settler.py
bash src/test-anti-fraud-scheduler.sh

# CLI 用法
python3 src/anti-distortion-rules.py count  --events-dir <events> --agent <名> --months 2026-07,2026-08,2026-09
python3 src/anti-distortion-rules.py check   --events-dir <events> --agent <名> --months 2026-07,2026-08,2026-09
python3 src/anti-distortion-rules.py apply   --auto-grade S --events-dir <events> --agent <名> --months 2026-07,2026-08,2026-09
```

## 七、与 P1 阶段联动（接入点待 P1-9 验收）

- 前置修复 S-1 已合入 `rating-settler.py`（结算器去重键）；后续结算 R-31/R-32 行为类负分事件将正常入流水。
- 调度器 `review-scheduler.sh --quarterly` 生成人评表单时，「四、防失真校验」区已渲染新计数摘要（季度范围 + 结构化事件 ID）。
- **季度链路集成**（spec 实施交接清单第 4 项）：`final_grade = apply_anti_distortion(auto_grade, counts)` 接入 P1-9 `quarterly-review-judge.py`、由该模块调用 `write_decision_log` —— 按规格依赖提示，待 KA-74（P1-9）验收后联调，本 run 不修改验收中的 P1-9 交付物。
