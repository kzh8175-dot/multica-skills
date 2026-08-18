#!/bin/bash
# ============================================================
# auto-pull-dashboard.sh — 服务器 /opt/dashboard 看板数据自动拉取（幂等）
#
# 从 multica-skills 仓库 main 拉取 dashboard-data.js，仅当 SHA256 变化时
# 覆盖（覆盖前自动备份可回滚）。由 cron 每 5 分钟调用，或手动执行。
#
# 用法:
#   bash auto-pull-dashboard.sh            # 默认部署目录 /opt/dashboard
#   DEST_DIR=/路径 bash auto-pull-dashboard.sh
#
# 幂等: 数据已最新时仅输出状态，不写文件；失败不覆盖旧文件。
# 配套: install-server-auto-pull.sh（一次性安装 cron）
# ============================================================
set -uo pipefail

DEST_DIR="${DEST_DIR:-/opt/dashboard}"
SRC_URL="https://raw.githubusercontent.com/kzh8175-dot/multica-skills/main/dashboard/dashboard-data.js"
TMP_FILE="$DEST_DIR/dashboard-data.js.new"

[[ -d "$DEST_DIR" ]] || { echo "❌ 部署目录不存在: $DEST_DIR"; exit 1; }

# 1. 拉取候选文件（失败不覆盖旧文件）
curl -fsSL -o "$TMP_FILE" "$SRC_URL" || { echo "❌ 拉取失败（curl 非零）"; exit 1; }

NEW_SHA=$(shasum -a 256 "$TMP_FILE" | awk '{print $1}')
CUR_SHA=$(shasum -a 256 "$DEST_DIR/dashboard-data.js" 2>/dev/null | awk '{print $1}')

# 2. 幂等：已最新则清理临时文件并退出
if [[ "$CUR_SHA" == "$NEW_SHA" ]]; then
  rm -f "$TMP_FILE"
  echo "✓ 数据已是最新（SHA256 $CUR_SHA）"
  exit 0
fi

# 3. 有变化：备份旧文件 → 覆盖
BAK="$DEST_DIR/dashboard-data.js.bak-$(date +%Y%m%d%H%M%S)"
cp -f "$DEST_DIR/dashboard-data.js" "$BAK"
mv -f "$TMP_FILE" "$DEST_DIR/dashboard-data.js"
echo "✅ 已更新 dashboard-data.js: ${CUR_SHA:-无} → $NEW_SHA（备份 $BAK）"
shasum -a 256 "$DEST_DIR/dashboard-data.js"
