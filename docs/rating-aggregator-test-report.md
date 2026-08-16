# rating-aggregator.py 验收测试报告（P0-1 / KA-16）

**任务**: KA-16 P0-1 rating-aggregator.py 聚合器开发（月度R-41/季度R-51）
**执行人**: 开发者工具工程师
**日期**: 2026-08-16
**脚本**: `agents/capability-system/rating-aggregator.py`
**测试**: `agents/capability-system/tests/test-rating-aggregator.py`
**交付报告**: 58 个智能体月度/季度报告（含原 46 + 12 工程智能体）

---

## 一、交付物

| 文件 | 说明 |
|---|---|
| `capability-system/rating-aggregator.py` | 聚合器主脚本（Python3，幂等，`--dry-run`，原子写入） |
| `capability-system/rating-benchmarks.conf` | 类别→基准月积分共享配置（R-42，review-scheduler.sh 与聚合器共用） |
| `capability-system/tests/test-rating-aggregator.py` | 验收测试套件（unittest，15 条用例） |
| `reviews/scoring/monthly/{agent}/2026-08.md` | 58 个智能体月度百分制报告 |
| `reviews/scoring/quarterly/{agent}/2026-Q3.md` | 58 个智能体季度客观分报告 |

## 二、验收标准核对

| # | 验收标准 | 结果 |
|---|---------|------|
| 1 | 与手工计算一致：以全量 R-41/R-51 事件为样本，抽 3 个月度 + 1 个季度手工比对 | ✅ 月度 3 条 + 季度 1 条逐项一致（真实事件，见下节）；测试套件另覆盖 30 条月度 + 10 条季度 |
| 2 | 幂等：重复运行结果一致 | ✅ 二次运行 `实际写入: 0 / 无变化跳过: 116` |
| 3 | dry-run 零写：dry-run 模式不产生任何写操作 | ✅ 输出目录零写入 |
| 4 | 缺失不崩：缺 agent 记录或必需字段时跳过该条并记告警、不中断全量聚合 | ✅ E_MISS/E_EMPTY/E_PARSE/E_CAT 标记不崩溃，单条异常不影响全量 |
| 5 | 报告含 category 元数据即可，不强制按 category 分组 | ✅ 每份报告含 `**类别**` 与 `**基准月积分**` |
| 6 | 与 R-42 category 映射交叉核对一致（代码审查员验收项） | ✅ 直接读取平台 `agent.description` 的 `[category=X]` 标签（46/46，见第六节） |

## 三、手工计算 vs 脚本输出（真实事件样本）

事件流水来源：工作区 7 条真实评分事件（issue metadata 中的 R-21/R-22，触发方 agent），已按结算器口径
（`rating-settler.py append_to_events` 格式）写入 `reviews/scoring/events/{agent}/2026-08.md`。

### 月度百分制抽查（R-41: clamp(积分×100÷基准, 0, 120)，整数除法）

| 智能体 | 类别/基准 | 事件积分 | 手工 | 脚本 |
|---|---|:---:|:---:|:---:|
| 财务规划与分析分析师 | data/350 | +5(R-21) +5(R-22)=10 | 10×100÷350=2 | **2** |
| 资深战略领导者 | creative/300 | +5(R-21)=5 | 5×100÷300=1 | **1** |
| 数据工程师 | data/350 | +5(R-22)=5 | 5×100÷350=1 | **1** |

### 季度客观分抽查（R-51: (M1+M2+M3)÷3，缺失月按 0 计并标记 E_MISS）

| 智能体 | M1(07) | M2(08) | M3(09) | 手工 | 脚本 |
|---|:---:|:---:|:---:|:---:|:---:|
| 财务规划与分析分析师 | 0(缺失) | 2 | 0(缺失) | (0+2+0)÷3=0 | **0** |

> 当前真实事件仅覆盖 2026-08（结算器尚未随 P0-3 cron 产生更多月份流水），其余智能体报告为
> 0 分占位报告并附 `E_MISS` 告警标记；流水就绪后重复运行聚合器即可自动填入真实积分。

## 四、测试套件（15 条用例全通过）

