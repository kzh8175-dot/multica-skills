#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
state-change-hook.py — 状态变更钩子（方案C P2-11 / KA-76）

职责: 当任务（issue）状态发生 完成/失败/返工 变更时，自动写入对应积分事件
（R-01 按时完成 / R-02 超时完成 / R-03 未完成失败 / R-04 退回返工），
与结算器（rating-settler.py）/事件流水打通：

  [状态变更] 本脚本检测 transition → 写 5 键 metadata（rating.status=pending）
  [每日结算] rating-settler.py → 事件流水 events/{agent}/YYYY-MM.md（幂等去重）
  [月末聚合] rating-aggregator.py → 月度百分制 / 季度客观分

事件映射（仅自动写 R-01~R-04 确定性状态事件；R-11~R-13 / R-31~R-33 需人评判定，
本钩子不写）:
  → done              R-01 任务按时完成 +20 / R-02 任务超时完成 +10
                      （有 due_date 且完成时间超过 → R-02，否则 R-01；当天完成计按时）
  → cancelled         R-03 任务未完成/失败 -15
                      （from=done 的取消不重复记失败，防双计）
  done/in_review → todo/in_progress
                      R-04 任务被退回返工 -10

权限边界: R-01~R-04 为行为类事件，按 reviewer-guide.md §3.1 模板以 trigger=reviewer
写入；本钩子为 P2-11（资深战略领导者立项）授权的确定性系统自动化（观察任务状态事实
而非智能体自我登记）。已 credited/escalated 的 metadata 不改写事件值；仅当检测到
「新事件」时按评审流写入新事件，旧事件保留在流水（结算器 (issue,事件) 去重防双计）。

幂等:
  - 状态跟踪: 每个 issue 的 rating.last_status 记录上次处理的 status；无变更 → no-op
  - 首次运行自动建立 baseline（只记录 status，不写事件），存量 done/cancelled 不触发
  - --baseline 与 decide() 口径对齐：未知/空 status 与 rating.test=true 的 issue 跳过，不写 baseline
  - 已有 rating.status=pending 的 issue 延后（尊重已有事件，不覆盖；待其结算后补写）
  - 已 credited 且同一事件 → 跳过（结算器 E_DUP 兜底，防双计）
  - 已 escalated → 跳过并报告（升级人工处置，不改写）
  - --dry-run 只读预演，不产生任何写入

退出码契约:
  - 0: 全部处理成功（含正常无事件、dry-run）
  - 1: 汇总含 write-error（写 metadata 失败）或 read-error（读 metadata 失败）时退出 1，
       cron/包装脚本（run-state-change-hook.sh）按「退出码非 0」告警

用法:
  python3 state-change-hook.py                     # 扫描全部 agent 分配 issue
  python3 state-change-hook.py --dry-run           # 预演（不写 metadata）
  python3 state-change-hook.py --issue <id>        # 只处理指定 issue
  python3 state-change-hook.py --baseline          # 全量仅建 baseline（写 rating.last_status），不写事件
  python3 state-change-hook.py --no-auto-baseline  # 缺 baseline 报错跳过（严格）
  python3 state-change-hook.py --json              # 汇总输出 JSON
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

# ---------------------------------------------------------------- 常量

RETURN_FROM = {"done", "in_review"}    # 从这些状态退回 → 返工
RETURN_TO = {"todo", "in_progress"}    # 退回到这些状态 → 返工
VALID_STATUSES = {
    "todo", "in_progress", "in_review", "done",
    "blocked", "backlog", "cancelled",
}

# 与 reviewer-guide.md §4.1 的事件/积分完全对齐
EVENTS = {
    "R-01": {"event": "R-01:任务按时完成", "points": 20},
    "R-02": {"event": "R-02:任务超时完成", "points": 10},
    "R-03": {"event": "R-03:任务未完成/失败", "points": -15},
    "R-04": {"event": "R-04:任务被退回返工", "points": -10},
}
TRIGGER = "reviewer"  # 行为类事件 trigger（P2-11 授权的系统自动化代理评审流）

EVENT_ID_RE = re.compile(r"^(R-\d+)")
ISO_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")

# ---------------------------------------------------------------- 纯函数

def event_id(desc):
    """事件描述 → R-xx 前缀；无法解析时原样返回。"""
    m = EVENT_ID_RE.match(desc or "")
    return m.group(1) if m else (desc or "")


def classify_completion(due_date, completed_at=None):
    """按时/超时判定（R-01 vs R-02）。

    无 due_date → 按时（R-01）；completed_at 缺失 → 按时。
    按日期比较：当天完成（completed_at 的日期 ≤ due_date）计按时。
    """
    if not due_date:
        return "on_time"
    if not completed_at:
        return "on_time"
    comp = str(completed_at)[:10]
    if comp > str(due_date)[:10]:
        return "overdue"
    return "on_time"


