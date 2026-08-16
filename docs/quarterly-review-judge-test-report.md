# quarterly-review-judge.py 验收测试报告（P1-9 / KA-74）

**任务**: KA-74 P1-9 季度人评表单自动判定（客观/人评/综合/等级）
**执行人**: 开发者工具工程师
**日期**: 2026-08-17
**脚本**: `agents/capability-system/quarterly-review-judge.py`（仓库 `src/quarterly-review-judge.py`）
**测试**: `agents/capability-system/tests/test-quarterly-review-judge.py`（仓库 `src/test-quarterly-review-judge.py`）

---

## 一、交付物

| 文件 | 说明 |
|---|---|
| `quarterly-review-judge.py` | 季度人评表单自动判定脚本（Python3，幂等，`--dry-run`/`--status`/`--json`，原子写入） |
| `test-quarterly-review-judge.py` | 验收测试套件（unittest，22 条用例全通过） |

**返工记录（KA-92）**：审核方独立复现「等级表 ☑ 在等级变更时残留」P1 缺陷，返工修复后重新验收。本次修复与订正：

- **P1 等级表残留**：`render_form` 渲染前先清全部等级行 ☑，仅标记当前等级行；新增 `test_grade_table_resync_on_grade_change`（综合分 92→84 跨 A/B 档，☑ 迁移且计数恒为 1）。
- **规则编号订正**：综合分 R-54→**R-61**、等级 R-55→**R-62~R-66**（以 `rating-workflow-rulebook.md` v1.0 为准），脚本 docstring / 测试 / 本报告同步订正。
- **P2 同修**：综合分浮点尾差显示（`fmt_score` 先 `round(v, 6)`）；单评分人「人评最终分」行标注 `（E-02 单评分人，非平均）`；`--agent` 拒绝空值/路径分隔符/`..`（防越界读写，退出码 2）；`apply_caps` docstring 与实现顺序（R-72→R-71→E-02）一致化。

## 二、判定规则（方案C R-51~R-53 + R-61~R-66 + 防失真）

| 要素 | 规则 | 实现 |
|---|---|---|
| 客观分 | R-51 (M1+M2+M3)/3，由聚合器写入表单「一、」区 | 本脚本只读取，不回写 |
| 人评分 | R-52 单评分人 = Σ(维度分×权重)×20；R-53 最终分 = 各评分人平均 | 从表单「二、」维度分表逐行解析（维度/权重/评分人列通用） |
| 综合分 | R-61 客观×0.8 + 人评×0.2 | 1 位小数显示，整数时不带小数 |
| 等级 | R-62~R-66 S≥95 / A 85-94 / B 70-84 / C 60-69 / D<60 | 综合分查表 |
| 防失真 | R-71 红线≥2→上限C；R-72 缺自评≥2→降一档；E-02 单评分人→上限A | 解析表单 cap_note/防失真区，叠加判定 |

等级叠加顺序：R-72 降一档（对基础等级）→ R-71 硬上限 C → E-02 上限 A（保证任何情况下不超过对应上限）。

## 三、验收标准核对

| # | 验收标准 | 结果 |
|---|---------|------|
| 1 | 计算正确性：人评分/人评最终分/综合分/等级 与手工计算逐项一致 | ✅ 全 5 分=100、全 4 分=80、5,4,5,4,5=92 等；综合分/等级边界全覆盖 |
| 2 | 表单回填：填维度分后运行，全部空白被自动判定并写回 | ✅ 端到端回填 人评分/综合分/等级/等级表标记/评分人数量 |
| 3 | 幂等：二次运行 0 写入 | ✅ `changed=False` / `note=已是最新（无变化）` |
| 4 | dry-run 零写 | ✅ DRY-RUN 判定但不产生写入 |
| 5 | 待填写：人评维度分未填 no-op 不崩 | ✅ 全部真实季度报告（聚合器客观分版）正确判为 pending |
| 6 | 防失真：R-71 上限C / R-72 降一档 / E-02 单评分人上限A | ✅ 含叠加组合（S→A→C） |
| 7 | 等级边界：95/85/70/60 档位切换 | ✅ 94.9→A / 85→A / 84.9→B / 70→B / 69.9→C / 60→C / 59.9→D |
| 8 | 缺失/异常：缺表单/缺客观分/非权重行 不崩 | ✅ missing / no-objective / pending 分级处理 |

