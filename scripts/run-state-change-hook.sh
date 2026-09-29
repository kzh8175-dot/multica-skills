#!/bin/bash
# 状态变更钩子包装脚本（P2-11 / KA-76）
#   - 运行时机：每日结算前（cron 00:20 或并入 run-daily-settlement.sh 的结算器之前）
#   - 职责：检测任务 完成/失败/返工 状态变更 → 自动写事件 metadata（rating.status=pending）
#   - 幂等：rating.last_status 状态跟踪 + 结算器 (issue,事件) 去重，重复运行 no-op
#   - 首次运行自动建立 baseline（只记录状态，不写事件），存量 done/cancelled 不触发
#   - 日志：输出同时写入 logs/hook/YYYY-MM-DD.log
#   - 失败：退出码非 0，由调度 agent 按 runbook 告警
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
JOB="hook"
LOG_DIR="$PROD_ROOT/logs/$JOB"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d).log"

stamp() { echo "$(date '+%Y-%m-%d %H:%M:%S %Z') $*"; }

{
  stamp "=== 状态变更钩子 start ==="
  # A9 留痕：把生效值写进本 job 日志，使「环境含该变量」可由日志复核，
  # 而不必回读脚本（SLI-6 同款口径：缓解措施不得静默生效）。
  stamp "  A9 连接层止血生效: GODEBUG=$GODEBUG"
  cd "$PROD_ROOT" || exit 1
  python3 agents/capability-system/state-change-hook.py
  rc=$?
  stamp "=== 状态变更钩子 exit=$rc ==="
  exit $rc
} 2>&1 | tee -a "$LOG_FILE"
rc=${PIPESTATUS[0]:-1}
exit $rc