def map_transition(from_status, to_status, due_date=None, completed_at=None):
    """状态变更 → 积分事件。返回 {"event","points","trigger"} 或 None（无评分事件）。

    - → done: R-01（按时） / R-02（超时）
    - → cancelled: R-03（from=done 除外，防双计）
    - RETURN_FROM → RETURN_TO: R-04（返工）
    - 其余（in_progress→in_review、→blocked、backlog→todo 等）不写事件
    """
    if to_status == "done":
        ev = EVENTS["R-01"] if classify_completion(due_date, completed_at) == "on_time" \
            else EVENTS["R-02"]
    elif to_status == "cancelled":
        if from_status == "done":
            return None  # 已完成再取消，不重复记失败
        ev = EVENTS["R-03"]
    elif from_status in RETURN_FROM and to_status in RETURN_TO:
        ev = EVENTS["R-04"]
    else:
        return None
    return {"event": ev["event"], "points": ev["points"], "trigger": TRIGGER}


def skip_reason(meta, event):
    """返回跳过/延后原因；None 表示允许写入事件。"""
    status = meta.get("rating.status")
    if status == "pending":
        return "event-pending"          # 已有未结算事件 → 延后，不覆盖
    if status == "escalated":
        return "escalated"              # 升级状态 → 人工处置
    if status == "credited" and event_id(meta.get("rating.event")) == event_id(event["event"]):
        return "credited-same-event"    # 同一事件已入账 → 防双计
    return None


def build_event_metadata(event, occurred_at):
    """按 reviewer-guide §3.1 构建 5 键 metadata（[(key, value, type), ...]）。

    rating.status=pending 由结算器扫描入账；rating.occurred_at 取实际完成时间，
    保证事件归入正确月份。
    """
    return [
        ("rating.trigger", TRIGGER, "string"),
        ("rating.event", event["event"], "string"),
        ("rating.points", str(event["points"]), "number"),
        ("rating.status", "pending", "string"),
        ("rating.occurred_at", occurred_at, "string"),
    ]


def _transition_time(issue):
    """推断状态变更时间：优先 issue.updated_at，缺失/非法回退当前 UTC。"""
    ts = issue.get("updated_at")
    if ts and ISO_TS_RE.match(str(ts)):
        return str(ts)
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def decide(issue, meta, no_auto_baseline=False):
    """决策单个 issue：返回 plan dict（纯函数，无副作用）。

    plan:
      action   baseline / needs-baseline / no-transition / non-scoring /
               event-written / deferred / escalated-blocked / credited-same-event /
               test-skip
      event    {"event","points","trigger"} | None
      updates  [(key, value, vtype), ...] 待写 metadata
      reason   str
    """
    status = issue.get("status") or ""
    if status not in VALID_STATUSES:
        return {"action": "invalid-status", "event": None, "updates": [],
                "reason": f"未知状态 {status!r}"}

    # 测试数据隔离（与结算器 rating.test 口径一致）
    if meta.get("rating.test") is True:
        return {"action": "test-skip", "event": None, "updates": [], "reason": "测试数据"}

    last_status = meta.get("rating.last_status")
    if last_status is None:
        # 自动 baseline：只记录当前状态，不写事件（存量 done/cancelled 不触发）
        if no_auto_baseline:
            return {"action": "needs-baseline", "event": None, "updates": [],
                    "reason": "缺少 rating.last_status baseline"}
        return {"action": "baseline", "event": None,
                "updates": [("rating.last_status", status, "string")],
                "reason": f"建立 baseline {status}"}

    if last_status == status:
        return {"action": "no-transition", "event": None, "updates": [],
                "reason": "状态无变更"}

    # 检测到 transition
    transitioned_at = meta.get("rating.transitioned_at") or _transition_time(issue)
    event = map_transition(last_status, status, issue.get("due_date"), transitioned_at)

    if event is None:
        # 非评分 transition：仅推进状态跟踪
        return {"action": "non-scoring", "event": None,
                "updates": [("rating.last_status", status, "string")],
                "reason": f"{last_status}→{status} 无评分事件"}

    reason = skip_reason(meta, event)
    if reason == "event-pending":
        # 已有 pending 事件 → 延后，不更新 last_status（待 pending 结算后补写）
        updates = []
        if "rating.transitioned_at" not in meta:
            updates.append(("rating.transitioned_at", transitioned_at, "string"))
        return {"action": "deferred", "event": event, "updates": updates,
                "reason": f"{last_status}→{status} 已有 pending 事件，延后"}
    if reason == "escalated":
        return {"action": "escalated-blocked", "event": event, "updates": [],
                "reason": f"{last_status}→{status} 事件 escalated，需人工处置"}
    if reason == "credited-same-event":
        return {"action": "credited-same-event", "event": event,
                "updates": [("rating.last_status", status, "string")],
                "reason": f"{event['event']} 已入账，不重复"}

    # 写事件（5 键）+ 更新 last_status
    event_meta = build_event_metadata(event, transitioned_at)
    updates = list(event_meta)
    updates.append(("rating.last_status", status, "string"))
    return {"action": "event-written", "event": event, "updates": updates,
            "reason": f"{last_status}→{status} → {event['event']}"}


