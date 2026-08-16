#!/usr/bin/env python3
"""
rating-settler.py — 评分积分结算器（方案C 阶段3）

职责: 实现积分状态流转
  pending → 结算中 → credited（成功）
                    → pending（失败，指数退避重试 ≤3次）
                    → escalated（重试耗尽/不可重试，升级最高决策者）

用法:
  python3 rating-settler.py                # 正常结算全部 pending
  python3 rating-settler.py --dry-run      # 仅扫描报告，不实际结算
  python3 rating-settler.py --limit 10     # 最多处理10个
  python3 rating-settler.py --issue <id>   # 结算指定 issue
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

# 最高决策者（资深战略领导者）
DECISION_MAKER = {
    "id": "f7410a50-25bf-43b9-9435-a7d6cb3ec5fe",
    "name": "资深战略领导者",
}

# 指数退避重试参数
MAX_RETRY = 3
RETRY_DELAYS = [30, 60, 120]  # 秒

# 工作目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EVENTS_DIR = os.path.join(BASE_DIR, "..", "reviews", "scoring", "events")

# 错误码
E_PARSE = "E_PARSE"      # 值格式错误（不可重试）
E_API = "E_API"          # multica API 调用失败（可重试）
E_WRITE = "E_WRITE"      # 本地流水写入失败（可重试）
E_DUP = "E_DUP"          # 重复结算（幂等跳过）
E_MISS = "E_MISS"        # 缺少必要键（不可重试）


def load_agents(path="/tmp/agents-v4.json"):
    """加载 agent id → 名称 映射。

    优先实时拉取 `multica agent list`（best-effort：CLI 失败/空结果时
    回退到本地缓存文件；缓存也缺失则返回空映射，调用方落到「未知智能体」，
    不中断结算主流程）。修复 F1：不再优先使用可能陈旧的 /tmp 缓存。
    """
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
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
        return {a["id"]: a["name"] for a in data if a.get("id") and a.get("name")}
    return {}


def load_squads():
    """加载 squad id → 名称 映射（best-effort：CLI 失败返回空）。

    修复 F3：assignee_type=squad 的 issue 可解析为 squad 名称，不再落入
    「未知智能体」。
    """
    try:
        result = subprocess.run(
            ["multica", "squad", "list", "--output", "json"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if isinstance(data, list):
                return {s["id"]: s["name"] for s in data if s.get("id") and s.get("name")}
    except Exception:
        pass
    return {}


def resolve_agent_name(issue, agents, squads):
    """解析 issue 归属 agent 名称。

    优先级：assignee_id（agent）→ assignee_id（squad，解析为 squad 名）
    → creator_id 兜底。全部失败回落到「未知智能体」，不中断结算主流程。
    修复 F3：assignee 缺失时回退 creator；squad assignee 按 squad 名解析。
    """
    aid = issue.get("assignee_id")
    if aid:
        if aid in agents:
            return agents[aid]
        if aid in squads:
            return squads[aid]
        return "未知智能体"
    cid = issue.get("creator_id")
    return agents.get(cid, "未知智能体")


def run_cli(args):
    """执行 multica CLI，返回 (ok, parsed_json_or_text)。"""
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


def list_pending_issues(limit=None):
    """列出所有 rating.status=pending 的 issue。"""
    cmd = ["issue", "list", "--metadata", "rating.status=pending", "--output", "json"]
    if limit:
        cmd += ["--limit", str(limit)]
    ok, out = run_cli(cmd)
    if not ok:
        return None, out
    try:
        data = json.loads(out)
        # issue list 返回包装对象 {issues: [...], total: N}
        if isinstance(data, dict) and "issues" in data:
            return data["issues"], None
        return data, None
    except json.JSONDecodeError:
        return None, "JSON 解析失败"


def get_issue_metadata(issue_id):
    """获取 issue 的全部 metadata。"""
    ok, out = run_cli(["issue", "metadata", "list", issue_id, "--output", "json"])
    if not ok:
        return None, out
    try:
        return json.loads(out), None
    except json.JSONDecodeError:
        return None, "JSON 解析失败"


def set_metadata(issue_id, key, value, vtype="string"):
    """写入单个 metadata 键。"""
    ok, out = run_cli([
        "issue", "metadata", "set", issue_id,
        "--key", key, "--value", str(value), "--type", vtype, "--output", "json",
    ])
    return ok, out


def validate_event(meta):
    """校验积分事件的必要字段。返回 (ok, error_code, error_msg)。"""
    required = {
        "rating.event": ("string", lambda v: isinstance(v, str) and v.startswith("R-")),
        "rating.points": ("number", lambda v: isinstance(v, (int, float))),
        "rating.trigger": ("string", lambda v: v in ("agent", "reviewer")),
    }
    for key, (vtype, checker) in required.items():
        if key not in meta:
            return False, E_MISS, f"缺少必要键 {key}"
        if not checker(meta[key]):
            return False, E_PARSE, f"{key} 值非法: {meta[key]}"

    # points 必须为整数（积分事件）
    if not isinstance(meta["rating.points"], int):
        return False, E_PARSE, f"rating.points 非整数: {meta['rating.points']}"
    return True, None, None


def get_event_month(meta):
    """从 occurred_at 或当前时间确定事件月份。"""
    ts = meta.get("rating.occurred_at")
    if ts:
        try:
            return ts[:7]  # "2026-08-16T..." → "2026-08"
        except Exception:
            pass
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _issue_credited_globally(issue_id, event, month):
    """跨文件全局去重：检查 (issue_id, rating.event) 是否已写入任意智能体的同月流水。

    修复 F2：E_DUP 原本仅按单文件判断，同一 issue 因 agent 解析差异
    （陈旧映射→未知智能体 vs 实时映射→真实智能体）会写入两个文件，
    聚合器按文件独立求和导致双计。

    修复 S-1（P1-10/KA-75）：去重键由 issue_id 改为 (issue_id, rating.event)。
    同一 issue 可承载多个不同事件（如 R-21 自评 + R-31 违反约束），不再被
    E_DUP 拦截；同一 (issue, 事件) 仍只写一次，保持「跨文件不双计」的
    防聚合双计属性（同一 issue 的归属解析是确定性的，事件不会跨智能体分裂）。
    """
    if not os.path.isdir(EVENTS_DIR):
        return False
    for agent_dir in os.listdir(EVENTS_DIR):
        f = os.path.join(EVENTS_DIR, agent_dir, f"{month}.md")
        if os.path.isfile(f):
            try:
                with open(f, encoding="utf-8") as fh:
                    for line in fh:
                        fields = [x.strip() for x in line.strip().strip("|").split("|")]
                        if len(fields) >= 3 and fields[1] == issue_id and fields[2] == event:
                            return True
            except OSError:
                continue
    return False


def append_to_events(agent_name, month, issue_id, meta):
    """追加积分事件到流水文件（幂等去重）。

    写失败（OSError）返回 (False, E_WRITE, 描述)，由调用方走指数退避重试。
    """
    try:
        os.makedirs(os.path.join(EVENTS_DIR, agent_name), exist_ok=True)
        events_file = os.path.join(EVENTS_DIR, agent_name, f"{month}.md")

        # 创建文件头（若不存在）
        if not os.path.exists(events_file):
            with open(events_file, "w") as f:
                f.write("| 时间 | 任务 | 事件 | 积分 |\n")
                f.write("|------|------|------|:---:|\n")

        # 去重检查（跨文件全局：(issue_id, rating.event) 同一事件不得双计，
        # 防聚合双计；同一 issue 不同事件允许共存 —— S-1 修复）
        event_desc = meta.get("rating.event", "?")
        if _issue_credited_globally(issue_id, event_desc, month):
            return False, E_DUP, f"issue {issue_id} 事件 {event_desc} 已存在于流水（全局去重）"

        # 确定任务标识
        points = meta["rating.points"]
        ts = meta.get("rating.occurred_at", "")[:16].replace("T", " ")

        line = f"| {ts} | {issue_id} | {event_desc} | {points:+d} |\n"
        with open(events_file, "a") as f:
            f.write(line)
        return True, None, None
    except OSError as e:
        return False, E_WRITE, f"写入流水失败: {e}"


def settle_one(issue, meta, agent_name, dry_run=False):
    """
    结算单个 issue。返回 (new_status, error_code)。
    状态流转:
      pending → credited / pending(重试) / escalated
    """
    # 校验
    ok, err_code, err_msg = validate_event(meta)
    if not ok:
        if err_code in (E_PARSE, E_MISS):
            # 不可重试 → escalated
            if not dry_run:
                set_metadata(issue["id"], "rating.status", "escalated", "string")
                set_metadata(issue["id"], "rating.note", f"{err_code}: {err_msg}", "string")
            print(f"  ⬆️  {issue['identifier']} [{agent_name}] → escalated ({err_code}: {err_msg})")
            return "escalated", err_code
        return None, err_code

    month = get_event_month(meta)

    if dry_run:
        print(f"  🔍 [DRY-RUN] {issue['identifier']} [{agent_name}] "
              f"{meta['rating.event']} {meta['rating.points']:+d} → 将结算到 {month}")
        return "pending", None

    # 结算: 写流水 → 更新状态
    ok, werr_code, werr_msg = append_to_events(agent_name, month, issue["id"], meta)
    if not ok:
        if werr_code == E_DUP:
            # 幂等：流水已存在 → 直接标记 credited
            set_metadata(issue["id"], "rating.status", "credited", "string")
            set_metadata(issue["id"], "rating.settled_at",
                         datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "string")
            print(f"  ⏭️  {issue['identifier']} [{agent_name}] 已存在于流水，标记 credited")
            return "credited", None
        # 写失败 → 可重试
        return _retry_settle(issue, meta, agent_name, month, werr_code, werr_msg)

    # 更新 metadata: credited
    set_metadata(issue["id"], "rating.status", "credited", "string")
    set_metadata(issue["id"], "rating.settled_at",
                 datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "string")
    print(f"  ✅ {issue['identifier']} [{agent_name}] {meta['rating.event']} "
          f"{meta['rating.points']:+d} → credited ({month})")
    return "credited", None


def _retry_settle(issue, meta, agent_name, month, err_code, err_msg):
    """指数退避重试写流水。"""
    retry_count = 0
    while retry_count < MAX_RETRY:
        retry_count += 1
        delay = RETRY_DELAYS[min(retry_count - 1, len(RETRY_DELAYS) - 1)]
        print(f"  🔁 重试 {retry_count}/{MAX_RETRY} ({err_code}) 等待{delay}s...")
        time.sleep(delay)
        ok, werr_code, werr_msg = append_to_events(agent_name, month, issue["id"], meta)
        if ok:
            set_metadata(issue["id"], "rating.status", "credited", "string")
            set_metadata(issue["id"], "rating.settled_at",
                         datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "string")
            print(f"  ✅ {issue['identifier']} [{agent_name}] 重试成功 → credited")
            return "credited", None
        if werr_code == E_DUP:
            set_metadata(issue["id"], "rating.status", "credited", "string")
            print(f"  ⏭️  {issue['identifier']} 已存在于流水，标记 credited")
            return "credited", None
        err_code, err_msg = werr_code, werr_msg

    # 重试耗尽 → escalated
    set_metadata(issue["id"], "rating.status", "escalated", "string")
    set_metadata(issue["id"], "rating.retry_count", str(retry_count), "number")
    set_metadata(issue["id"], "rating.note", f"重试{retry_count}次失败: {err_code} {err_msg}", "string")
    print(f"  ⬆️  {issue['identifier']} [{agent_name}] 重试耗尽 → escalated "
          f"(升级最高决策者 {DECISION_MAKER['name']})")
    return "escalated", err_code


def main():
    parser = argparse.ArgumentParser(description="评分积分结算器")
    parser.add_argument("--dry-run", action="store_true", help="仅扫描报告，不实际结算")
    parser.add_argument("--limit", type=int, default=None, help="最多处理N个 pending issue")
    parser.add_argument("--issue", help="只结算指定 issue-id")
    args = parser.parse_args()

    print("=== 评分积分结算器 (rating-settler) ===")
    print(f"模式: {'DRY-RUN' if args.dry_run else '正常结算'}")
    print(f"最高决策者: {DECISION_MAKER['name']} ({DECISION_MAKER['id']})")
    print()

    # 加载 agent 映射（agent + squad，用于归属解析）
    agents = load_agents()
    squads = load_squads()

    # 获取 pending issues
    if args.issue:
        ok, out = run_cli(["issue", "get", args.issue, "--output", "json"])
        if not ok:
            print(f"❌ 获取 issue 失败: {out}")
            sys.exit(1)
        issues = [json.loads(out)]
    else:
        issues, err = list_pending_issues(args.limit)
        if err:
            print(f"❌ 列出 pending issue 失败: {err}")
            sys.exit(1)
        if issues is None:
            print("❌ 无返回")
            sys.exit(1)

    print(f"发现 {len(issues)} 个待结算 issue\n")

    stats = {"credited": 0, "escalated": 0, "pending": 0, "skipped": 0}
    for issue in issues:
        # 解析归属 agent 名称（assignee → squad → creator 兜底）
        agent_name = resolve_agent_name(issue, agents, squads)

        # 读取 metadata
        meta, err = get_issue_metadata(issue["id"])
        if err or meta is None:
            print(f"  ❌ {issue.get('identifier', issue['id'])} 读取 metadata 失败: {err}")
            stats["escalated"] += 1
            continue

        # 幂等检查
        if meta.get("rating.status") != "pending":
            print(f"  ⏭️  {issue.get('identifier', issue['id'])} 状态={meta.get('rating.status')}，跳过")
            stats["skipped"] += 1
            continue

        # 测试数据隔离（rating.test=true 跳过结算，防御性兜底）
        if meta.get("rating.test") is True:
            if not args.dry_run:
                set_metadata(issue["id"], "rating.status", "credited", "string")
                set_metadata(issue["id"], "rating.note", "测试数据，不进入真实积分", "string")
            print(f"  🧪 {issue.get('identifier', issue['id'])} 测试数据(rating.test)，标记为credited，不计入真实积分")
            stats["skipped"] += 1
            continue

        status, _ = settle_one(issue, meta, agent_name, args.dry_run)
        if status in stats:
            stats[status] += 1

    print()
    print("========== 结算汇总 ==========")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"  合计: {sum(stats.values())}")

    # 生成结算报告
    report_path = os.path.join(BASE_DIR, "..", "reviews", "scoring", "settler-report.json")
    report = {
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dry_run": args.dry_run,
        "stats": stats,
    }
    with open(report_path, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"报告已写入: {os.path.normpath(report_path)}")


if __name__ == "__main__":
    main()
