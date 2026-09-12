#!/bin/bash
# 状态变更钩子包装脚本（P2-11 / KA-76）
#   - 运行时机：每日结算前（cron 00:20 或并入 run-daily-settlement.sh 的结算器之前）
#   - 职责：检测任务 完成/失败/返工 状态变更 → 自动写事件 metadata（rating.status=pending）
#   - 幂等：rating.last_status 状态跟踪 + 结算器 (issue,事件) 去重，重复运行 no-op
#   - 首次运行自动建立 baseline（只记录状态，不写事件），存量 done/cancelled 不触发
#   - 日志：输出同时写入 logs/hook/YYYY-MM-DD.log
#   - 失败：退出码非 0，由调度 agent 按 runbook 告警
set -uo pipefail

# 运行侧超时前置（KA-333 经验固化，KA-338 / A-3；KA-352 补齐）:
#   把 metadata 读写与 CLI 调用的超时容忍度前移为运行侧默认项。
#   本脚本此前遗漏该 export，331 条 issue 全量扫描时 34 条 metadata 读超时 → read-error → exit 1。
#   失效条件（KA-346 / KA-355 已归档）：仅在平台健康时有效，平台整体降级时无效。
export MULTICA_HTTP_TIMEOUT="${MULTICA_HTTP_TIMEOUT:-60}"

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
