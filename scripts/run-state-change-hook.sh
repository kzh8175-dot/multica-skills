#!/bin/bash
# 状态变更钩子包装脚本（P2-11 / KA-76）
#   - 运行时机：每日结算前（cron 00:20 或并入 run-daily-settlement.sh 的结算器之前）
#   - 职责：检测任务 完成/失败/返工 状态变更 → 自动写事件 metadata（rating.status=pending）
#   - 幂等：rating.last_status 状态跟踪 + 结算器 (issue,事件) 去重，重复运行 no-op
#   - 首次运行自动建立 baseline（只记录状态，不写事件），存量 done/cancelled 不触发
#   - 日志：输出同时写入 logs/hook/YYYY-MM-DD.log
#   - 失败：退出码非 0，由调度 agent 按 runbook 告警
set -uo pipefail

PROD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JOB="hook"
LOG_DIR="$PROD_ROOT/logs/$JOB"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d).log"

stamp() { echo "$(date '+%Y-%m-%d %H:%M:%S %Z') $*"; }

{
  stamp "=== 状态变更钩子 start ==="
  cd "$PROD_ROOT" || exit 1
  python3 agents/capability-system/state-change-hook.py
  rc=$?
  stamp "=== 状态变更钩子 exit=$rc ==="
  exit $rc
} 2>&1 | tee -a "$LOG_FILE"
rc=${PIPESTATUS[0]:-1}
exit $rc
