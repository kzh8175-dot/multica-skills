#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
autopilot-slo-guard.py — 日更 autopilot 链路 SLO 守卫（KA-338 / A-3）

背景: 2026-09-05 → 09-11 六条日更 autopilot 链路 34 次计划运行、20 次失败
(58.8%)，且**全部静默**——失败不产生任何通知，只能靠人事后翻 `multica autopilot
runs` 才发现。本脚本把「事后翻日志」变成「定时判定 + 建单」。

三个动作（可分别调度）:
  --report      根因占比表：按 failure_reason 归类，输出 本机侧 / 平台侧 占比
  --check       告警判定：连续失败 / 同日多链路失败 / P0 单次失败 / 静默漏跑
                → 超阈值时建 P1 issue（幂等去重，24h 冷却）
  --compensate  失火追偿：对「漏跑且仍在补偿窗口内」的链路调用
                `multica autopilot trigger`，失败按抖动退避重试

设计约束（与 runbook.md 对齐）:
  - 静默 = 故障：应执行窗口过后仍无 run 记录，视同失败
  - 告警按**用户可见影响**分级，不按错误字符串分级
  - 追偿必须尊重**时序**：钩子 00:20 必须早于结算 00:30，补偿窗口只有 9 分钟，
    所以退避是秒级抖动而非分钟级
  - 幂等：同一 (链路, 根因类别) 24h 内只建单一次；state 文件记录冷却窗口
  - 只读平台：除 `autopilot trigger` / `issue create` 外不写任何 Multica 资源

退出码:
  0 = 无需动作 / 判定通过
  1 = 有告警或追偿失败（调用方按非 0 处理）
  2 = 脚本自身错误（配置缺失、CLI 不可用）

用法:
  python3 scripts/autopilot-slo-guard.py --report
  python3 scripts/autopilot-slo-guard.py --check --dry-run
  python3 scripts/autopilot-slo-guard.py --check --notify
  python3 scripts/autopilot-slo-guard.py --compensate --dry-run
  python3 scripts/autopilot-slo-guard.py --check --report --lookback-hours 168
