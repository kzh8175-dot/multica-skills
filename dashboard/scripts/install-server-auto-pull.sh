#!/bin/bash
# ============================================================
# install-server-auto-pull.sh — 服务器看板自动同步一次性安装
#
# 在阿里云 Workbench 终端执行一次（KA-155 收尾 + 根治「公网静默滞后」）：
#   1) 立即把公网 dashboard-data.js 同步到 /opt/dashboard（当前待同步数据）
#   2) 安装每 5 分钟自动拉取 cron —— 此后任何「数据同步」交付只要推到
#      multica-skills main，服务器即自动跟随，不再需要任何人工 Workbench 操作
#
# 用法:
#   bash install-server-auto-pull.sh              # 默认部署目录 /opt/dashboard
#   DEST_DIR=/路径 bash install-server-auto-pull.sh
#
# 幂等: 重复执行安全（cron 去重、拉取幂等）。
# 回滚: /opt/dashboard/dashboard-data.js.bak-<ts> 拷回即可。
# ============================================================
set -uo pipefail

DEST_DIR="${DEST_DIR:-/opt/dashboard}"
PULL_SCRIPT="/usr/local/bin/auto-pull-dashboard.sh"

echo "=================================================================="
echo " 看板自动同步安装 · $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo " 部署目录: $DEST_DIR"
echo "=================================================================="

# 0. 前置检查
[[ -d "$DEST_DIR" ]] || { echo "❌ 部署目录不存在: $DEST_DIR"; exit 1; }

# 1. 写入拉取脚本
cat > "$PULL_SCRIPT" <<'PULL'
#!/bin/bash
# auto-pull-dashboard.sh — 从 multica-skills main 拉取看板数据（幂等）
# 由 install-server-auto-pull.sh 安装；也可单独升级本文件。
set -uo pipefail
DEST_DIR="${DEST_DIR:-/opt/dashboard}"
SRC_URL="https://raw.githubusercontent.com/kzh8175-dot/multica-skills/main/dashboard/dashboard-data.js"
TMP_FILE="$DEST_DIR/dashboard-data.js.new"
[[ -d "$DEST_DIR" ]] || { echo "DEST_MISSING"; exit 1; }
curl -fsSL -o "$TMP_FILE" "$SRC_URL" || { echo "PULL_FAIL"; exit 1; }
NEW_SHA=$(shasum -a 256 "$TMP_FILE" | awk '{print $1}')
CUR_SHA=$(shasum -a 256 "$DEST_DIR/dashboard-data.js" 2>/dev/null | awk '{print $1}')
if [[ "$CUR_SHA" == "$NEW_SHA" ]]; then
  rm -f "$TMP_FILE"; echo "ALREADY_LATEST $CUR_SHA"
else
  cp -f "$DEST_DIR/dashboard-data.js" "$DEST_DIR/dashboard-data.js.bak-$(date +%Y%m%d%H%M%S)"
  mv -f "$TMP_FILE" "$DEST_DIR/dashboard-data.js"
  echo "UPDATED ${CUR_SHA:-none} -> $NEW_SHA"
fi
shasum -a 256 "$DEST_DIR/dashboard-data.js"
PULL
chmod +x "$PULL_SCRIPT"

# 2. 立即执行一次（完成当前待同步数据）
echo "== [1/2] 立即拉取 =="
bash "$PULL_SCRIPT" || { echo "❌ 立即拉取失败，请检查网络/curl"; exit 1; }

# 3. 安装 cron（每 5 分钟，幂等去重）
echo "== [2/2] 安装 cron（每 5 分钟） =="
( crontab -l 2>/dev/null | grep -v 'auto-pull-dashboard.sh'; echo '*/5 * * * * /usr/local/bin/auto-pull-dashboard.sh >/dev/null 2>&1' ) | crontab -
crontab -l | grep 'auto-pull-dashboard.sh' || { echo "❌ cron 安装失败"; exit 1; }

echo "=================================================================="
echo " ✅ 已安装自动同步 cron（每 5 分钟）。当前数据已立即同步（SHA256 见上）。"
echo "    此后公网看板自动跟随 multica-skills main，无需再人工 Workbench 部署。"
echo "=================================================================="
