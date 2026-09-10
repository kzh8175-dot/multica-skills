#!/bin/bash
# ============================================================
# ensure-prod-tree.sh — 看板生产树健康检查 + 自愈物化（幂等）
#
# 背景: workspace 级 `<WORKSPACE>/prod/` 会周期性地整体缺失（已复现 6 次:
#   KA-213 / KA-223 / KA-254 / KA-277 / KA-318 / KA-334）。缺失时
#   `prod/dashboard/scripts/refresh-dashboard.sh` 不存在，每日 01:45 刷新
#   任务直接失败，公网 :8080 看板回落为目录列表（404 首页）。
#
# 本脚本把「重建」从人工步骤变成确定性步骤：检查 → 缺什么补什么 → 复验。
#   - 幂等: 生产树健康时 no-op，仅打印状态，不写任何文件
#   - 只读平台: 仅从 git 远端拉取，不触碰 Multica 平台数据
#   - 保留日志: 重建 dashboard 时不动 logs/（历史刷新日志不丢）
#   - 失败显式: 任一环节失败退出码非 0，由调度 agent 告警
#
# 用法:
#   bash ensure-prod-tree.sh                 # PROD_ROOT=<WORKSPACE>/prod
#   PROD_ROOT=/路径 bash ensure-prod-tree.sh
#
# 退出码: 0=健康（含刚重建成功） 1=重建失败
# ============================================================
set -uo pipefail

# PROD_ROOT 推导顺序（脚本本体在仓库内，故需兼容两种落点）:
#   ① 环境变量显式传入（推荐，runbook / autopilot 用）
#   ② <script_dir>/../../prod   —— 脚本被放到 <PROD_ROOT>/dashboard/scripts/ 时
#   ③ <script_dir>/../../../prod —— 脚本在仓库 <repo>/dashboard/scripts/ 时
if [[ -z "${PROD_ROOT:-}" ]]; then
  for cand in "$(dirname "${BASH_SOURCE[0]}")/../../prod" \
              "$(dirname "${BASH_SOURCE[0]}")/../../../prod"; do
    if [[ -d "$cand/dashboard" ]]; then PROD_ROOT="$(cd "$cand" && pwd)"; break; fi
  done
fi
[[ -n "${PROD_ROOT:-}" ]] || { echo "❌ 无法推导 PROD_ROOT，请显式传入（例: PROD_ROOT=<WORKSPACE>/prod bash $0）"; exit 1; }

SKILLS_REPO="https://github.com/kzh8175-dot/multica-skills.git"
RATING_REPO="https://github.com/kzh8175-dot/multica-rating-system.git"

DASH_ROOT="$PROD_ROOT/dashboard"
RATING_ROOT="$PROD_ROOT/rating-system"
LOG_DIR="$DASH_ROOT/logs/bootstrap"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d).log"

stamp() { echo "$(date '+%Y-%m-%d %H:%M:%S %Z') $*"; }

# ---------------------------------------------------------------- 健康判据
dashboard_incomplete() {
  [[ -f "$DASH_ROOT/generate-dashboard-data.py" ]] || return 0
  [[ -f "$DASH_ROOT/dashboard-data-feed.py" ]]     || return 0
  [[ -f "$DASH_ROOT/index.html" ]]                 || return 0
  [[ -x "$DASH_ROOT/scripts/refresh-dashboard.sh" ]] || return 0
  return 1
}
rating_incomplete() { [[ -d "$RATING_ROOT/agents" ]] || return 0; return 1; }

# ---------------------------------------------------------------- 物化
restore_dashboard() {
  local tmp; tmp="$(mktemp -d)"
  stamp "→ 重建 dashboard：从 $SKILLS_REPO 拉取"
  git clone --depth 1 "$SKILLS_REPO" "$tmp/skills" 2>&1 || { rm -rf "$tmp"; return 1; }
  mkdir -p "$DASH_ROOT/scripts" "$DASH_ROOT/docs"
  cp "$tmp/skills/dashboard/index.html"                 "$DASH_ROOT/" || { rm -rf "$tmp"; return 1; }
  cp "$tmp/skills/dashboard/generate-dashboard-data.py" "$DASH_ROOT/" || { rm -rf "$tmp"; return 1; }
  cp "$tmp/skills/dashboard/README.md"                  "$DASH_ROOT/" || { rm -rf "$tmp"; return 1; }
  cp "$tmp/skills/dashboard/crontab-dashboard.conf"     "$DASH_ROOT/" || { rm -rf "$tmp"; return 1; }
  # feed 是团队标准只读接口，仓库内位于 src/，生产树要求与 index.html 同目录
  cp "$tmp/skills/src/dashboard-data-feed.py"           "$DASH_ROOT/" || { rm -rf "$tmp"; return 1; }
  cp "$tmp/skills/dashboard/scripts/"*.sh               "$DASH_ROOT/scripts/" || { rm -rf "$tmp"; return 1; }
  cp -R "$tmp/skills/dashboard/docs/."                  "$DASH_ROOT/docs/" || { rm -rf "$tmp"; return 1; }
  chmod +x "$DASH_ROOT/scripts/"*.sh
  rm -rf "$tmp"
  return 0
}

restore_rating() {
  local tmp; tmp="$(mktemp -d)"
  stamp "→ 重建 rating-system：从 $RATING_REPO 拉取"
  git clone --depth 50 "$RATING_REPO" "$tmp/rs" 2>&1 || { rm -rf "$tmp"; return 1; }
  mv "$tmp/rs" "$RATING_ROOT" || { rm -rf "$tmp"; return 1; }
  rm -rf "$tmp"
  return 0
}

# ---------------------------------------------------------------- 主流程
{
  stamp "=== 生产树健康检查 start (PROD_ROOT=$PROD_ROOT) ==="
  mkdir -p "$PROD_ROOT"
  rc=0

  if dashboard_incomplete; then
    stamp "⚠ dashboard 生产树缺件 → 自愈重建"
    restore_dashboard || { stamp "✗ dashboard 重建失败"; rc=1; }
  else
    stamp "✓ dashboard 生产树健康（no-op）"
  fi

  if rating_incomplete; then
    stamp "⚠ rating-system 生产树缺失 → 自愈重建"
    restore_rating || { stamp "✗ rating-system 重建失败"; rc=1; }
  else
    stamp "✓ rating-system 生产树健康（no-op）"
  fi

  # 复验：重建后仍不合判据则视为失败
  if [[ $rc -eq 0 ]]; then
    dashboard_incomplete && { stamp "✗ 复验失败：dashboard 仍缺件"; rc=1; }
    rating_incomplete    && { stamp "✗ 复验失败：rating-system 仍缺失"; rc=1; }
  fi

  stamp "=== 生产树健康检查 exit=$rc ==="
  exit $rc
} 2>&1 | tee -a "$LOG_FILE"
rc=${PIPESTATUS[0]:-1}
exit $rc
