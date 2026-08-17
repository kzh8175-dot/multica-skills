#!/bin/bash
# ============================================================
# publish-dashboard.sh — 看板发布流程（本地侧）
#
# 流程：刷新本地看板 → 生成指纹清单(manifest) → [可选推送公网]
#        → 校验公网 generatedAt / SHA256 / 内容指纹 一致
#
# 用法：
#   publish-dashboard.sh prepare   # 刷新 + 生成 dashboard-manifest.json
#   publish-dashboard.sh push      # 若配置了 DASH_PUSH_URL 则推送到公网
#   publish-dashboard.sh verify    # 拉取公网数据与本地 manifest 比对（PASS/FAIL）
#   publish-dashboard.sh all       # prepare → push(如有) → verify（默认）
#
# 环境变量：
#   DASH_PUBLIC_URL  公网根地址（默认 http://43.108.86.63）
#   DASH_PUSH_URL    可选：公网上传端点（配置后 push 才生效）
#   DASH_PUSH_TOKEN  可选：上传端点鉴权 token
#
# 退出码：0=一致  2=不一致(检测到公网未同步)  其他=执行失败
# ============================================================
set -uo pipefail

DASH_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PUBLIC_URL="${DASH_PUBLIC_URL:-http://43.108.86.63}"
MANIFEST="$DASH_ROOT/dashboard-manifest.json"
DATA_FILE="$DASH_ROOT/dashboard-data.js"
cmd="${1:-all}"

require_manifest() {
  [[ -f "$MANIFEST" ]] || { echo "❌ 缺少 $MANIFEST，请先执行 prepare"; exit 1; }
}

gen_manifest() {
  python3 - "$DATA_FILE" "$MANIFEST" <<'PY'
import json, hashlib, sys, datetime
src, out = sys.argv[1], sys.argv[2]
data = open(src, encoding='utf-8').read()
sha = hashlib.sha256(data.encode('utf-8')).hexdigest()
obj = json.loads(data[data.find('{'):data.rfind('}')+1])
sl = next((a for a in obj['agents'] if a['name'] == '资深战略领导者'), {})
manifest = {
  "schemaVersion": "1.0",
  "generatedAt": obj['meta']['generatedAt'],
  "sha256": sha,
  "sizeBytes": len(data.encode('utf-8')),
  "fingerprint": {
    "agents": len(obj['agents']),
    "agentsWithData": obj['meta'].get('agentsWithData'),
    "events": len(obj['events']),
    "unknownAgentCount": sum(1 for a in obj['agents'] if a['name'] == '未知智能体'),
    "sl_monthTotal": sl.get('monthTotal'),
    "sl_monthPct": sl.get('monthPct'),
    "sl_objective": sl.get('objective'),
  },
  "generatedAtLocal": datetime.datetime.now().isoformat(timespec='seconds'),
}
json.dump(manifest, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
print("✓ manifest 已生成:", manifest['generatedAt'], "sha256=" + sha[:12],
      "unknown=" + str(manifest['fingerprint']['unknownAgentCount']),
      "SL=" + str(manifest['fingerprint']['sl_monthTotal']))
PY
}

if [[ "$cmd" == "prepare" || "$cmd" == "all" ]]; then
  echo "=== [1/3] 刷新本地看板数据 ==="
  "$DASH_ROOT/scripts/refresh-dashboard.sh" >/dev/null || { echo "❌ 刷新失败"; exit 1; }
  gen_manifest || exit 1
fi

if [[ "$cmd" == "push" || "$cmd" == "all" ]]; then
  echo "=== [2/3] 推送公网（可选） ==="
  if [[ -z "${DASH_PUSH_URL:-}" ]]; then
    echo "⚠ DASH_PUSH_URL 未配置 → 跳过推送。"
    echo "  公网需手动覆盖（Workbench 运行 apply-verify-server.sh），或先配置上传端点后启用自动推送。"
  else
    curl -sS -X PUT --data-binary @"$DATA_FILE" \
      -H "X-Sync-Token: ${DASH_PUSH_TOKEN:-}" \
      "$DASH_PUSH_URL" || { echo "❌ 推送失败"; exit 1; }
    echo "✓ 已推送到 $DASH_PUSH_URL"
  fi
fi

if [[ "$cmd" == "verify" || "$cmd" == "all" ]]; then
  echo "=== [3/3] 校验公网一致性 ==="
  require_manifest
  python3 - "$PUBLIC_URL" "$MANIFEST" <<'PY'
import json, hashlib, sys, urllib.request
url, mfile = sys.argv[1], sys.argv[2]
m = json.load(open(mfile, encoding='utf-8'))
try:
    remote = urllib.request.urlopen(url.rstrip('/') + '/dashboard-data.js', timeout=15).read().decode('utf-8')
except Exception as e:
    print("❌ 无法读取公网数据:", e); sys.exit(2)
rsha = hashlib.sha256(remote.encode('utf-8')).hexdigest()
robj = json.loads(remote[remote.find('{'):remote.rfind('}')+1])
r_sl = next((a for a in robj['agents'] if a['name'] == '资深战略领导者'), {})
ok_sha = (rsha == m['sha256'])
ok_gen = (robj['meta']['generatedAt'] == m['generatedAt'])
ok_fp = (len(robj['agents']) == m['fingerprint']['agents']
         and sum(1 for a in robj['agents'] if a['name'] == '未知智能体') == m['fingerprint']['unknownAgentCount']
         and r_sl.get('monthTotal') == m['fingerprint']['sl_monthTotal'])
print(f"  本地 manifest : generatedAt={m['generatedAt']}  sha={m['sha256'][:12]}  agents={m['fingerprint']['agents']}  unknown={m['fingerprint']['unknownAgentCount']}  SL={m['fingerprint']['sl_monthTotal']}")
print(f"  公网 实际数据 : generatedAt={robj['meta']['generatedAt']}  sha={rsha[:12]}  agents={len(robj['agents'])}  unknown={sum(1 for a in robj['agents'] if a['name']=='未知智能体')}  SL={r_sl.get('monthTotal')}")
print("  SHA256 一致      :", "✅" if ok_sha else "❌")
print("  generatedAt 一致 :", "✅" if ok_gen else "❌")
print("  内容指纹一致     :", "✅" if ok_fp else "❌")
if ok_sha and ok_gen and ok_fp:
    print("  ✅ 公网与本地一致，发布完成。")
    sys.exit(0)
else:
    print("  ❌ 公网未同步（存在差异），请执行 apply-verify-server.sh 覆盖后再 verify。")
    sys.exit(2)
PY
fi
