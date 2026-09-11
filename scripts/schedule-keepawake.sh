#!/bin/bash
# ============================================================
# schedule-keepawake.sh — 调度窗口保活（KA-338 / A-3 本机侧缓解）
#
# 背景（KA-338 根因占比表）: 2026-09-05 → 09-11 六条日更链路 20/34 失败，
# 其中 12 次是 `runtime unavailable while task was queued` / `runtime went
# offline` —— 任务排队期间本机 runtime 不在线。对账 pmset 日志得到直接证据：
#
#   09-05  166 次 Sleep 记录  电量 2-3%
#   09-06   75 次 Sleep 记录  电量 1-2%
#   09-07    0 次 Sleep 记录  电量 1%（当日 0 成功，实为休眠/关机）
#   09-09   28 次            'Low Power Sleep' 13572s → Wake from Hibernate，电量 1%
#   09-10    7 次            接入电源后当日 5/5 成功
#   09-11    1 次            AC 供电，当日 5/5 成功
#
# 失败日的共同特征：**电池供电 + 极低电量 + 低电量休眠（Low Power Sleep /
# Hibernate）**；成功日共同特征：**接入 AC 或电量充足**。
#
# 本脚本能做的（软件层，尽力而为）:
#   在调度窗口内持 caffeinate 断言，阻止 idle / disk / system sleep。
# 本脚本**做不到**的（必须人工/电源层）:
#   电池耗尽时的 Low Power Sleep / hibernate 是硬件保护，任何 caffeinate
#   都拦不住（09-09 13:32 那次 13572s 休眠即为此）。因此在窗口开始前如果
#   检测到「未接 AC 且电量偏低」，脚本会显式告警并把该窗口标记为高风险——
#   而不是静默地"以为保活了"。
#
# 用法:
#   bash schedule-keepawake.sh --window nightly     # 00:10–03:10（钩子/看板/同步）
#   bash schedule-keepawake.sh --window evening     # 18:30–21:00（上传/门禁）
#   bash schedule-keepawake.sh --window weekly      # 周一 09:20–10:10（预算对账）
#   bash schedule-keepawake.sh --preflight          # 只体检不保活（供 SLO 守卫调用）
#
# 退出码: 0=已在保活或体检通过  1=高风险（未接 AC 且电量低）——调用方应告警
# ============================================================
set -uo pipefail

MIN_BATTERY_PCT="${MIN_BATTERY_PCT:-25}"
STATE_DIR="${MULTICA_SLO_GUARD_STATE_DIR:-$HOME/.multica}"
LOG_DIR="$STATE_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/keepawake-$(date +%Y-%m-%d).log"
PID_FILE="$STATE_DIR/keepawake.pid"

stamp() { echo "$(date '+%Y-%m-%d %H:%M:%S %Z') $*" | tee -a "$LOG_FILE"; }

# ---------------------------------------------------------------- 电源体检
power_report() {
  # 输出: <AC|BATT> <百分比>
  local raw pct src
  raw="$(pmset -g batt 2>/dev/null | tail -n +2 | head -1)"
  pct="$(printf '%s' "$raw" | grep -oE '[0-9]+%' | head -1 | tr -d '%')"
  case "$raw" in
    *"AC Power"*) src="AC" ;;
    *)            src="BATT" ;;
  esac
  echo "${src:-UNKNOWN} ${pct:-?}"
}

preflight() {
  local src pct rc=0
  read -r src pct <<<"$(power_report)"
  stamp "电源体检: source=$src battery=${pct}% 阈值=${MIN_BATTERY_PCT}%"
  if [[ "$src" == "BATT" && "$pct" != "?" && "$pct" -lt "$MIN_BATTERY_PCT" ]]; then
    stamp "⚠ 高风险：电池供电且电量 ${pct}% < ${MIN_BATTERY_PCT}% —— 低电量休眠将吞掉本窗口，"
    stamp "  caffeinate 无法阻止 Low Power Sleep / hibernate。请接入 AC 电源。"
    rc=1
  fi
  # 低电量休眠设置本身也是风险因子
  if pmset -g custom 2>/dev/null | sed -n '/^Battery Power:/,/^AC Power:/p' | grep -qE '^\s*standby\s+1'; then
    stamp "ℹ 电池 standby=1（待机休眠开启）。若无法常接 AC，可评估：sudo pmset -b standby 0 hibernatemode 0"
  fi
  return $rc
}

# ---------------------------------------------------------------- 保活
start_keepawake() {
  local seconds="$1" tag="$2"
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    stamp "⏭ 已有保活进程 $(cat "$PID_FILE")，no-op（幂等）"
    return 0
  fi
  # -i 阻止 idle sleep，-m 阻止 disk sleep，-s 阻止 system sleep（AC 下生效）
  # 不用 -u（会点亮屏幕），避免夜间无谓唤醒显示器
  nohup caffeinate -i -m -s -t "$seconds" >/dev/null 2>&1 &
  echo $! > "$PID_FILE"
  stamp "✓ 保活已启动（$tag，${seconds}s，pid $(cat "$PID_FILE")）"
}

stop_keepawake() {
  if [[ -f "$PID_FILE" ]]; then
    local p; p="$(cat "$PID_FILE")"
    kill "$p" 2>/dev/null && stamp "保活已停止（pid $p）" || stamp "保活进程 $p 已不在"
    rm -f "$PID_FILE"
  else
    stamp "无保活进程（no-op）"
  fi
}

status_keepawake() {
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    stamp "保活中：pid $(cat "$PID_FILE")"
    ps -p "$(cat "$PID_FILE")" -o pid=,etime=,command= | tee -a "$LOG_FILE"
  else
    stamp "未保活"
  fi
}

# ---------------------------------------------------------------- main
WINDOW=""; ACTION="start"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --window)    WINDOW="${2:-}"; shift 2 ;;
    --preflight) ACTION="preflight"; shift ;;
    --stop)      ACTION="stop"; shift ;;
    --status)    ACTION="status"; shift ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
done

if [[ "$ACTION" == "stop" ]];    then stop_keepawake;    exit 0; fi
if [[ "$ACTION" == "status" ]];  then status_keepawake;  exit 0; fi
if [[ "$ACTION" == "preflight" ]]; then preflight; exit $?; fi

case "$WINDOW" in
  nightly) SECS=$((3 * 3600)); TAG="nightly 00:10–03:10" ;;   # 钩子00:20 / 看板01:45 / 同步01:50
  evening) SECS=$((2 * 3600 + 1800)); TAG="evening 18:30–21:00" ;; # 上传18:45 / 门禁20:23
  weekly)  SECS=$((50 * 60)); TAG="weekly Mon 09:20–10:10" ;;  # 预算对账 周一09:37
  *) echo "用法: $0 --window nightly|evening|weekly | --preflight | --stop | --status" >&2; exit 2 ;;
esac

preflight
pre_rc=$?
start_keepawake "$SECS" "$TAG"
exit $pre_rc
