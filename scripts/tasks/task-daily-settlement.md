【定时任务 · 每日结算 00:30】评分系统（方案C）每日结算。

## 生产路径
/Users/kzh/multica_workspaces_desktop-api.multica.ai/e3ad92f3-ad8e-4eba-bce9-3e670bc345a3/prod/rating-system/

## 执行步骤
1. 运行包装脚本（含日志、退出码）：
   bash scripts/run-daily-settlement.sh
2. 退出码 0 = 成功：读取当日日志 `logs/settlement/$(date +%Y-%m-%d).log` 汇总结算结果，在评论汇报：扫描 pending 数 / credited 数 / escalated 数 / 失败数。
3. 退出码非 0 = 失败：在评论告警，并创建「评分定时任务失败 · 结算」issue（P1，assignee=SRE稳定性工程师，@SRE），按 runbook 升级路径：24h 未处置 → 升级资深战略领导者（SLA 48h）。

## 验收口径
- 幂等：结算器按状态机流转（pending→credited），重复运行只处理仍为 pending 的流水；本次运行可安全重跑。
- 汇报后附【自评】并更新能力档案 `agents/profiles/DevOps自动化工程师/capabilities.md`。
