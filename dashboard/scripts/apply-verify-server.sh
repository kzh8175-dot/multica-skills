#!/bin/bash
# ============================================================
# apply-verify-server.sh — 公网服务器侧应用 + 就地校验
#
# 在公网服务器（阿里云 43.108.86.63）上通过 Workbench 运行，
# 覆盖 dashboard-data.js 并就地校验 SHA256 / generatedAt / 内容指纹。
#
# 用法（在服务器 dashboard 目录下执行）：
#   bash apply-verify-server.sh /path/to/upload/dashboard-data.js [manifest.json]
#
# 前提：先把新 dashboard-data.js（和 dashboard-manifest.json）
#       上传到服务器某目录（如 /tmp/dashboard-sync/）
# ============================================================
set -uo pipefail

SRC_FILE="${1:?用法: apply-verify-server.sh <新dashboard-data.js> [manifest.json]}"
MANIFEST="${2:-$(dirname "$SRC_FILE")/dashboard-manifest.json}"

# 服务器上 dashboard 的部署目录——按实际修改
DEST_DIR="${DEST_DIR:-$PWD}"
DEST="$DEST_DIR/dashboard-data.js"

[[ -f "$SRC_FILE" ]] || { echo "❌ 找不到源文件: $SRC_FILE"; exit 1; }
[[ -f "$DEST" ]] && cp "$DEST" "$DEST.bak-$(date +%Y%m%d-%H%M%S)" && echo "✓ 旧文件已备份"

cp "$SRC_FILE" "$DEST"
echo "✓ 已写入: $DEST"

sha_new=$(shasum -a 256 "$DEST" | awk '{print $1}')
gen_new=$(grep -oE '"generatedAt": *"[^"]*"' "$DEST" | head -1 | sed -E 's/.*"generatedAt": *"([^"]*)".*/\1/')

# 从 manifest 取期望值（若有）
sha_exp=""; gen_exp=""
if [[ -f "$MANIFEST" ]]; then
  sha_exp=$(python3 -c "import json;print(json.load(open('$MANIFEST'))['sha256'])" 2>/dev/null || true)
  gen_exp=$(python3 -c "import json;print(json.load(open('$MANIFEST'))['generatedAt'])" 2>/dev/null || true)
fi

echo "---- 就地校验 ----"
echo "  SHA256      实际=$sha_new  期望=$sha_exp  -> $([ -n "$sha_exp" ] && { [ "$sha_new" = "$sha_exp" ] && echo ✅ || echo ❌; } || echo '未比对(无manifest)')"
echo "  generatedAt 实际=$gen_new  期望=$gen_exp  -> $([ -n "$gen_exp" ] && { [ "$gen_new" = "$gen_exp" ] && echo ✅ || echo ❌; } || echo '未比对(无manifest)')"

# 结构自检：未知智能体应为 0（本流程目标）
unk=$(grep -c '未知智能体' "$DEST" || true)
echo "  未知智能体残留数=$unk -> $([ "$unk" = "0" ] && echo ✅ || echo ❌)"

# 静态服务无需重启（python http.server / nginx 读文件即用）。
# 若服务缓存，则重启：
#   launchctl kickstart -k gui/$(id -u)/com.multica.dashboard.http    # launchd
#   systemctl restart nginx                                            # nginx

echo "---- 完成后，在本地跑: publish-dashboard.sh verify ----"
