#!/bin/bash
# ============================================================
# install-autopilot-slo-guard.sh — 安装 SLO 守卫与窗口保活的 launchd 任务（KA-338 / A-3）
#
# 生成并（可选）加载 4 个 LaunchAgent：
#   com.multica.slo-guard.check      每 15 分钟跑一次 --check --notify（连续失败/跨链路建单）
#   com.multica.keepawake.nightly    00:10 起保活 3h（钩子 00:20 / 看板 01:45 / 同步 01:50）
#   com.multica.keepawake.evening    18:30 起保活 2.5h（上传 18:45 / 门禁 20:23）
#   com.multica.keepawake.weekly     周一 09:20 起保活 50min（预算对账 09:37）
#
# 默认**只生成不加载**（--load 才 bootstrap）：它会改变本机电源行为（阻止休眠），
# 在电池受限的笔记本上属于需要 owner 拍板的变更。
#
# 用法:
#   bash install-autopilot-slo-guard.sh              # 生成 plist + 打印加载命令
#   bash install-autopilot-slo-guard.sh --load       # 生成并加载
#   bash install-autopilot-slo-guard.sh --unload     # 卸载并删除
#   bash install-autopilot-slo-guard.sh --status     # 查看加载状态
# ============================================================
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AGENT_DIR="$HOME/Library/LaunchAgents"
GUARD="$REPO_ROOT/scripts/autopilot-slo-guard.py"
KEEPAWAKE="$REPO_ROOT/scripts/schedule-keepawake.sh"
STATE_DIR="${MULTICA_SLO_GUARD_STATE_DIR:-$HOME/.multica}"
LOG_DIR="$STATE_DIR/logs"
PY="$(command -v python3 || echo /usr/bin/python3)"
PATH_ENV="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$HOME/.local/bin"

LABELS=(
  "com.multica.slo-guard.check"
  "com.multica.keepawake.nightly"
  "com.multica.keepawake.evening"
  "com.multica.keepawake.weekly"
)

ACTION="generate"
case "${1:-}" in
  --load)   ACTION="load" ;;
  --unload) ACTION="unload" ;;
  --status) ACTION="status" ;;
  "")       ;;
  *) echo "未知参数: $1" >&2; exit 2 ;;
esac

if [[ "$ACTION" == "status" ]]; then
  for l in "${LABELS[@]}"; do
    if launchctl print "gui/$(id -u)/$l" >/dev/null 2>&1; then echo "✓ 已加载 $l"; else echo "— 未加载 $l"; fi
  done
  exit 0
fi

if [[ "$ACTION" == "unload" ]]; then
  for l in "${LABELS[@]}"; do
    launchctl bootout "gui/$(id -u)/$l" 2>/dev/null && echo "已卸载 $l" || echo "（未加载）$l"
    rm -f "$AGENT_DIR/$l.plist"
  done
  exit 0
fi

mkdir -p "$AGENT_DIR" "$LOG_DIR"

_write_plist() {  # $1=label  $2=ProgramArguments 的 XML 片段  $3=StartCalendarInterval/StartInterval 片段
  local label="$1" args="$2" sched="$3"
  cat > "$AGENT_DIR/$label.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$label</string>
  <key>ProgramArguments</key>
  <array>
$args
  </array>
  <key>WorkingDirectory</key><string>$REPO_ROOT</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$PATH_ENV</string>
    <key>MULTICA_SLO_GUARD_STATE_DIR</key><string>$STATE_DIR</string>
  </dict>
  <key>RunAtLoad</key><false/>
$sched
  <key>StandardOutPath</key><string>$LOG_DIR/launchd-$label.out.log</string>
  <key>StandardErrorPath</key><string>$LOG_DIR/launchd-$label.err.log</string>
</dict>
</plist>
PLIST
  plutil -lint "$AGENT_DIR/$label.plist" >/dev/null && echo "✓ 生成并通过 plutil 校验: $label.plist" || {
    echo "✗ plist 校验失败: $label"; return 1; }
}

_write_plist "com.multica.slo-guard.check" \
"    <string>$PY</string>
    <string>$GUARD</string>
    <string>--check</string>
    <string>--notify</string>
    <string>--lookback-hours</string>
    <string>168</string>" \
"  <key>StartInterval</key><integer>900</integer>"

_write_plist "com.multica.keepawake.nightly" \
"    <string>/bin/bash</string>
    <string>$KEEPAWAKE</string>
    <string>--window</string>
    <string>nightly</string>" \
"  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>0</integer><key>Minute</key><integer>10</integer></dict>"

_write_plist "com.multica.keepawake.evening" \
"    <string>/bin/bash</string>
    <string>$KEEPAWAKE</string>
    <string>--window</string>
    <string>evening</string>" \
"  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>18</integer><key>Minute</key><integer>30</integer></dict>"

_write_plist "com.multica.keepawake.weekly" \
"    <string>/bin/bash</string>
    <string>$KEEPAWAKE</string>
    <string>--window</string>
    <string>weekly</string>" \
"  <key>StartCalendarInterval</key>
  <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>20</integer></dict>"

echo
if [[ "$ACTION" == "load" ]]; then
  for l in "${LABELS[@]}"; do
    launchctl bootout "gui/$(id -u)/$l" 2>/dev/null
    launchctl bootstrap "gui/$(id -u)" "$AGENT_DIR/$l.plist" && echo "✓ 已加载 $l" || echo "✗ 加载失败 $l"
  done
  echo
  echo "复核: bash $0 --status"
else
  echo "plist 已生成到 $AGENT_DIR（未加载）。"
  echo "确认要改变本机电源/调度行为后再执行："
  echo "  bash $0 --load"
  echo "回滚："
  echo "  bash $0 --unload"
fi
