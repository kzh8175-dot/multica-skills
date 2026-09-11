#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test-autopilot-slo-guard.py — autopilot-slo-guard.py 单元测试（KA-338 / A-3）

覆盖:
  1. classify()      对本周四类真实 failure_reason 的归类（含平台侧反例）
  2. expected_slots() 槽位枚举 / 周频（每周预算对账仅周一）
  3. trailing_failures() 连续失败计数
  4. match_run()     槽位 ↔ run 的时间归属
  5. parse_minute_hour() 平台 cron 解析
  6. cmd_compensate() 两条通道 + deadline 拦截（含 FAILED run 绝不 autopilot trigger 的守护）
  7. render_alert()  告警单渲染

运行: python3 src/test-autopilot-slo-guard.py
"""

import importlib.util
import io
import os
import sys
import contextlib
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "scripts"))

spec = importlib.util.spec_from_file_location(
    "slo_guard", os.path.join(REPO, "scripts", "autopilot-slo-guard.py"))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print("%s %s%s" % ("✅" if cond else "❌", name, ("  —— " + str(detail)) if detail else ""))


# ---------------------------------------------------------------- 1. classify
RULES = [
    {"cause_class": "local_inference_gateway", "side": "local",
     "patterns": ["请求转发失败", "上游请求失败", "client error (Connect)", "API Error"]},
    {"cause_class": "local_runtime_unavailable", "side": "local",
     "patterns": ["runtime unavailable while task was queued", "runtime went offline"]},
    {"cause_class": "local_network_reset", "side": "local",
     "patterns": ["connection reset by peer", "start task failed"]},
    {"cause_class": "platform_queue_expired", "side": "platform", "patterns": ["task expired in queue"]},
    {"cause_class": "platform_upstream_5xx", "side": "platform", "patterns": ["上游 HTTP 502", "Bad Gateway"]},
]

CASES = [
    ("API Error: 502 请求转发失败: 上游请求失败: client error (Connect). This is a server-side issue, "
     "usually temporary — try again in a moment. If it persists, check your inference gateway (127.0.0.1:15721).",
     "local_inference_gateway", "local"),
    ("runtime unavailable while task was queued", "local_runtime_unavailable", "local"),
    ("runtime went offline", "local_runtime_unavailable", "local"),
    ('start task failed: Post "https://api.multica.ai/api/daemon/tasks/01a0725e-e691-7469-806c-652c30818fc4/start": '
     "read tcp 198.18.0.2:65026->198.18.0.55:443: read: connection reset by peer",
     "local_network_reset", "local"),
    ("task expired in queue", "platform_queue_expired", "platform"),
    ("上游 HTTP 502: The origin web server returned an invalid or incomplete response to Cloudflare.",
     "platform_upstream_5xx", "platform"),
    (None, "unknown", "unknown"),
    ("something nobody has seen before", "unclassified", "unknown"),
]
for reason, want_cc, want_side in CASES:
    cc, side, _ = g.classify(reason, RULES)
    check("classify → %s" % want_cc, (cc, side) == (want_cc, want_side), "got %s/%s" % (cc, side))

# 关键反例：本机推理网关的错误文案里带 "server-side issue"，但不得归到平台侧
cc, side, _ = g.classify(CASES[0][0], RULES)
check("classify 不把本地推理网关误判为平台侧（文案含 'server-side issue'）", side == "local", side)

# ---------------------------------------------------------------- 2. expected_slots
daily = {"slots": ["00:20"], "weekdays": list(range(7))}
mondays = {"slots": ["09:37"], "weekdays": [0]}
start = datetime(2026, 9, 5, 0, 0, tzinfo=g.TZ)   # 周六
end = datetime(2026, 9, 11, 23, 59, tzinfo=g.TZ)  # 周五
check("expected_slots 每日链路 7 天 → 7 槽位", len(g.expected_slots(daily, start, end)) == 7,
      len(g.expected_slots(daily, start, end)))
mon = g.expected_slots(mondays, start, end)
check("expected_slots 周频链路（周一）→ 1 槽位", len(mon) == 1 and mon[0].weekday() == 0, mon)
check("expected_slots 槽位时刻正确", mon and mon[0].strftime("%H:%M") == "09:37" and mon[0].date().isoformat() == "2026-09-07")

# ---------------------------------------------------------------- 3. trailing_failures
mk = lambda states: [{"state": s} for s in states]
check("trailing_failures 全 OK → 0", g.trailing_failures(mk(["OK", "OK"])) == 0)
check("trailing_failures 末尾 3 连败 → 3", g.trailing_failures(mk(["OK", "FAILED", "FAILED", "FAILED"])) == 3)
check("trailing_failures MISSED 计入", g.trailing_failures(mk(["OK", "MISSED", "FAILED"])) == 2)
check("trailing_failures 末尾 OK → 0（已恢复）", g.trailing_failures(mk(["FAILED", "FAILED", "OK"])) == 0)

# ---------------------------------------------------------------- 4. match_run
slot = datetime(2026, 9, 5, 0, 20, tzinfo=g.TZ)
runs = [
    {"_created": datetime(2026, 9, 5, 0, 20, 15, tzinfo=g.TZ), "id": "in-window"},
    {"_created": datetime(2026, 9, 5, 2, 13, 42, tzinfo=g.TZ), "id": "late"},
    {"_created": datetime(2026, 9, 4, 0, 20, 15, tzinfo=g.TZ), "id": "prev-day"},
]
m = g.match_run(runs, slot, 20)
check("match_run 取窗口内最早 run", m and m["id"] == "in-window", m and m["id"])
check("match_run 无匹配 → None", g.match_run([runs[1]], slot, 20) is None)

# ---------------------------------------------------------------- 5. parse_minute_hour
REAL_CRONS = [
    ("20 0 * * *", "00:20", list(range(7))),
    ("45 1 * * *", "01:45", list(range(7))),
    ("50 1 * * *", "01:50", list(range(7))),
    ("45 18 * * *", "18:45", list(range(7))),
    ("23 20 * * *", "20:23", list(range(7))),
    ("37 9 * * 1", "09:37", [0]),
]
for cron, want_slot, want_days in REAL_CRONS:
    s, d = g.parse_minute_hour(cron)
    check("parse_minute_hour %-12s → %s" % (cron, want_slot), (s, d) == (want_slot, want_days), "%s %s" % (s, d))

# ---------------------------------------------------------------- 6. cmd_compensate
def make_conf(failed_rerun="report", base_delay=1):
    return {
        "links": [
            {"autopilot_id": "ap-hook", "name": "钩子", "slots": ["00:20"], "weekdays": list(range(7)),
             "deadline": "00:29", "p0": True},
            {"autopilot_id": "ap-long", "name": "长窗链路", "slots": ["01:45"], "weekdays": list(range(7)),
             "deadline": "03:00", "p0": False},
        ],
        "compensate": {"enabled": True, "failed_rerun": failed_rerun, "max_attempts": 2,
                       "base_delay_seconds": base_delay, "jitter_ratio": 0.0,
                       "never_after_deadline": True},
        "schedule_source": {"assignee_by_autopilot": {"ap-hook": "agent-A", "ap-long": "agent-B"}},
    }


class Recorder:
    def __init__(self, results):
        self.calls, self.results = [], list(results)

    def __call__(self, args, timeout=120):
        self.calls.append(args)
        r = self.results.pop(0) if self.results else (0, "{}", "")
        return r


def run_compensate(conf, per_link, rec=None, dry_run=False, now=None, clock=None):
    import tempfile
    g.now_local = clock if clock else ((lambda: now) if now else (lambda: datetime.now(g.TZ)))
    orig_cli = g.run_cli
    if rec is not None:
        g.run_cli = rec
    buf = io.StringIO()
    with tempfile.TemporaryDirectory() as td:
        try:
            with contextlib.redirect_stdout(buf):
                rc = g.cmd_compensate(conf, per_link, {"compensations": []},
                                      os.path.join(td, "state.json"), dry_run)
        finally:
            g.run_cli = orig_cli
    return rc, buf.getvalue()


def ticking_clock(start, step_seconds):
    """每次读取前进 step_seconds —— 模拟重试等待期间真实时间流逝。"""
    box = {"t": start}

    def now():
        t = box["t"]
        box["t"] = t + timedelta(seconds=step_seconds)
        return t
    return now


# 6a. MISSED + 未过截止 → 走 autopilot trigger
conf = make_conf()
now = datetime(2026, 9, 5, 0, 25, tzinfo=g.TZ)
per_link = {"ap-hook": {"recs": [{"slot": datetime(2026, 9, 5, 0, 20, tzinfo=g.TZ),
                                  "state": "MISSED", "run": None}]}}
rec = Recorder([(0, "{}", "")])
rc, out = run_compensate(conf, per_link, rec, now=now)
check("MISSED 未过截止 → 调 autopilot trigger",
      rec.calls and rec.calls[0][:2] == ["autopilot", "trigger"] and rec.calls[0][2] == "ap-hook", rec.calls)
check("MISSED 追偿成功 rc=0", rc == 0, rc)

# 6b. MISSED + 已过截止 → 不追偿
conf = make_conf()
per_link = {"ap-hook": {"recs": [{"slot": datetime(2026, 9, 5, 0, 20, tzinfo=g.TZ),
                                  "state": "MISSED", "run": None}]}}
rec = Recorder([])
rc, out = run_compensate(conf, per_link, rec, now=datetime(2026, 9, 5, 1, 0, tzinfo=g.TZ))
check("MISSED 已过截止 → 不调用 CLI", not rec.calls, rec.calls)
check("MISSED 已过截止 → 输出截止说明", "已过补偿截止" in out, out.strip()[:80])

# 6c. FAILED + failed_rerun=report → 只报告，绝不 trigger
conf = make_conf(failed_rerun="report")
per_link = {"ap-long": {"recs": [{"slot": datetime(2026, 9, 5, 1, 45, tzinfo=g.TZ), "state": "FAILED",
                                  "run": {"issue_id": "iss-1", "failure_reason": "runtime went offline"}}]}}
rec = Recorder([])
rc, out = run_compensate(conf, per_link, rec, now=datetime(2026, 9, 5, 2, 0, tzinfo=g.TZ))
check("FAILED report 模式 → 不调用任何 CLI", not rec.calls, rec.calls)
check("FAILED report 模式 → 给出既有 issue 与就地补跑命令",
      "iss-1" in out and "issue assign iss-1 --to-id agent-B" in out, out.strip()[:160])
check("FAILED report 模式 → 绝不 autopilot trigger（防重复建单）",
      "autopilot" not in " ".join(" ".join(c) for c in rec.calls), rec.calls)

# 6d. FAILED + failed_rerun=assign → 就地补跑既有 issue
conf = make_conf(failed_rerun="assign")
per_link = {"ap-long": {"recs": [{"slot": datetime(2026, 9, 5, 1, 45, tzinfo=g.TZ), "state": "FAILED",
                                  "run": {"issue_id": "iss-1", "failure_reason": "runtime unavailable while task was queued"}}]}}
rec = Recorder([(0, "{}", "")])
rc, out = run_compensate(conf, per_link, rec, now=datetime(2026, 9, 5, 2, 0, tzinfo=g.TZ))
check("FAILED assign 模式 → 对既有 issue 执行 issue assign",
      rec.calls and rec.calls[0][:2] == ["issue", "assign"] and rec.calls[0][2] == "iss-1", rec.calls)
check("FAILED assign 模式 → 绝不 autopilot trigger",
      all(c[0] != "autopilot" for c in rec.calls), rec.calls)

# 6e. 抖动退避：连续失败 → 重试，且次数受 max_attempts 限制
conf = make_conf(failed_rerun="assign", base_delay=1)
conf["compensate"]["max_attempts"] = 3
per_link = {"ap-long": {"recs": [{"slot": datetime(2026, 9, 5, 1, 45, tzinfo=g.TZ), "state": "FAILED",
                                  "run": {"issue_id": "iss-1", "failure_reason": "x"}}]}}
rec = Recorder([(1, "", "boom"), (1, "", "boom"), (0, "{}", "")])
rc, out = run_compensate(conf, per_link, rec, clock=ticking_clock(datetime(2026, 9, 5, 2, 0, tzinfo=g.TZ), 5))
check("退避重试：2 次失败后第 3 次成功 → 共 3 次调用", len(rec.calls) == 3, len(rec.calls))
check("退避重试成功 → rc=0", rc == 0, rc)

# 6e-2. 抖动确实存在（jitter_ratio>0 时延时非恒定）
delays = set()
for _ in range(60):
    conf = make_conf(failed_rerun="assign", base_delay=8)
    conf["compensate"]["max_attempts"] = 2
    conf["compensate"]["jitter_ratio"] = 0.3
    per_link = {"ap-long": {"recs": [{"slot": datetime(2026, 9, 5, 1, 45, tzinfo=g.TZ), "state": "FAILED",
                                      "run": {"issue_id": "i", "failure_reason": "x"}}]}}
    rec = Recorder([(1, "", "boom"), (0, "{}", "")])
    buf_delays = []
    orig_sleep = g.time.sleep
    g.time.sleep = lambda d: buf_delays.append(d)
    try:
        run_compensate(conf, per_link, rec, clock=ticking_clock(datetime(2026, 9, 5, 2, 0, tzinfo=g.TZ), 1))
    finally:
        g.time.sleep = orig_sleep
    if buf_delays:
        delays.add(round(buf_delays[0], 3))
check("退避带抖动：60 次采样延时不全相同", len(delays) > 1, "样本数=%d" % len(delays))
check("退避在 base±jitter 区间内", all(8 * 0.7 <= d <= 8 * 1.3 for d in delays),
      "min=%.2f max=%.2f" % (min(delays), max(delays)) if delays else "无样本")

# 6f. 重试期间撞 deadline → 停止
conf = make_conf(failed_rerun="assign", base_delay=1)
per_link = {"ap-hook": {"recs": [{"slot": datetime(2026, 9, 5, 0, 20, tzinfo=g.TZ), "state": "FAILED",
                                  "run": {"issue_id": "iss-9", "failure_reason": "x"}}]}}
rec = Recorder([(1, "", "boom"), (1, "", "boom"), (0, "{}", "")])
rc, out = run_compensate(conf, per_link, rec,
                         clock=ticking_clock(datetime(2026, 9, 5, 0, 28, 50, tzinfo=g.TZ), 5))
check("撞 deadline → 停止重试（只调 1 次）", len(rec.calls) == 1, len(rec.calls))
check("撞 deadline → 输出停止说明", "撞上截止时间" in out, out.strip()[:80])

# ---------------------------------------------------------------- 7. render_alert
conf = make_conf()
alert = {"link": conf["links"][0], "severity": "P1", "trigger": "连续 3 次失败（阈值 3）",
         "rec": {"slot": datetime(2026, 9, 7, 0, 20, tzinfo=g.TZ), "cause_class": "local_runtime_unavailable",
                 "run": {"failure_reason": "runtime unavailable while task was queued"}}}
title, body = g.render_alert(alert, conf)
check("render_alert 标题含链路与根因", "钩子" in title and "local_runtime_unavailable" in title, title)
check("render_alert 正文含复现命令", "multica autopilot runs ap-hook --output json" in body)
check("render_alert 正文含升级路径", "SLA 48h" in body)

# 跨链路告警（rec=None）不得崩
alert2 = {"link": {"name": "跨链路（A、B）", "autopilot_id": "cross"}, "severity": "P1",
          "trigger": "同日 2 条链路失败", "rec": None}
try:
    t2, b2 = g.render_alert(alert2, conf)
    check("render_alert 支持跨链路（rec=None）", "cross_link" in t2, t2)
except Exception as e:
    check("render_alert 支持跨链路（rec=None）", False, repr(e))

# ---------------------------------------------------------------- 汇总
print()
print("=" * 64)
print("通过 %d / %d" % (len(PASS), len(PASS) + len(FAIL)))
if FAIL:
    print("失败用例：")
    for f in FAIL:
        print("  - %s" % f)
    sys.exit(1)
print("全部通过 ✅")
