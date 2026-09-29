#!/bin/bash
# 季度人评触发包装脚本（P0-3）
#   - 守卫：仅季度末月（3/6/9/12）最后 3 天执行；其他日期 exit 0（skip 记入日志）
#   - 幂等：review-scheduler.sh 对已存在的季度表单不再生成（[ ! -f ] 守卫）
#   - 日志：logs/review/YYYY-MM-DD.log
set -uo pipefail

# ---- KA-453 A9：TLS 连接层止血（GODEBUG=tlsmlkem=0）-------------------------
# 09-28 钩子 write-error 的根因是本机网络路径丢弃大体积 TLS 握手，而该变量是 CLI
# 错误报文**自己**给出的缓解手段：`Retry with the environment variable
# GODEBUG=tlsmlkem=0 set, and keep it set for the CLI and the daemon`。
# 机制：关闭 ML-KEM（X25519MLKEM768，后量子）密钥交换、回退经典 ECDHE，使
# ClientHello 变小。可逆；代价是网络路径修好前失去后量子抗性。
# 范围：环境级，对本脚本派生的**全部** multica CLI 调用同时生效（钩子 / 结算 /
# 聚合 / 人评 / 巡检 / 同步 / 看板），不止钩子的写路径。
# 写法：追加而非覆盖 —— GODEBUG 为逗号分隔多键，Go 运行时对重复键取**最后**一次
# （本机实测：`inittrace=1,inittrace=0` 静默 / `inittrace=0,inittrace=1` 有输出），
# 故追加即确保生效，同时保留外部已设的其它 GODEBUG 键。
# 规格：docs/state-change-hook-slo-spec.md §三-B
export GODEBUG="${GODEBUG:+$GODEBUG,}tlsmlkem=0"

PROD_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
JOB="review"
LOG_DIR="$PROD_ROOT/logs/$JOB"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d).log"

stamp() { echo "$(date '+%Y-%m-%d %H:%M:%S %Z') $*"; }

# 当月最后一天（macOS / Linux 兼容）
if date -j -v+1m -v-1d -f "%Y-%m-%d" "$(date +%Y-%m-01)" +"%d" >/dev/null 2>&1; then
    LAST_DAY=$(date -j -v+1m -v-1d -f "%Y-%m-%d" "$(date +%Y-%m-01)" +"%d")
else
    LAST_DAY=$(date -d "$(date +%Y-%m-01) +1 month -1 day" +"%d")
fi
DAY_OF_MONTH=$((10#$(date +%d)))
CURRENT_MONTH=$((10#$(date +%m)))
QUARTER_MONTHS=(3 6 9 12)

is_quarter_end_window() {
    for m in "${QUARTER_MONTHS[@]}"; do
        [ "$CURRENT_MONTH" -eq "$m" ] || continue
        if [ "$DAY_OF_MONTH" -ge $((LAST_DAY - 2)) ]; then
            return 0
        fi
    done
    return 1
}

if ! is_quarter_end_window; then
    stamp "非季度末窗口（$CURRENT_MONTH 月 $DAY_OF_MONTH/$LAST_DAY 日），跳过季度人评触发（幂等 no-op）" >> "$LOG_FILE"
    exit 0
fi

{
  stamp "=== 季度人评触发 start（季度末窗口内）==="
  cd "$PROD_ROOT" || exit 1
  bash agents/capability-system/review-scheduler.sh --quarterly
  rc=$?
  stamp "=== 季度人评触发 exit=$rc ==="
  exit $rc
} 2>&1 | tee -a "$LOG_FILE"
rc=${PIPESTATUS[0]:-1}
exit $rc
