# quarterly-review-judge.py 验收测试报告（P1-9 / KA-74 · P1-10 联调）

**任务**: KA-74 P1-9 季度人评表单自动判定（客观/人评/综合/等级）；KA-75 P1-10 联调（防失真接入）
**执行人**: 开发者工具工程师
**日期**: 2026-08-17
**脚本**: `agents/capability-system/quarterly-review-judge.py`（仓库 `src/quarterly-review-judge.py`）
**测试**: `agents/capability-system/tests/test-quarterly-review-judge.py`（仓库 `src/test-quarterly-review-judge.py`）

---

## 一、交付物

| 文件 | 说明 |
|---|---|
| `quarterly-review-judge.py` | 季度人评表单自动判定脚本（Python3，幂等，`--dry-run`/`--status`/`--json`，原子写入） |
| `test-quarterly-review-judge.py` | 验收测试套件（unittest，**24** 条用例全通过） |

**P1-10 联调记录（spec 6.2）**：防失真修正统一由 `anti-distortion-rules.py` 唯一权威施加。

- **退役**：`parse_anti_fraud()`（读表单 cap_note/防失真区文案触发标记）整体移除；
  `apply_caps()` 中 R-71/R-72 分支退役——judge 只输出**原始等级 auto_grade** + `single_reviewer` 表单事实。
- **接入**：`final_grade = apply_anti_distortion(auto_grade, counts, single_reviewer)`（E-02→R-72→R-71）；
  R-31/R-32 计数来自事件流水（`count_distortion_events`，结构化事件 ID + 季度范围 + fail-open）。
- **留痕**：judge 调用 `write_decision_log` 写 append-only 决策日志（幂等签名，同判定重复运行不重复追加）。
- **测试预期更新**：`test_apply_caps` 关键行为变更 —— S + 单评分人 + R-32×2：**A → B**（终审 B-3 顺序 E-02→R-72→R-71）。

**返工记录（KA-92，首版）**：等级表 ☑ 残留修复、规则编号订正 R-61/R-62~R-66、`fmt_score` 浮点尾差、
单评分人非平均标注、`--agent` 越界防护——均已保留。

## 二、判定规则（方案C R-51~R-53 + R-61~R-66 + 防失真委托）

| 要素 | 规则 | 实现 |
|---|---|---|
| 客观分 | R-51 (M1+M2+M3)/3，由聚合器写入表单「一、」区 | 本脚本只读取，不回写 |
| 人评分 | R-52 单评分人 = Σ(维度分×权重)×20；R-53 最终分 = 各评分人平均 | 从表单「二、」维度分表逐行解析（维度/权重/评分人列通用） |
| 综合分 | R-61 客观×0.8 + 人评×0.2 | 1 位小数显示，整数时不带小数 |
| 原始等级 | R-62~R-66 S≥95 / A 85-94 / B 70-84 / C 60-69 / D<60 | 综合分查表（`grade_for`，**未经防失真修正**） |
| 防失真修正 | E-02 单评分人→上限A；R-72 缺自评≥2→降一档；R-71 红线≥2→上限C | **委托 `apply_anti_distortion(auto_grade, counts, single_reviewer)`**，顺序 E-02→R-72→R-71 |
| 决策留痕 | append-only 决策日志 | 调用 `anti-distortion-rules.write_decision_log`（幂等） |

## 三、验收标准核对

| # | 验收标准 | 结果 |
|---|---------|------|
| 1 | 计算正确性：人评分/人评最终分/综合分/等级 与手工计算逐项一致 | ✅ 全 5 分=100、全 4 分=80、5,4,5,4,5=92 等；综合分/等级边界全覆盖 |
| 2 | 表单回填：填维度分后运行，全部空白被自动判定并写回 | ✅ 端到端回填 人评分/综合分/等级/等级表标记/评分人数量 |
| 3 | 幂等：二次运行 0 写入 | ✅ `changed=False` / `note=已是最新（无变化）`；决策日志同判定不重复追加 |
| 4 | dry-run 零写 | ✅ DRY-RUN 判定但不产生写入（含不写决策日志） |
| 5 | 待填写：人评维度分未填 no-op 不崩 | ✅ 全部真实季度报告（聚合器客观分版）正确判为 pending |
| 6 | 防失真（P1-10 联调）：R-31 事件→上限C / R-32 事件→降一档 / E-02 单评分人→上限A | ✅ 基于事件流水计数；S+单评分人+R-32×2 → **B**（#16，A→B 行为变更） |
| 7 | 等级边界：95/85/70/60 档位切换 | ✅ 94.9→A / 85→A / 84.9→B / 70→B / 69.9→C / 60→C / 59.9→D |
| 8 | 缺失/异常：缺表单/缺客观分/非权重行 不崩 | ✅ missing / no-objective / pending 分级处理 |

## 四、测试套件（24 条用例全通过）