"""

import argparse
import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------- 常量

TZ = timezone(timedelta(hours=8))  # Asia/Shanghai，与 autopilot schedule 同口径
HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
DEFAULT_CONF = os.path.join(REPO_ROOT, "config", "autopilot-slo-guard.conf")
DEFAULT_STATE = os.path.join(
    os.environ.get("MULTICA_SLO_GUARD_STATE_DIR", os.path.expanduser("~/.multica")),
    "autopilot-slo-guard.state.json",
)
OK_STATUSES = {"completed", "issue_created", "success", "succeeded"}
SRE_AGENT_ID = "05d17dc2-4b1e-4cae-9de2-5ff1c9e58eed"  # 系统稳定性工程师


# ---------------------------------------------------------------- 工具

def now_local():
    """当前本地时间。SLO_GUARD_NOW 可用于规则回放（backtest），格式 ISO8601。"""
    override = os.environ.get("SLO_GUARD_NOW")
    if override:
        return parse_iso(override) or datetime.now(TZ)
    return datetime.now(TZ)


def parse_iso(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(TZ)
    except ValueError:
        return None


def run_cli(args, timeout=120):
    """调用 multica CLI。返回 (rc, stdout, stderr)。"""
    try:
        p = subprocess.run(
            ["multica"] + args,
            capture_output=True, text=True, timeout=timeout,
        )
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", "multica CLI not found in PATH"
    except subprocess.TimeoutExpired:
        return 124, "", "multica CLI timeout after %ss" % timeout


def load_conf(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_state(path):
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (ValueError, OSError):
            pass
    return {"alerts": {}, "compensations": []}


def save_state(path, state):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


def classify(reason, rules):
    """把 failure_reason 映射到 (cause_class, side, owner)。"""
    if not reason:
        return ("unknown", "unknown", "—")
    for r in rules:
        for pat in r["patterns"]:
            if pat in reason:
                return (r["cause_class"], r["side"], r.get("owner", "—"))
    return ("unclassified", "unknown", "—")


# ---------------------------------------------------------------- 槽位与 run 对账

def expected_slots(link, start, end):
    """枚举 [start, end] 内该链路应执行的槽位（本地时间）。"""
    out = []
    hh, mm = (int(x) for x in link["slots"][0].split(":"))
    day = start.date()
    while day <= end.date():
        if day.weekday() in link.get("weekdays", list(range(7))):
            slot = datetime(day.year, day.month, day.day, hh, mm, tzinfo=TZ)
            if start <= slot <= end:
                out.append(slot)
        day += timedelta(days=1)
    return out


def match_run(runs, slot, match_window_min):
    """找出落在槽位 [slot, slot+match_window] 内的 run（取最早一条）。"""
    hi = slot + timedelta(minutes=match_window_min)
    hits = [r for r in runs if slot <= r["_created"] <= hi]
    hits.sort(key=lambda r: r["_created"])
    return hits[0] if hits else None


def fetch_runs(autopilot_id, limit=60):
    rc, out, err = run_cli(["autopilot", "runs", autopilot_id, "--limit", str(limit), "--output", "json"])
    if rc != 0:
        raise RuntimeError("autopilot runs %s failed: %s" % (autopilot_id, err.strip() or out.strip()))
    data = json.loads(out)
    runs = data.get("runs", data if isinstance(data, list) else [])
    for r in runs:
        r["_created"] = parse_iso(r.get("created_at"))
    return [r for r in runs if r["_created"]]


def evaluate(conf, lookback_hours, match_window_min, since=None):
    """对账所有链路 → 每槽位判定 OK / FAILED / MISSED。"""
    now = now_local()
    start = since if since else (now - timedelta(hours=lookback_hours))
    rows, per_link = [], {}
    for link in conf["links"]:
        runs = fetch_runs(link["autopilot_id"])
        slots = expected_slots(link, start, now)
        recs = []
        for slot in slots:
            run = match_run(runs, slot, match_window_min)
            if run is None:
                # 静默漏跑：槽位早已过期且无 run 记录
                if now > slot + timedelta(minutes=match_window_min):
                    recs.append({"slot": slot, "state": "MISSED", "run": None,
                                 "cause_class": "silent_miss", "side": "local"})
                continue
            st = (run.get("status") or "").lower()
            if st in OK_STATUSES:
                recs.append({"slot": slot, "state": "OK", "run": run,
                             "cause_class": None, "side": None})
            else:
                cc, side, _ = classify(run.get("failure_reason"), conf["cause_rules"])
                recs.append({"slot": slot, "state": "FAILED", "run": run,
                             "cause_class": cc, "side": side})
        recs.sort(key=lambda r: r["slot"])
        for r in recs:
            r["_link_id"] = link["autopilot_id"]
            r["_link_name"] = link["name"]
        per_link[link["autopilot_id"]] = {"link": link, "recs": recs}
        rows.extend(recs)
    return per_link, rows, now


def trailing_failures(recs):
    """末尾连续非 OK 槽位数。"""
    n = 0
    for r in reversed(recs):
        if r["state"] in ("FAILED", "MISSED"):
            n += 1
        else:
            break
    return n


# ---------------------------------------------------------------- --report

def cmd_report(conf, per_link, rows, window_label):
    total = len(rows)
    failed = [r for r in rows if r["state"] != "OK"]
    ok = total - len(failed)

    print("## autopilot 链路 SLO 报告")
    print()
    print("窗口: %s（截止 %s）" % (window_label, now_local().strftime("%Y-%m-%d %H:%M %Z")))
    print()
    print("| 链路 | 计划 | 成功 | 失败/漏跑 | 成功率 | 末尾连续失败 |")
    print("|---|---:|---:|---:|---:|---:|")
    for link in conf["links"]:
        recs = per_link[link["autopilot_id"]]["recs"]
        f = sum(1 for r in recs if r["state"] != "OK")
        ratio = "%.0f%%" % (100.0 * (len(recs) - f) / len(recs)) if recs else "n/a"
        print("| %s | %d | %d | %d | %s | %d |" % (
            link["name"], len(recs), len(recs) - f, f, ratio, trailing_failures(recs)))
    print("| **合计** | **%d** | **%d** | **%d** | **%s** | |" % (
        total, ok, len(failed),
        ("%.1f%%" % (100.0 * ok / total)) if total else "n/a"))
    print()

    # 根因占比表
    agg = {}
    for r in failed:
        key = (r["side"], r["cause_class"])
        agg.setdefault(key, 0)
        agg[key] += 1
    print("### 根因占比（本机侧 vs 平台侧）")
    print()
    print("| 侧 | 根因类别 | 次数 | 占比 |")
    print("|---|---|---:|---:|")
    for (side, cc), n in sorted(agg.items(), key=lambda kv: -kv[1]):
        side_label = {"local": "本机侧", "platform": "平台侧", "unknown": "待定性"}.get(side, side)
        print("| %s | %s | %d | %.1f%% |" % (side_label, cc, n, 100.0 * n / len(failed)))
    local_n = sum(n for (s, _), n in agg.items() if s == "local")
    plat_n = sum(n for (s, _), n in agg.items() if s == "platform")
    print()
    print("**本机侧 %d/%d（%.1f%%） · 平台侧 %d/%d（%.1f%%）**" % (
        local_n, len(failed), 100.0 * local_n / len(failed),
        plat_n, len(failed), 100.0 * plat_n / len(failed)))
    print()

    if failed:
        print("### 失败明细")
        print()
        print("| 本地时间 | 链路 | 状态 | 根因 | 失败原因（截断） |")
        print("|---|---|---|---|---|")
        for r in failed:
            reason = (r["run"].get("failure_reason") or "") if r["run"] else "无 run 记录（静默漏跑）"
            print("| %s | %s | %s | %s | %s |" % (
                r["slot"].strftime("%m-%d %H:%M"),
                r.get("_link_name", "?"),
                r["state"], r["cause_class"] or "-", reason[:90].replace("|", "/")))
        print()
    return 0 if not failed else 1


# ---------------------------------------------------------------- --check

def cmd_check(conf, per_link, rows, state, state_path, notify, dry_run):
    now = now_local()
    ac = conf["alert"]
    today = now.date()

    alerts = []          # 待建单
    day_fail_links = {}  # 自然日 → 失败链路集合（跨链路规则用）
    recent_cut = now - timedelta(hours=ac.get("same_day_window_hours", 24))

    for link in conf["links"]:
        recs = per_link[link["autopilot_id"]]["recs"]
        if not recs:
            continue
        # 连续失败：在完整历史窗口内计末尾连续非 OK 槽位
        # （槽位粒度是 1 天/链路，窗口必须 ≥ 阈值天数才有判别力）
        consec = trailing_failures(recs)
        last = recs[-1]

        # 跨链路规则只看最近 same_day_window_hours 内的失败
        for r in recs:
            if r["state"] != "OK" and r["slot"] >= recent_cut:
                day_fail_links.setdefault(r["slot"].date(), set()).add(link["name"])

        if consec >= ac["consecutive_failures_p1"]:
            alerts.append({
                "link": link, "rec": last, "severity": "P1",
                "trigger": "连续 %d 次失败（阈值 %d）" % (consec, ac["consecutive_failures_p1"]),
                "dedup": "%s|%s" % (link["autopilot_id"], last["cause_class"] or "unknown"),
            })
        elif link.get("p0") and last["state"] != "OK" and last["slot"] >= recent_cut \
                and ac.get("p0_single_failure_p1"):
            alerts.append({
                "link": link, "rec": last, "severity": "P1",
                "trigger": "P0 链路单次失败即告警（%s）" % link.get("deadline_reason", "关键时序链路"),
                "dedup": "%s|%s" % (link["autopilot_id"], last["cause_class"] or "unknown"),
            })

    # 跨链路系统性失败：同一自然日内 ≥N 条不同链路失败
    for d, names in sorted(day_fail_links.items()):
        if len(names) >= ac["same_day_distinct_links_p1"]:
            alerts.append({
                "link": {"name": "跨链路（%s）" % "、".join(sorted(names)), "autopilot_id": "cross"},
                "rec": None, "severity": "P1",
                "trigger": "%s 同日 %d 条链路同时失败（阈值 %d）——系统性失火，非偶发"
                           % (d.isoformat(), len(names), ac["same_day_distinct_links_p1"]),
                "dedup": "cross|%s" % d.isoformat(),
            })

    # 冷却去重
    live, suppressed = [], []
    for a in alerts:
        last_at = parse_iso(state["alerts"].get(a["dedup"], {}).get("at"))
        if last_at and (now - last_at) < timedelta(hours=ac["cooldown_hours"]):
            suppressed.append(a)
        else:
            live.append(a)

    print("## 告警判定（%s）" % now.strftime("%Y-%m-%d %H:%M %Z"))
    print()
    if not alerts:
        print("✅ 无告警：所有链路在阈值内。")
    for a in live:
        print("🔴 **%s** %s —— %s" % (a["severity"], a["link"]["name"], a["trigger"]))
    for a in suppressed:
        print("⚪（冷却中，24h 内已建单）%s —— %s" % (a["link"]["name"], a["trigger"]))
    print()

    rc = 0
    if live and notify and not dry_run:
        for a in live:
            issue_id, msg = create_alert_issue(a, conf)
            print("→ 建单: %s" % msg)
            if issue_id:
                state["alerts"][a["dedup"]] = {"at": now.isoformat(), "issue": issue_id}
            else:
                rc = 1
        save_state(state_path, state)
    elif live and dry_run:
        print("（dry-run：不建单、不写 state。以下为将要提交的告警单内容）")
        for a in live:
            title, body = render_alert(a, conf)
            print()
            print("┌─ 将要创建：%s" % title)
            for line in body.splitlines():
                print("│ %s" % line)
            print("└─（assignee=%s, priority=high）" % SRE_AGENT_ID)
    elif live:
        print("（未传 --notify：仅判定，不建单）")

    return 1 if live else rc


def render_alert(alert, conf):
    """渲染告警 issue 的 (title, body)。与建单解耦，便于 dry-run 复验。"""
    link = alert["link"]
    rec = alert["rec"]
    cause = rec["cause_class"] if rec else "cross_link"
    reason = (rec["run"].get("failure_reason") or "无 run 记录（静默漏跑）") if rec and rec["run"] else "—"
    slot = rec["slot"].strftime("%Y-%m-%d %H:%M") if rec else "—"
    body = "\n".join([
        "由 `scripts/autopilot-slo-guard.py --check --notify` 自动创建（KA-338 / A-3）。",
        "",
        "## 判定",
        "",
        "| 项 | 值 |",
        "|---|---|",
        "| 链路 | %s |" % link["name"],
        "| autopilot | `%s` |" % link["autopilot_id"],
        "| 触发条件 | %s |" % alert["trigger"],
        "| 槽位（本地） | %s |" % slot,
        "| 根因类别 | `%s` |" % cause,
        "| 失败原因 | %s |" % reason.replace("|", "/"),
        "",
        "## 处置（runbook.md §3 升级路径）",
        "",
        "1. 复现判据：`multica autopilot runs %s --output json`" % link["autopilot_id"],
        "2. 本机侧优先自愈：确认供电与休眠策略、本地推理网关与代理隧道；追偿 `python3 scripts/autopilot-slo-guard.py --compensate`",
        "3. 24h 未处置 → 升级资深战略领导者（SLA 48h）",
        "",
        "---",
        "*本单为自动告警，同类根因 24h 内不重复建单。*",
    ])
    title = "autopilot 失火告警 · %s · %s" % (link["name"], cause)
    return title, body


def create_alert_issue(alert, conf):
    title, body = render_alert(alert, conf)
    # --description-file 只接受当前工作目录内的路径（MUL-4252），因此落在 CWD。
    tmp = os.path.join(os.getcwd(), ".slo-guard-alert-%d.md" % os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(body)
    try:
        rc, out, err = run_cli([
            "issue", "create", "--title", title,
            "--description-file", tmp,
            "--priority", "high",
            "--assignee-id", SRE_AGENT_ID,
            "--output", "json",
        ], timeout=180)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    if rc != 0:
        return None, "建单失败: %s" % (err.strip() or out.strip())
    try:
        iid = json.loads(out).get("identifier") or json.loads(out).get("id")
    except ValueError:
        iid = out.strip()[:60]
    return iid, "%s %s" % (title, iid)


# ---------------------------------------------------------------- --compensate

def cmd_compensate(conf, per_link, state, state_path, dry_run):
    """失火追偿。两条通道，**不新建重复 issue**：

    - MISSED（平台无 run 记录 → 也未建 issue）: `autopilot trigger` 补一次计划运行。
    - FAILED（run.issue_id 已存在，issue 滞留 todo/in_progress）: 对**既有 issue**
      就地补跑 `issue assign <issue_id> --to-id <agent>`，绝不再次 `autopilot trigger`
      —— 那会生成第二张同名 issue（已在 KA-328 实证）。

    两通道都尊重 deadline 与抖动退避。
    """
    now = now_local()
    cc = conf["compensate"]
    sched = conf.get("schedule_source", {})
    agent_of = sched.get("assignee_by_autopilot", {})
    acted, reported, skipped = 0, 0, 0

    if not cc.get("enabled", True):
        print("补偿已在配置中关闭。")
        return 0

    failed_mode = cc.get("failed_rerun", "report")  # off | report | assign

    for link in conf["links"]:
        recs = per_link.get(link["autopilot_id"], {}).get("recs", [])
        deadline_h, deadline_m = (int(x) for x in link["deadline"].split(":"))
        for r in recs:
            if r["state"] == "OK":
                continue
            deadline = r["slot"].replace(hour=deadline_h, minute=deadline_m)
            if deadline <= r["slot"]:
                deadline += timedelta(days=1)
            past = cc.get("never_after_deadline", True) and now >= deadline
            slot_s = r["slot"].strftime("%m-%d %H:%M")

            if r["state"] == "MISSED":
                if past:
                    print("⏭  %s %s —— 漏跑且已过补偿截止 %s，不追偿（转告警通道）"
                          % (link["name"], slot_s, deadline.strftime("%H:%M")))
                    skipped += 1
                    continue
                if dry_run:
                    print("→（dry-run）将补触发 %s（槽位 %s，截止 %s）"
                          % (link["name"], slot_s, deadline.strftime("%H:%M")))
                    acted += 1
                    continue
                ok = retry_with_backoff(
                    lambda: run_cli(["autopilot", "trigger", link["autopilot_id"], "--output", "json"], timeout=120),
                    cc, deadline, "%s 补触发" % link["name"])
                if ok:
                    state["compensations"].append({"at": now_local().isoformat(), "link": link["name"],
                                                   "slot": r["slot"].isoformat(), "kind": "trigger"})
                    acted += 1
                else:
                    skipped += 1
                continue

            # ---- FAILED：绝不新建 issue，就地补跑既有 issue ----
            run = r["run"] or {}
            issue_id = run.get("issue_id")
            if not issue_id:
                print("⚠  %s %s —— 失败但 run 无 issue_id，无法就地补跑" % (link["name"], slot_s))
                skipped += 1
                continue
            cmd = "multica issue assign %s --to-id %s" % (issue_id, agent_of.get(link["autopilot_id"], "<agent-id>"))
            if failed_mode == "off":
                continue
            if failed_mode == "report":
                print("📋 %s %s —— 失败，issue `%s` 滞留；就地补跑命令：%s"
                      % (link["name"], slot_s, issue_id, cmd))
                reported += 1
                continue
            if past:
                print("⏭  %s %s —— 失败且已过补偿截止，不就地补跑（转告警通道）" % (link["name"], slot_s))
                skipped += 1
                continue
            if dry_run:
                print("→（dry-run）将就地补跑 %s（issue %s）" % (link["name"], issue_id))
                acted += 1
                continue
            ok = retry_with_backoff(
                lambda iid=issue_id, lid=link: run_cli(
                    ["issue", "assign", iid, "--to-id", agent_of.get(lid["autopilot_id"], "")], timeout=120),
                cc, deadline, "%s 就地补跑" % link["name"])
            if ok:
                state["compensations"].append({"at": now_local().isoformat(), "link": link["name"],
                                               "slot": r["slot"].isoformat(), "kind": "rerun",
                                               "issue": issue_id})
                acted += 1
            else:
                skipped += 1

    if not dry_run:
        save_state(state_path, state)
    print()
    print("补偿完成：执行 %d，待人工确认 %d，跳过/失败 %d（failed_rerun=%s）"
          % (acted, reported, skipped, failed_mode))
    return 0 if skipped == 0 else 1


def retry_with_backoff(call, cc, deadline, label):
    """带抖动退避的重试；每次重试前检查是否已越过 deadline。"""
    for attempt in range(1, cc["max_attempts"] + 1):
        if now_local() >= deadline:
            print("⏭  %s —— 重试中撞上截止时间，停止" % label)
            return False
        rc, out, err = call()
        if rc == 0:
            print("✅ %s 成功（第 %d 次）" % (label, attempt))
            return True
        msg = (err.strip() or out.strip())[:140]
        if attempt >= cc["max_attempts"]:
            print("❌ %s 耗尽重试: %s" % (label, msg))
            return False
        delay = cc["base_delay_seconds"] * (2 ** (attempt - 1))
        delay *= 1 + random.uniform(-cc["jitter_ratio"], cc["jitter_ratio"])
        print("⚠ %s 失败（第 %d 次）: %s —— %.0fs 后重试" % (label, attempt, msg, delay))
        time.sleep(max(1.0, delay))
    return False


# ---------------------------------------------------------------- --sync-schedule

CRON_DOW = {"0": 6, "1": 0, "2": 1, "3": 2, "4": 3, "5": 4, "6": 5, "7": 6}


def parse_minute_hour(cron):
    """只解 `M H * * *` / `M H * * D` 形态（本 workspace 六条链路均为此形态）。"""
    f = cron.split()
    if len(f) != 5:
        raise ValueError("不支持的 cron: %s" % cron)
    hh, mm = int(f[1]), int(f[0])
    dow_field = f[4]
    if dow_field == "*":
        days = list(range(7))
    else:
        days = sorted({CRON_DOW[p] for p in dow_field.split(",") if p in CRON_DOW})
    return "%02d:%02d" % (hh, mm), days


def cmd_sync_schedule(conf, conf_path, dry_run):
    """从平台拉取 cron / 时区 / 指派 agent，回写配置，消除配置漂移。"""
    changed = 0
    agent_map = conf.setdefault("schedule_source", {}).setdefault("assignee_by_autopilot", {})
    for link in conf["links"]:
        rc, out, err = run_cli(["autopilot", "get", link["autopilot_id"], "--output", "json"])
        if rc != 0:
            print("⚠ %s: autopilot get 失败: %s" % (link["name"], (err or out).strip()[:120]))
            continue
        d = json.loads(out)
        ap = d.get("autopilot", d)
        trs = [t for t in d.get("triggers", []) if t.get("kind") == "schedule" and t.get("enabled")]
        if not trs:
            print("⚠ %s: 无启用的 schedule trigger，跳过" % link["name"])
            continue
        cron = trs[0].get("cron_expression")
        try:
            slot, days = parse_minute_hour(cron)
        except (ValueError, TypeError) as e:
            print("⚠ %s: %s" % (link["name"], e))
            continue
        tz = trs[0].get("timezone")
        if tz and tz != conf.get("timezone"):
            print("⚠ %s: 平台时区 %s != 配置 %s" % (link["name"], tz, conf.get("timezone")))
        for field, new in (("slots", [slot]), ("weekdays", days)):
            if link.get(field) != new:
                print("→ %s.%s: %s → %s" % (link["name"], field, link.get(field), new))
                link[field] = new
                changed += 1
        aid = ap.get("assignee_id")
        if aid and agent_map.get(link["autopilot_id"]) != aid:
            print("→ %s.assignee: %s → %s" % (link["name"], agent_map.get(link["autopilot_id"]), aid))
            agent_map[link["autopilot_id"]] = aid
            changed += 1
        print("✓ %s: cron=%s tz=%s → slot=%s weekdays=%s" % (link["name"], cron, tz, slot, days))
    if changed and not dry_run:
        with open(conf_path, "w", encoding="utf-8") as f:
            json.dump(conf, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print()
        print("配置已更新（%d 处）：%s" % (changed, conf_path))
    elif changed:
        print()
        print("（dry-run）将有 %d 处变更，未写回。" % changed)
    return 0


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="日更 autopilot 链路 SLO 守卫")
    ap.add_argument("--config", default=DEFAULT_CONF)
    ap.add_argument("--state", default=DEFAULT_STATE)
    ap.add_argument("--report", action="store_true", help="输出 SLO / 根因占比报告")
    ap.add_argument("--check", action="store_true", help="告警判定")
    ap.add_argument("--compensate", action="store_true", help="漏跑追偿（补触发 / 就地补跑）")
    ap.add_argument("--sync-schedule", action="store_true",
                    help="从平台拉取 cron/时区/指派并回写配置（消除配置漂移）")
    ap.add_argument("--notify", action="store_true", help="--check 超阈值时建 P1 issue")
    ap.add_argument("--dry-run", action="store_true", help="只判定不写入")
    ap.add_argument("--lookback-hours", type=int, default=168,
                    help="历史窗口（默认 168h=7d；连续失败阈值需 ≥ 阈值天数的窗口才有判别力）")
    ap.add_argument("--since", default=None,
                    help="窗口起点（本地日期 YYYY-MM-DD，含当日 00:00）；给出时覆盖 --lookback-hours")
    ap.add_argument("--match-window-minutes", type=int, default=20,
                    help="槽位后多久内出现的 run 视为该槽位的执行")
    args = ap.parse_args()

    if not (args.report or args.check or args.compensate or args.sync_schedule):
        ap.error("至少指定 --report / --check / --compensate / --sync-schedule 之一")

    if not os.path.exists(args.config):
        print("配置不存在: %s" % args.config, file=sys.stderr)
        return 2
    conf = load_conf(args.config)

    if args.sync_schedule:
        return cmd_sync_schedule(conf, args.config, args.dry_run)

    state = load_state(args.state)

    since = None
    if args.since:
        try:
            y, m, d = (int(x) for x in args.since.split("-"))
            since = datetime(y, m, d, 0, 0, tzinfo=TZ)
        except ValueError:
            print("--since 需为 YYYY-MM-DD: %s" % args.since, file=sys.stderr)
            return 2

    try:
        per_link, rows, _ = evaluate(conf, args.lookback_hours, args.match_window_minutes, since)
    except RuntimeError as e:
        print("对账失败: %s" % e, file=sys.stderr)
        return 2

    rc = 0
    if args.report:
        label = ("自 %s 00:00 起" % args.since) if since else ("最近 %dh" % args.lookback_hours)
        rc = max(rc, cmd_report(conf, per_link, rows, label))
    if args.check:
        rc = max(rc, cmd_check(conf, per_link, rows, state, args.state, args.notify, args.dry_run))
    if args.compensate:
        rc = max(rc, cmd_compensate(conf, per_link, state, args.state, args.dry_run))
    return rc


if __name__ == "__main__":
    sys.exit(main())