def _baseline_plan(issue, meta):
    """--baseline 模式决策：与 decide() 口径对齐，仅补写缺失的 rating.last_status。

    过滤顺序与 decide() 一致（未知/空 status → 测试数据 → 已有 baseline）：
      - 未知/空 status → invalid-status（跳过，不写）
      - rating.test=true → test-skip（测试数据隔离，不写）
      - 已有 baseline  → already-baselined（不重写）
      - 缺 baseline    → baseline（写 rating.last_status，不写事件）
    """
    status = issue.get("status") or ""
    if status not in VALID_STATUSES:
        return {"action": "invalid-status", "event": None, "updates": [],
                "reason": f"未知状态 {status!r}"}
    if meta.get("rating.test") is True:
        return {"action": "test-skip", "event": None, "updates": [],
                "reason": "测试数据"}
    if "rating.last_status" in meta:
        return {"action": "already-baselined", "event": None, "updates": [],
                "reason": "baseline 已存在"}
    return {"action": "baseline", "event": None,
            "updates": [("rating.last_status", status, "string")],
            "reason": f"建立 baseline {status}"}


# ---------------------------------------------------------------- IO

def run_cli(args):
    """执行 multica CLI，返回 (ok, output)。"""
    try:
        result = subprocess.run(
            ["multica"] + args,
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return False, result.stderr.strip()
        return True, result.stdout
    except Exception as e:
        return False, str(e)


def list_agent_issues():
    """分页列出全部 assignee_type=agent 的 issue。返回 (issues, err)。"""
    all_issues = []
    offset = 0
    page = 100
    while True:
        ok, out = run_cli([
            "issue", "list", "--limit", str(page), "--offset", str(offset),
            "--output", "json",
        ])
        if not ok:
            return None, out
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            return None, "JSON 解析失败"
        if isinstance(data, dict):
            issues = data.get("issues") or []
            has_more = bool(data.get("has_more"))
        elif isinstance(data, list):
            issues = data
            has_more = False
        else:
            return None, "无法解析 issue list 返回"
        all_issues.extend(i for i in issues if i.get("assignee_type") == "agent")
        if not has_more or not issues:
            break
        offset += len(issues)
    return all_issues, None


def get_issue_metadata(issue_id):
    """读取 issue 全部 metadata。返回 (meta_dict, err)。"""
    ok, out = run_cli(["issue", "metadata", "list", issue_id, "--output", "json"])
    if not ok:
        return None, out
    try:
        return json.loads(out), None
    except json.JSONDecodeError:
        return None, "JSON 解析失败"


def set_metadata(issue_id, key, value, vtype="string"):
    """写入单个 metadata 键。返回 (ok, err)。"""
    ok, out = run_cli([
        "issue", "metadata", "set", issue_id,
        "--key", key, "--value", str(value), "--type", vtype, "--output", "json",
    ])
    return ok, (None if ok else out)


def load_agents():
    """agent id → 名称 映射（仅用于展示；失败返回空，不中断）。"""
    try:
        result = subprocess.run(
            ["multica", "agent", "list", "--output", "json"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if isinstance(data, list):
                return {a["id"]: a["name"] for a in data if a.get("id") and a.get("name")}
    except Exception:
        pass
    return {}


# ---------------------------------------------------------------- 处理

def _apply_updates(issue, plan, dry_run=False, write=None):
    """应用 plan['updates'] 到 issue 的 metadata；写失败 → write-error plan。

    write: 注入的写回调 (key, value, vtype) → (ok, err)；None 用真实 set_metadata。
    dry_run: 只读，不应用任何 writes。
    """
    if dry_run or not plan["updates"]:
        return plan
    if write is None:
        write = lambda key, value, vtype: set_metadata(issue["id"], key, value, vtype)
    for key, value, vtype in plan["updates"]:
        ok, err = write(key, value, vtype)
        if not ok:
            return {"action": "write-error", "event": plan["event"], "updates": [],
                    "reason": f"{key} 写入失败: {err}"}
    return plan


def process_issue(issue, meta, dry_run=False, no_auto_baseline=False, write=None):
    """处理单个 issue：decide + 应用 updates。返回 plan（含实际 action）。

    write: 注入的写回调 (key, value, vtype) → (ok, err)；None 用真实 set_metadata。
    dry_run: 只读，不应用任何 writes。
    """
    plan = decide(issue, meta, no_auto_baseline=no_auto_baseline)
    return _apply_updates(issue, plan, dry_run=dry_run, write=write)


def _exit_on_error(stats):
    """写/读失败时退出码=1（cron/包装脚本按非 0 告警）；无错误不调用 exit（契约 exit 0）。"""
    if stats.get("write-error") or stats.get("read-error"):
        sys.exit(1)


# ---------------------------------------------------------------- 主流程

def main():
    parser = argparse.ArgumentParser(description="状态变更钩子（方案C P2-11）")
    parser.add_argument("--dry-run", action="store_true", help="只读预演，不写 metadata")
    parser.add_argument("--issue", help="只处理指定 issue-id")
    parser.add_argument("--baseline", action="store_true",
                        help="全量仅建 baseline（写 rating.last_status），不写事件")
    parser.add_argument("--no-auto-baseline", action="store_true",
                        help="缺少 baseline 的 issue 报错跳过（严格模式）")
    parser.add_argument("--json", action="store_true", help="汇总输出 JSON")
    args = parser.parse_args()

    # 加载 agent 映射（展示用）
    agents = load_agents()

    # 获取 issue 列表
    if args.issue:
        ok, out = run_cli(["issue", "get", args.issue, "--output", "json"])
        if not ok:
            print(f"❌ 获取 issue 失败: {out}")
            sys.exit(1)
        issues = [json.loads(out)]
    else:
        issues, err = list_agent_issues()
        if err:
            print(f"❌ 列出 issue 失败: {err}")
            sys.exit(1)
        if issues is None:
            print("❌ 无返回")
            sys.exit(1)

    if not args.json:
        print("=== 状态变更钩子 (state-change-hook) ===")
        mode = "DRY-RUN" if args.dry_run else ("BASELINE" if args.baseline else "正常")
        print(f"模式: {mode} | 扫描 issue: {len(issues)}")
        print()

    stats = {}
    events_out = []
    for issue in issues:
        ident = issue.get("identifier", issue["id"])
        agent = agents.get(issue.get("assignee_id"), "未知智能体")
        meta, merr = get_issue_metadata(issue["id"])
        if merr or meta is None:
            if not args.json:
                print(f"  ❌ {ident} [{agent}] 读取 metadata 失败: {merr}")
            stats["read-error"] = stats.get("read-error", 0) + 1
            continue

        if args.baseline:
            # baseline 模式：仅补写缺失的 rating.last_status，不写事件；
            # _baseline_plan 与 decide() 口径对齐（invalid-status / 测试数据跳过）
            plan = _baseline_plan(issue, meta)
            # 显式应用 updates（与 process_issue 共用写路径；dry-run 只读）
            plan = _apply_updates(issue, plan, dry_run=args.dry_run)
        else:
            plan = process_issue(issue, meta, dry_run=args.dry_run,
                                 no_auto_baseline=args.no_auto_baseline)

        action = plan["action"]
        stats[action] = stats.get(action, 0) + 1
        event = plan.get("event") or {}
        if action == "event-written":
            events_out.append({
                "identifier": ident,
                "issue_id": issue["id"],
                "agent": agent,
                "event": event.get("event", ""),
                "points": event.get("points"),
            })

        if args.json:
            continue
        icons = {
            "event-written": "✅", "baseline": "🗂️", "already-baselined": "🗂️",
            "no-transition": "⏭️", "non-scoring": "⏭️", "deferred": "⏳",
            "escalated-blocked": "⛔", "credited-same-event": "🔁",
            "needs-baseline": "⚠️", "test-skip": "🧪",
            "invalid-status": "❌", "write-error": "❌",
        }
        icon = icons.get(action, "•")
        line = f"  {icon} {ident} [{agent}] {plan.get('reason', '')}"
        if action == "event-written":
            line += f" {event.get('points', 0):+d}"
        print(line)

    if args.json:
        report = {
            "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "mode": "dry-run" if args.dry_run else ("baseline" if args.baseline else "normal"),
            "scanned": len(issues),
            "stats": stats,
            "events_written": events_out,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))
        _exit_on_error(stats)
        return

    print()
    print("========== 钩子汇总 ==========")
    for k, v in sorted(stats.items(), key=lambda kv: -kv[1]):
        print(f"  {k}: {v}")
    print(f"  合计: {sum(stats.values())}")
    _exit_on_error(stats)


if __name__ == "__main__":
    main()