```
test_apply_caps                                   ... ok   # 防失真叠加（委托 apply_anti_distortion；S+单评分人+R-32→B）
test_fmt_score                                    ... ok   # 整数/整值/一位小数显示 + 浮点尾差
test_grade_boundaries                             ... ok   # 等级档位边界
test_reviewer_score_formula                       ... ok   # R-52 公式 + 缺失维度
test_cli_bad_quarter_exit2                        ... ok   # 非法季度参数退出码 2
test_cli_dry_run_exit0                            ... ok   # CLI dry-run 退出码 0
test_cli_json                                     ... ok   # --json 机器输出
test_cli_reject_agent_path_traversal              ... ok   # --agent 路径分隔符/.. 拒绝
test_cli_status_no_write                          ... ok   # --status 只读
test_decision_log_written_idempotent              ... ok   # judge 写决策日志 + 幂等（新增）
test_dry_run_no_write                             ... ok   # dry-run 不写
test_end_to_end_fill                              ... ok   # 端到端判定回填
test_fresh_objective_only_report_pending          ... ok   # 聚合器客观分报告 → pending
test_grade_table_marker_only_selected_row         ... ok   # 等级表仅标记判定行
test_grade_table_resync_on_grade_change           ... ok   # 等级变更后重跑 ☑ 迁移（防残留）
test_idempotent_second_run_no_write               ... ok   # 二次运行 0 写入
test_missing_form                                 ... ok   # 缺表单不崩
test_missing_objective                            ... ok   # 缺客观分不崩
test_pending_no_scores                            ... ok   # 维度分未填 pending
test_r71_cap_c                                    ... ok   # 事件流水 R-31×2 → 红线上限 C（重写）
test_r72_downgrade                                ... ok   # 事件流水 R-32×2 → 缺自评降档（重写）
test_resync_on_input_change                       ... ok   # 输入变化后重跑同步刷新
test_single_reviewer_e02                          ... ok   # 单评分人上限 A + 非平均标注
test_single_reviewer_plus_r32                     ... ok   # S+单评分人+R-32×2 → B（#16，新增）
```

运行命令: `cd <生产路径>/agents/capability-system && python3 tests/test-quarterly-review-judge.py -v`

## 五、口径说明

1. **表单为纯函数**：输出（人评/综合/等级）仅依赖「客观分 + 人评维度分 + 事件流水计数」三个输入；
   维度分/事件变化后重跑即同步刷新，不产生漂移——等级表「判定」☑ 同步迁移，计数恒为 1。
2. **修正委托（P1-10 联调）**：judge 不再自算防失真（`parse_anti_fraud`/`apply_caps` 退役），
   原始等级 + `single_reviewer` 交给 `anti-distortion-rules.apply_anti_distortion` 唯一权威计算；
   修正链 E-02→R-72→R-71，R-71 为最终硬性天花板。
3. **计数源（N-4）**：R-31/R-32 计数来自 `count_distortion_events`（结构化事件 ID + 季度范围 +
   `(issue, event_id)` 去重 + fail-open）；不再解析表单 cap_note/防失真区文案（文本 grep 与流水
   不同源，静默失效风险消除）。
4. **决策日志（N-6）**：judge 在非 dry-run 判定成功后调用 `write_decision_log`，append-only 审计链；
   幂等签名 = 判定输入规范化 JSON 的 sha256，重复运行不重复追加。
5. **幂等**：回填采用「临时文件 + os.replace」原子替换，内容一致则跳过；同一表单重复运行 0 写入。
6. **缺失不崩**：缺表单→`missing`、缺客观分→`no-objective`、人评区/维度分未填→`pending`，全部 exit 0；
   防失真模块加载失败 → fail-open（不应用修正，仅输出原始等级并标注）。

## 六、运行示例

```bash
python3 quarterly-review-judge.py                           # 当前季度全部表单自动判定
python3 quarterly-review-judge.py --quarter 2026-Q3         # 指定季度
python3 quarterly-review-judge.py --agent "开发者工具工程师"   # 指定智能体
python3 quarterly-review-judge.py --dry-run                 # 预演，不写（先行验证）
python3 quarterly-review-judge.py --status                  # 只读状态（待填写清单）
python3 quarterly-review-judge.py --json                    # 机器可读汇总
```

## 七、与 P1 阶段联动

- 调度器 `review-scheduler.sh --quarterly` 在季末最后 3 天生成人评表单（含客观分「一、」区 + 人评「二、」区空白）；
- 负责人 + ≥1 位协作方填写「二、」维度分（1-5 分）；
- 本脚本运行一次：解析维度分 → 计算人评/综合 → 查表原始等级 → **委托防失真模块**计算最终等级 → 回填表单 → 写决策日志；
- P1-10（KA-75）防失真机制（红线上限C / 缺自评降档 / 单评分人上限A）已在季度链路上全自动生效。
