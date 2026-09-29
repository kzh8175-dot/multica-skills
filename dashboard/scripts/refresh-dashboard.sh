#!/bin/bash
# 看板数据刷新包装脚本（KA-104 · 生产部署）
#   - 幂等：generate-dashboard-data.py 消费 dashboard-data-feed.py（只读、确定性），
#     同输入必得同输出；重复运行仅刷新 generatedAt / 实时运行态计数
#   - 数据源：<WORKSPACE>/prod/rating-system/agents（评分系统生产树，唯一口径）
#   - 日志：输出同时写入 logs/dashboard/YYYY-MM-DD.log
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
