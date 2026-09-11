#!/bin/bash
# 每日结算包装脚本（P0-3）
#   - 幂等：rating-settler.py 按状态机流转（pending→credited），重复运行只处理仍未结算的流水
#   - 日志：输出同时写入 logs/settlement/YYYY-MM-DD.log
#   - 失败：退出码非 0，由调度 agent 按 runbook 告警
set -uo pipefail

# 运行侧超时前置（KA-333 经验固化，KA-338 / A-3）:
#   把 metadata 读写与 CLI 调用的超时容忍度从"事后定向重跑补救"前移为运行侧默认项。
#   09-09 状态钩子曾因瞬时超时 exit=1（KA-322）；预设 60s 后 310 次读取 + 11 次写入零超时。
export MULTICA_HTTP_TIMEOUT="${MULTICA_HTTP_TIMEOUT:-60}"

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
