【定时任务 · 月末聚合】评分系统（方案C）月度/季度聚合。

## 生产路径
/Users/kzh/multica_workspaces_desktop-api.multica.ai/e3ad92f3-ad8e-4eba-bce9-3e670bc345a3/prod/rating-system/

## 执行步骤
1. 运行包装脚本（内含月末守卫：非当月最后一天自动 skip，exit 0）：
   bash scripts/run-monthly-aggregation.sh
2. 若输出「非月末…跳过」：评论一行说明并完成（幂等 no-op，不产生写操作）。
3. 若执行聚合（退出码 0 = 成功）：读取当日日志 `logs/aggregation/$(date +%Y-%m-%d).log` 汇总（聚合月份/季度、月度报告数、季度报告数、写入/无变化跳过），在评论汇报。
4. 退出码非 0 = 失败：在评论告警，创建「评分定时任务失败 · 聚合」issue（P1，@SRE稳定性工程师），按 runbook 升级路径（24h → 资深战略领导者，SLA 48h）。

## 验收口径
- 幂等：聚合输出为事件流水的纯函数，重复运行结果一致（无变化跳过）；可安全重跑。
- 汇报后附【自评】并更新能力档案。
