#!/usr/bin/env python3
"""audit-events.py — 积分事件流水完整性审计/修复（评分系统方案C）

职责（对应 SRE P0-3 验收 F1/F2 + 周检建议）:
  1. 审计跨文件重复 issue（同一 issue 出现在多个智能体流水 → 聚合双计，F2）
  2. 审计「未知智能体」归属：可解析到真实 assignee/creator 的流水行
  3. `--reconcile` 修复: 未知智能体行迁移到真实智能体；跨文件重复删除错误方

用法:
  python3 scripts/audit-events.py                  # 只审计，不写
  python3 scripts/audit-events.py --reconcile      # 审计 + 修复（先备份）
  python3 scripts/audit-events.py --month 2026-08  # 指定月份
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
EVENTS_DIR = os.path.join(BASE_DIR, "agents", "reviews", "scoring", "events")
UNKNOWN = "未知智能体"
HEADER = ["| 时间 | 任务 | 事件 | 积分 |", "|------|------|------|:---:|"]
ROW_RE = re.compile(r"^\|\s*(\S[^|]*?)\s*\|\s*([0-9a-f-]{36})\s*\|\s*(\S.*?)\s*\|\s*([+-]\d+)\s*\|$")


def run_cli(args):
    try:
        r = subprocess.run(["multica"] + args, capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return None
        return json.loads(r.stdout) if r.stdout.strip() else None
    except Exception:
        return None


def load_agents():
    data = run_cli(["agent", "list", "--output", "json"])
    if not isinstance(data, list):
        return {}
    return {a["id"]: a["name"] for a in data if a.get("id") and a.get("name")}


def parse_rows(path):
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path) as f:
        for line in f:
            m = ROW_RE.match(line.strip())
            if m:
                rows.append({"ts": m.group(1).strip(), "issue": m.group(2),
                             "event": m.group(3).strip(), "points": m.group(4).strip()})
    return rows


def issue_target_agent(issue_id, agents):
    """解析 issue 应归属的智能体。

    仅按系统设计口径 `issue.assignee_id`（与 rating-settler.py 一致）：
    可解析到真实 agent → 返回其名；否则返回 None。
    注意：不回退 creator——未分配 issue 的自评事件无法从 issue 字段判定
    归属，误归 creator 会扭曲他人积分（防失真规则 R-71/R-72 场景）。
    """
    data = run_cli(["issue", "get", issue_id, "--output", "json"])
    if not isinstance(data, dict):
        return None
    aid = data.get("assignee_id")
    if aid and data.get("assignee_type") == "agent" and aid in agents:
        return agents[aid]
    return None


def event_file(agent, month):
    return os.path.join(EVENTS_DIR, agent, f"{month}.md")


def ensure_header(path):
    if not os.path.isfile(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(HEADER[0] + "\n" + HEADER[1] + "\n")


def audit(agents, month, reconcile=False):
    print(f"=== 流水完整性审计 {month}（reconcile={reconcile}）===")
    if not os.path.isdir(EVENTS_DIR):
        print("events 目录不存在"); return

    all_rows = {}  # issue -> [(agent, row)]
    for agent in sorted(os.listdir(EVENTS_DIR)):
        rows = parse_rows(event_file(agent, month))
        for r in rows:
            all_rows.setdefault(r["issue"], []).append((agent, r))

    # 跨文件重复
    dupes = {iss: lst for iss, lst in all_rows.items() if len(lst) > 1}
    unknown_rows = parse_rows(event_file(UNKNOWN, month)) if os.path.isdir(os.path.join(EVENTS_DIR, UNKNOWN)) else []

    print(f"总流水行: {sum(len(v) for v in all_rows.values())}（涉及 {len(all_rows)} 个 issue）")
    print(f"未知智能体行: {len(unknown_rows)}")
    print(f"跨文件重复 issue: {len(dupes)}")
    for iss, lst in dupes.items():
        print(f"  ⚠️  {iss} -> {[a for a, _ in lst]}")

    if not reconcile:
        return

    # ---- 修复 ----
    backup_dir = os.path.join(BASE_DIR, "logs", "reconcile-backup-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(backup_dir, exist_ok=True)
    real_agents = sorted(
        a for a in os.listdir(EVENTS_DIR)
        if a != UNKNOWN and os.path.isdir(os.path.join(EVENTS_DIR, a))
    )

    # 1) 跨文件重复（仅真实 vs 真实）: 保留与 assignee 一致的一侧，删除其它
    fixed_dupes = 0
    for iss, lst in dupes.items():
        if any(a == UNKNOWN for a, _ in lst):
            continue  # 涉及未知智能体的由步骤 2 统一处理
        target = issue_target_agent(iss, agents)
        keep = None
        for agent, row in lst:
            if target is None or agent == target:
                keep = (agent, row)
        if keep is None:
            keep = lst[0]
        for agent, row in lst:
            if (agent, row) == keep:
                continue
            src = event_file(agent, month)
            shutil.copy(src, os.path.join(backup_dir, f"{agent}-{month}.md"))
            lines = [l for l in open(src).readlines()
                     if not (ROW_RE.match(l.strip()) and ROW_RE.match(l.strip()).group(2) == iss)]
            with open(src, "w") as f:
                f.writelines(lines)
            print(f"  🔧 去重: {agent}/{iss} 移除（保留 {keep[0]}）")
            fixed_dupes += 1

    # 2) 未知智能体行：已存在于任一真实文件 → 删未知侧（防双计）；否则可解析 assignee → 迁移；否则保留
    moved = dropped = kept = 0
    unknown_file = event_file(UNKNOWN, month)
    keep_rows = []
    for row in unknown_rows:
        iss = row["issue"]
        exists_real = any(
            any(r["issue"] == iss for r in parse_rows(event_file(a, month)))
            for a in real_agents
        )
        if exists_real:
            dropped += 1
            print(f"  🔧 去重: {UNKNOWN}/{iss} 已存在于真实智能体流水，移除未知侧")
            continue
        target = issue_target_agent(iss, agents)
        if target and target != UNKNOWN:
            ensure_header(event_file(target, month))
            shutil.copy(event_file(target, month), os.path.join(backup_dir, f"{target}-{month}.md"))
            with open(event_file(target, month), "a") as f:
                f.write(f"| {row['ts']} | {iss} | {row['event']} | {row['points']} |\n")
            moved += 1
            print(f"  🔧 迁移: {UNKNOWN}/{iss} → {target}")
        else:
            keep_rows.append(row)
            kept += 1
            print(f"  ℹ️  保留未知: {iss}（无可解析 assignee，留待人工归属）")

    # 重写未知智能体文件
    if moved or dropped or fixed_dupes:
        os.makedirs(os.path.join(EVENTS_DIR, UNKNOWN), exist_ok=True)
        with open(unknown_file, "w") as f:
            f.write(HEADER[0] + "\n" + HEADER[1] + "\n")
            for row in keep_rows:
                f.write(f"| {row['ts']} | {row['issue']} | {row['event']} | {row['points']} |\n")
    print(f"  迁移 {moved} / 未知侧去重 {dropped} / 保留未知 {kept} / 真实间重复修复 {fixed_dupes}")
    print(f"  备份目录: {backup_dir}")


def main():
    parser = argparse.ArgumentParser(description="积分事件流水完整性审计/修复")
    parser.add_argument("--reconcile", action="store_true", help="修复（先备份到 logs/reconcile-backup-*）")
    parser.add_argument("--month", default=datetime.now().strftime("%Y-%m"), help="月份 YYYY-MM")
    args = parser.parse_args()
    agents = load_agents()
    if not agents:
        print("❌ 无法加载 multica agent list，中止")
        sys.exit(1)
    audit(agents, args.month, reconcile=args.reconcile)


if __name__ == "__main__":
    main()