```
test_desc_category_regex                         ... ok   # R-42 [category=X] 描述标签解析
test_norm_name                                   ... ok   # 名称归一化（空格/短横）
test_resolve_category_cli_first                  ... ok   # CLI R-42 标签 > 档案标签 > 关键词推断
test_resolve_category_profile_fallback           ... ok   # 档案标签兜底
test_resolve_category_keyword_fallback_no_profile... ok   # 无档案 → 关键词推断 + E_CAT
test_all_agents_generate_reports                 ... ok
test_category_precedence                         ... ok   # 类别优先级；clamp 上下限
test_default_mode_generates_for_all              ... ok
test_dry_run_no_writes                           ... ok
test_idempotent                                  ... ok   # 二次运行 0 写入
test_missing_empty_flags                         ... ok   # E_MISS/E_EMPTY/E_PARSE
test_missing_profile_does_not_abort              ... ok   # 缺 agent 记录 E_CAT 不中断全量
test_monthly_hand_calc_consistency               ... ok   # 30 条逐项一致
test_quarterly_hand_calc_consistency             ... ok   # 10 条逐项一致
test_quarterly_section_preservation              ... ok   # 更新既有调度器表单仅改客观分区
```

运行命令: `cd agents/capability-system && python3 -m unittest tests.test-rating-aggregator -v`

## 五、口径说明

1. **月度百分制（R-41）**：`clamp(积分×100//基准, 0, 120)`，整数除法，与 `review-scheduler.sh calc_monthly_score` 口径一致。
2. **季度客观分（R-51）**：`(M1+M2+M3)//3`，季度恒取 3 个月；缺失月按 **0** 计入并标记 `E_MISS`（如需排除缺失月，由负责人按 E-01 裁定）。
3. **类别→基准**：统一读取 `rating-benchmarks.conf`；类别解析顺序 **R-42 CLI 标签（`[category=X]`）→ 档案 `category` 标签 → 名称关键词推断**。46 个已打标智能体直接使用平台 R-42 标签；12 个工程智能体（无 R-42 标签）用关键词推断兜底（已文档化，不标记异常）。
4. **幂等**：报告内容仅依赖 (agent, 周期, 事件流水)，与运行时间无关；写入采用「临时文件 + os.replace」原子替换，内容不变则跳过。
5. **缺失不崩**：缺流水→`E_MISS`、空流水→`E_EMPTY`、坏行/列数不足→`E_PARSE`、缺 agent 记录→`E_CAT`，全部「跳过该条并记告警、不中断全量聚合」；主循环对单智能体异常兜底 try/except。
6. **既有季度人评表单兼容**：若目标季度文件为 `review-scheduler.sh` 生成的人评表单（含 `## 一、`/`## 二、`），仅更新「一、季度客观分」段落，保留人评区（二~六）。

## 六、R-42 交叉核对（供代码审查员验收）

聚合器直接读取 `multica agent list` 返回的 `agent.description` 中 `[category=X]` 标签（`tag-agent-categories.py`
写入的 R-42 映射载体），实测 **46/46 已打标智能体被正确识别**。

与 P0-2 早期的映射报告草稿（`category-mapping-report.md`）比对，发现 **2 处差异**，以平台实际标签为准：

| 智能体 | 映射报告草稿 | 平台实际标签（聚合器所用） |
|---|---|:---:|
| Jira 工作流管理员 | technical | execution |
| 产品经理 | execution | creative |

> 差异为 P0-2 打标结果与草稿不一致，属 P0-2 验收范畴；聚合器始终消费平台实际标签，保证与生效中的 R-42 映射一致。
> 如需按草稿口径调整，改 `agent.description` 标签后重跑聚合器即可（幂等，仅差异处更新）。

## 七、运行示例

```bash
python3 rating-aggregator.py                              # 当前月 + 当前季度（全部智能体）
python3 rating-aggregator.py --month 2026-08              # 仅月度
python3 rating-aggregator.py --quarter 2026-Q3            # 仅季度
python3 rating-aggregator.py --dry-run                    # 预演，不写
python3 rating-aggregator.py --all                        # 扫描 events 下全部月份/季度
python3 rating-aggregator.py --no-cli-categories          # 离线/测试，不读 CLI 类别
```
