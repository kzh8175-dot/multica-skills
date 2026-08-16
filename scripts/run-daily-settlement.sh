#!/bin/bash
# 每日结算包装脚本（P0-3）
#   - 幂等：rating-settler.py 按状态机流转（pending→credited），重复运行只处理仍未结算的流水
#   - 日志：输出同时写入 logs/settlement/YYYY-MM-DD.log
#   - 失败：退出码非 0，由调度 agent 按 runbook 告警
set -uo pipefail

PROD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JOB="settlement"
LOG_DIR="$PROD_ROOT/logs/$JOB"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d).log"

stamp() { echo "$(date '+%Y-%m-%d %H:%M:%S %Z') $*"; }

{
  stamp "=== 每日结算 start ==="
  cd "$PROD_ROOT" || exit 1
  python3 agents/capability-system/rating-settler.py
  rc=$?
  stamp "=== 每日结算 exit=$rc ==="
  exit $rc
} 2>&1 | tee -a "$LOG_FILE"
rc=${PIPESTATUS[0]:-1}
exit $rc
