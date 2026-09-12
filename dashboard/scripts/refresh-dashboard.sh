#!/bin/bash
# 看板数据刷新包装脚本（KA-104 · 生产部署）
#   - 幂等：generate-dashboard-data.py 消费 dashboard-data-feed.py（只读），
#     同输入必得同输出；重复运行仅刷新 generatedAt / 实时运行态计数
#   - 数据源：<WORKSPACE>/prod/rating-system/agents（评分系统生产树，唯一口径）
#     + `multica` CLI 的类别(R-42)/预算/rating.status，经 cache/cli-snapshot.json
#       快照兜底（KA-355）—— CLI 抖动不再改变产出
#   - 日志：输出同时写入 logs/dashboard/YYYY-MM-DD.log
#   - 失败：退出码非 0，由调度 agent 按 runbook 告警
#       0 = 正常
#       2 = 参数/依赖缺失
#       3 = CLI 数据源不可用或快照超龄（**不落盘**，保留上一次正确产物）
set -uo pipefail

# 运行侧超时前置（KA-333 经验固化，KA-338 / A-3）:
#   把 CLI 调用的超时容忍度前移为运行侧默认项。KA-333 已归档其**失效条件**：
#   仅在平台健康时有效；平台整体降级时仍会失败 —— 那种场景由快照兜底 + 退出码 3 告警。
export MULTICA_HTTP_TIMEOUT="${MULTICA_HTTP_TIMEOUT:-60}"

DASH_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROD_RATING_ROOT="${DASH_ROOT}/../rating-system"
JOB="dashboard"
LOG_DIR="$DASH_ROOT/logs/$JOB"
SNAPSHOT="$DASH_ROOT/cache/cli-snapshot.json"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d).log"

stamp() { echo "$(date '+%Y-%m-%d %H:%M:%S %Z') $*"; }

{
  stamp "=== 看板数据刷新 start ==="
  cd "$DASH_ROOT" || exit 1
  python3 generate-dashboard-data.py \
    --prod-root "$PROD_RATING_ROOT" \
    --feed-script "$DASH_ROOT/dashboard-data-feed.py" \
    --cli-snapshot "$SNAPSHOT" \
    --out "$DASH_ROOT/dashboard-data.js"
  rc=$?
  stamp "=== 看板数据刷新 exit=$rc ==="
  exit $rc
} 2>&1 | tee -a "$LOG_FILE"
rc=${PIPESTATUS[0]:-1}
exit $rc
