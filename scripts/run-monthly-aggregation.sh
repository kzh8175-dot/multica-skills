#!/bin/bash
# 月末聚合包装脚本（P0-3）
#   - 守卫：仅当月最后一天执行；其他日期 exit 0（skip 记入日志，幂等无副作用）
#   - 幂等：聚合器输出为事件流水的纯函数，重复运行结果一致（无变化跳过）
#   - 日志：logs/aggregation/YYYY-MM-DD.log
set -uo pipefail

PROD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JOB="aggregation"
LOG_DIR="$PROD_ROOT/logs/$JOB"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d).log"

stamp() { echo "$(date '+%Y-%m-%d %H:%M:%S %Z') $*"; }

# 当月最后一天（macOS / Linux 兼容，与 review-scheduler.sh 同款写法）
if date -j -v+1m -v-1d -f "%Y-%m-%d" "$(date +%Y-%m-01)" +"%d" >/dev/null 2>&1; then
    LAST_DAY=$(date -j -v+1m -v-1d -f "%Y-%m-%d" "$(date +%Y-%m-01)" +"%d")
else
    LAST_DAY=$(date -d "$(date +%Y-%m-01) +1 month -1 day" +"%d")
fi
DAY_OF_MONTH=$(date +%d)

if [ "${DAY_OF_MONTH#0}" -lt "${LAST_DAY#0}" ]; then
    stamp "非月末（今天 $DAY_OF_MONTH/$LAST_DAY），跳过聚合（幂等 no-op）" >> "$LOG_FILE"
    exit 0
fi

{
  stamp "=== 月末聚合 start（今天 = 当月最后一天 $LAST_DAY）==="
  cd "$PROD_ROOT" || exit 1
  python3 agents/capability-system/rating-aggregator.py
  rc=$?
  stamp "=== 月末聚合 exit=$rc ==="
  exit $rc
} 2>&1 | tee -a "$LOG_FILE"
rc=${PIPESTATUS[0]:-1}
exit $rc