## 四、测试套件（22 条用例全通过）

```
test_apply_caps                                   ... ok   # R-71/R-72/E-02 叠加
test_fmt_score                                    ... ok   # 整数/整值/一位小数显示 + 浮点尾差
test_grade_boundaries                             ... ok   # 等级档位边界
test_reviewer_score_formula                       ... ok   # R-52 公式 + 缺失维度
test_cli_bad_quarter_exit2                        ... ok   # 非法季度参数退出码 2
test_cli_dry_run_exit0                            ... ok   # CLI dry-run 退出码 0
test_cli_json                                     ... ok   # --json 机器输出
test_cli_reject_agent_path_traversal              ... ok   # --agent 路径分隔符/.. 拒绝
test_cli_status_no_write                          ... ok   # --status 只读
test_dry_run_no_write                             ... ok   # dry-run 不写
test_end_to_end_fill                              ... ok   # 端到端判定回填
test_fresh_objective_only_report_pending          ... ok   # 聚合器客观分报告 → pending
test_grade_table_marker_only_selected_row         ... ok   # 等级表仅标记判定行
test_grade_table_resync_on_grade_change           ... ok   # 等级变更后重跑 ☑ 迁移（防残留）
test_idempotent_second_run_no_write               ... ok   # 二次运行 0 写入
test_missing_form                                 ... ok   # 缺表单不崩
test_missing_objective                            ... ok   # 缺客观分不崩
test_pending_no_scores                            ... ok   # 维度分未填 pending
test_r71_cap_c                                    ... ok   # 红线上限 C
test_r72_downgrade                                ... ok   # 缺自评降档
test_resync_on_input_change                       ... ok   # 输入变化后重跑同步刷新
test_single_reviewer_e02                          ... ok   # 单评分人上限 A + 非平均标注
```

运行命令: `cd <生产路径>/agents/capability-system && python3 tests/test-quarterly-review-judge.py -v`（或 `python3 -m unittest tests.test-quarterly-review-judge -v`）

## 五、口径说明

1. **表单为纯函数**：输出（人评/综合/等级）仅依赖「客观分 + 人评维度分」两个输入；维度分变化后重跑即同步刷新，不产生漂移——等级表「判定」☑ 同步迁移（旧行清除、仅当前等级行标记），计数恒为 1。
2. **人评维度分解析**：从表单「二、」维度分表按表头动态识别评分人列（兼容后续扩展列）；某评分人任一维度缺失则判定其「未就绪」，全部评分人就绪才回填。
3. **客观分只读**：客观分由 `rating-aggregator.py` 维护（R-51），本脚本不写客观分区，避免与聚合器争写。
4. **幂等**：回填采用「临时文件 + os.replace」原子替换，内容一致则跳过；同一表单重复运行 0 写入。
5. **缺失不崩**：缺表单→`missing`、缺客观分→`no-objective`、人评区/维度分未填→`pending`，全部 exit 0，不影响批量。
6. **防失真来源**：R-71/R-72 标记读取表单「三、」cap_note（`（等级上限C）`/`（等级降一档）`）与「四、」防失真区文案；调度器 `review-scheduler.sh check_anti_fraud` 写入在先，本脚本叠加判定在后。

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
- 本脚本运行一次，自动判定并回填 人评/综合/等级 及防失真标记；
- P1-10（KA-75）在此基础上将防失真机制（红线上限C / 缺自评降档）进一步自动化到写事件层。
