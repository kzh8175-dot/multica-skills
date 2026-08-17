#!/bin/bash
# 看板数据刷新包装脚本（KA-104 · 生产部署）
#   - 幂等：generate-dashboard-data.py 消费 dashboard-data-feed.py（只读、确定性），
#     同输入必得同输出；重复运行仅刷新 generatedAt / 实时运行态计数
#   - 数据源：<WORKSPACE>/prod/rating-system/agents（评分系统生产树，唯一口径）
#   - 日志：输出同时写入 logs/dashboard/YYYY-MM-DD.log
#   - 失败：退出码非 0，由调度 agent 按 runbook 告警
set -uo pipefail

DASH_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROD_RATING_ROOT="${DASH_ROOT}/../rating-system"
JOB="dashboard"
LOG_DIR="$DASH_ROOT/logs/$JOB"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d).log"

stamp() { echo "$(date '+%Y-%m-%d %H:%M:%S %Z') $*"; }

{
  stamp "=== 看板数据刷新 start ==="
  cd "$DASH_ROOT" || exit 1
  python3 generate-dashboard-data.py \
    --prod-root "$PROD_RATING_ROOT" \
    --feed-script "$DASH_ROOT/dashboard-data-feed.py" \
    --out "$DASH_ROOT/dashboard-data.js"
  rc=$?
  stamp "=== 看板数据刷新 exit=$rc ==="
  exit $rc
} 2>&1 | tee -a "$LOG_FILE"
rc=${PIPESTATUS[0]:-1}
exit $rc
