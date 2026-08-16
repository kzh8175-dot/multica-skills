【定时任务 · 季度人评触发】评分系统（方案C）季度人评表单生成。

## 生产路径
/Users/kzh/multica_workspaces_desktop-api.multica.ai/e3ad92f3-ad8e-4eba-bce9-3e670bc345a3/prod/rating-system/

## 执行步骤
1. 运行包装脚本（内含季度末窗口守卫：非季末月最后 3 天自动 skip，exit 0）：
   bash scripts/run-quarterly-review.sh
2. 若输出「非季度末窗口…跳过」：评论一行说明并完成（幂等 no-op）。
3. 若执行（退出码 0 = 成功）：读取当日日志 `logs/review/$(date +%Y-%m-%d).log` 汇总（本季度标签、生成的表单数、总览文件路径），在评论汇报。
4. 退出码非 0 = 失败：在评论告警，创建「评分定时任务失败 · 人评触发」issue（P1，@SRE稳定性工程师），按 runbook 升级路径（24h → 资深战略领导者，SLA 48h）。

## 验收口径
- 幂等：已存在的季度表单不再生成（`[ ! -f ]` 守卫）；可安全重跑。
- 汇报后附【自评】并更新能力档案。
