# 评分系统定时任务 Runbook（P0-3 / KA-18）

生产路径（本机）：
```
/Users/kzh/multica_workspaces_desktop-api.multica.ai/e3ad92f3-ad8e-4eba-bce9-3e670bc345a3/prod/rating-system/
├── agents/capability-system/   # review-scheduler.sh / rating-aggregator.py / rating-settler.py / rating-benchmarks.conf / tests/
├── agents/profiles/            # 59 个能力档案（含 DevOps自动化工程师 持续学习记录）
├── agents/reviews/scoring/     # 事件流水 + 月度/季度报告
├── scripts/                    # 定时任务包装脚本（守卫 + 日志 + 退出码）
├── logs/{settlement,aggregation,review}/   # 运行日志（按日）
├── monitor/                    # 监控周报
├── crontab-rating.conf         # 三任务 cron 配置（本文件配套）
└── runbook.md
```

## 1. 定时任务一览（cron 可见）

| # | 任务 | cron（Asia/Shanghai） | 包装脚本 | 核心命令 |
|---|------|----------------------|----------|----------|
| 1 | 每日结算 | `30 0 * * *` | `run-daily-settlement.sh` | `rating-settler.py` |
| 2 | 月末聚合 | `15 1 28-31 * *`（守卫：当月最后一天） | `run-monthly-aggregation.sh` | `rating-aggregator.py` |
| 3 | 季度人评触发 | `15 2 29-31 3,6,9,12 *`（守卫：季末最后3天） | `run-quarterly-review.sh` | `review-scheduler.sh --quarterly` |

Multica 侧实现为 3 个 autopilot（schedule trigger，create_issue 模式），派发 issue 给 DevOps自动化工程师。

```bash
multica autopilot list --output json          # 可见全部 autopilot（含本三任务）
multica autopilot get <id> --output json      # 单任务详情 + trigger
multica autopilot runs <id> --output json     # 执行历史/失败原因
```

## 2. 手动触发

```bash
multica autopilot trigger <id> --output json   # 手动触发一次（验收标准：手动触发成功）
multica autopilot runs <id> --output json      # 等待 run 完成，确认 status=success
```

手动触发与自动触发等价：执行同一包装脚本、写同一日志、结果一致（幂等）。

## 3. 告警与 SLA

### 告警降级路径（与 SRE 对齐口径）
- **L1 脚本失败**（包装脚本退出码非 0）：运行 agent 在本 job issue 评论告警，并创建 `评分定时任务失败` issue（P1，assignee=SRE稳定性工程师，@SRE）；
- **L2 24h 未处置**：升级资深战略领导者（escalated 项 SLA 48h 内完成升级）；
- **L3 静默失火**（该日应有 run 但无日志/无 run）：每日监控（门禁 SLA 监控 autopilot + 本 runbook 第 6 节周检）发现后补触发并告警——**静默 = 故障**。

### 失败判定
| 信号 | 判定 |
|------|------|
| 包装脚本退出码非 0 | 失败 → L1 |
| 当日无日志文件 / autopilot runs 无该时段 run | 静默失火 → L3 |
| 结算 escalated 数量突增 / pending 滞留 >48h | 风险 → 周报 + 告警 |

## 4. 幂等判定（手动重跑 vs 自动触发）

对齐口径（DevOps 提议，SRE 验收确认）：
1. **定义**：同一任务的「手动重跑」与「自动触发」视为同一逻辑执行单元；两者交错运行不产生重复积分/重复报告。
2. **结算器**：事件按 `pending→结算中→credited` 状态机流转；重复运行只处理仍为 `pending` 的流水，已 `credited` 触发 `E_DUP` 跳过。
3. **聚合器**：月度/季度报告为事件流水的纯函数，每次从零重算并覆盖，输入不变则输出一致（无变化跳过，不累计、不双计）。
4. **人评触发**：季度表单仅在不存在时生成（`[ ! -f ]` 守卫），重复运行 no-op。
5. **验证**：对同一输入两次运行输出 diff 为空即为幂等（见第 5 节复验命令）。

## 5. 调度器 R-42 类别解析复验（KA-43 / B1 验收）

```bash
cd <生产路径>
bash agents/capability-system/tests/test-review-scheduler-category.sh
# 期望：验收点 1（9 目标 == R-42）/ 2（幂等）/ 3（无回归）/ 4（CLI 回退）全部通过
python3 agents/capability-system/tests/test-rating-aggregator.py
# 期望：15/15 通过
```

## 6. 监控与周报

- 周检：`monitor/` 下按周输出 `monitor-report-YYYY-Wxx.md`，内容：三任务 on-time 执行率、结算失败数、escalated 数、pending 滞留分布、**流水完整性**。
- 指标口径：on-time 执行率 = 按 cron 计划窗口内完成数 / 应执行数（目标 >99%，对应月错误预算 ≈1 次失火）。
- **流水完整性**（SRE 建议，周检必查）：`python3 scripts/audit-events.py --month <YYYY-MM>` —— 期望 **跨文件重复 issue = 0**、未知智能体行维持仅「未分配 issue」清单。若出现重复 → 立即 `--reconcile` 并复盘归属。
- **L3 静默失火显式检查**：每日核验「三任务当日日志存在 + 当窗口有 autopilot run」（门禁 SLA 监控 autopilot 中显式列出），缺失即补触发 + 告警（静默 = 故障）。
- **失火复盘**：>99% on-time 对应月错误预算约 1 次失火——**当月 ≥1 次失火即触发 blameless 复盘**（与 L3「静默=故障」口径一致）。
- 月检：与月末聚合同步复核月度/季度报告完整性。

## 7. 流水完整性对账（F1/F2 修复后口径）

```bash
# 审计（只读）：跨文件重复 / 未知智能体归属
python3 scripts/audit-events.py --month <YYYY-MM>
# 修复（先备份到 logs/reconcile-backup-*）：删除错误方重复、迁移可归属行
python3 scripts/audit-events.py --month <YYYY-MM> --reconcile
```

- **归属口径**：仅按 `issue.assignee_id`（与 `rating-settler.py` 一致）；未分配 issue 的自评事件保留在「未知智能体」待人工归属，**不回退 creator**（防误归他人）。
- 结算器已修复：`load_agents()` 优先实时 `multica agent list`（不再信任 `/tmp` 陈旧缓存）；`append_to_events()` 跨文件全局去重（同一 issue 不得写入多个智能体流水）。

## 8. 故障处置示例

```bash
# 结算失败：先看日志
tail -50 <生产路径>/logs/settlement/$(date +%Y-%m-%d).log
# 手动补跑（幂等，安全）
bash <生产路径>/scripts/run-daily-settlement.sh
# 触发失败时创建告警 issue（@SRE），24h 未处置升级资深战略领导者
```

---
*由 DevOps自动化工程师部署维护 · P0-3/KA-18*
