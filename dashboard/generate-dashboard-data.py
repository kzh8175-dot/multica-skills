#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate-dashboard-data.py — 智能看板数据接口层（只读 · 消费团队标准数据源）

依赖团队标准只读接口 `dashboard-data-feed.py`（KA-96 里程碑 1，仓库
kzh8175-dot/multica-skills commit 0093c62），调用其 `build_feed()` 一次性
聚合评分方案 C 生产数据（月度 R-41 / 季度 R-51+人评+等级 / 事件流水 /
防失真 / 预算 metadata / 运行态）→ 单一 JSON，再映射为看板渲染层使用的
`window.DASHBOARD_DATA`。

设计原则（与 KA-96 验收口径对齐）:
  - 只读：不写入 / 不修改任何评分系统数据；feed 脚本本身也只读；
  - 同源：跨页数值全部来自 feed 的同一份 JSON，无第二处口径；
  - 诚实呈现：Q3 人评待运行（09-28~09-30），综合分/等级按系统当前状态
    显示「待运行」；feed 提供的 `estimated`（objective_only 参考值）保留在
    数据契约中供「参考等级（预估）」等标注场景使用，不冒充正式等级；
  - 试点期防误读：无事件智能体标 E_MISS 且不参与排名，避免「无数据 = D 级」。

用法:
  python3 generate-dashboard-data.py \
      --prod-root <prod/rating-system> \
      [--feed-script <dashboard-data-feed.py>] \
      --out dashboard-data.js
"""

import argparse
import calendar
import datetime
import hashlib
import importlib.util
import json
import os
import re
import sys

# ---------------------------------------------------------------- 周期（动态 · 复用 feed）

# 周期不再硬编码：当前月份/季度取自 dashboard-data-feed 的 current_month() /
# current_quarter()，重生成自动跟随（QUARTER_MONTHS 由季度推导，人评窗口 = 季度末 3 天）。

def quarter_months(quarter):
    """'2026-Q3' → ['2026-07', '2026-08', '2026-09']（季度恒 3 个月）。"""
    m = re.match(r"^(\d{4})-Q([1-4])$", quarter or "")
    if not m:
        return []
    year, q = int(m.group(1)), int(m.group(2))
    first = (q - 1) * 3 + 1
    return [f"{year}-{mm:02d}" for mm in range(first, first + 3)]


def quarter_label(quarter):
    """'2026-Q3' → '2026 Q3'。"""
    m = re.match(r"^(\d{4})-Q([1-4])$", quarter or "")
    return f"{m.group(1)} Q{m.group(2)}" if m else (quarter or "")


def month_label(month):
    """'2026-08' → '8月'。"""
    return f"{int(month[5:7])}月" if month and len(month) == 7 else (month or "")


def human_review_window(quarter):
    """季度末 3 天窗口：'2026-Q3' → '09-28 ~ 09-30'。"""
    qmonths = quarter_months(quarter)
    if not qmonths:
        return "季度末 3 天"
    last_year, last_month = int(qmonths[-1][:4]), int(qmonths[-1][5:7])
    last_day = calendar.monthrange(last_year, last_month)[1]
    return f"{last_month:02d}-{last_day - 2:02d} ~ {last_month:02d}-{last_day:02d}"


def stable_agent_id(category, name):
    """稳定 slug：category + 名称 SHA-256 前 10 位十六进制。

    agt-%03d 序号会随智能体集合/排序变化导致深链漂移；改用名称哈希，
    重生成 / 新增智能体不影响既有 #page-detail?agent= 深链。
    """
    digest = hashlib.sha256(f"{category}:{name}".encode("utf-8")).hexdigest()
    return f"agt-{digest[:10]}"


def split_events(row, month):
    """事件行按 ';' 拆分为多条独立事件（R-21:自评;R-22:更新能力档案 → 2 条）。

    事件流水单行可含多个 `;` 分隔子事件（R-21~R-33 行为事件）。拆分后事件流
    页逐条完整呈现；行积分按子事件均分（余数给前几条），单条保留整行积分。
    """
    raw = (row.get("event") or "").strip()
    parts = [p.strip() for p in raw.split(";") if p.strip()]
    if not parts:
        parts = [raw]
    total = row.get("points")
    n = len(parts)
    out = []
    for i, part in enumerate(parts):
        if ":" in part:
            code, _, desc = part.partition(":")
            code, desc = code.strip(), desc.strip()
        else:
            code, desc = part, part
        pts = None
        if total is not None:
            pts = total if n == 1 else total // n + (1 if i < total % n else 0)
        out.append({
            "ts": short_ts(row.get("time", "")),
            "code": code,
            "desc": desc or raw,
            "points": pts,
            "month": month,
        })
    return out


CATEGORY_LABELS = {
    "execution": "执行",
    "data": "数据",
    "marketing": "营销",
    "creative": "创意",
    "technical": "技术",
}

def short_ts(ts):
    m = re.match(r"^\d{4}-(\d{2}-\d{2}) (\d{2}:\d{2})", ts or "")
    return f"{m.group(1)} {m.group(2)}" if m else ts


# ---------------------------------------------------------------- feed 加载


def load_feed_module(feed_script):
    spec = importlib.util.spec_from_file_location("dashboard_data_feed", feed_script)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dashboard_data_feed"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- 映射


def build_dashboard(prod_root, feed_mod, use_cli=True):
    agents_root = os.path.join(prod_root, "agents")
    dirs = feed_mod.scoring_dirs(agents_root)
    # 周期：复用 feed 动态取当前月份/季度（重生成自动跟随），不硬编码
    month = feed_mod.current_month()
    quarter = feed_mod.current_quarter()
    qmonths = quarter_months(quarter)
    qlabels = [month_label(m) for m in qmonths]
    months = [month]
    quarters = [quarter]
    agents = feed_mod.discover_agents(agents_root, dirs)
    feed = feed_mod.build_feed(agents_root, months, quarters, agents, use_cli=use_cli)

    month_short = month_label(month)
    quarter_lbl = quarter_label(quarter)
    window = human_review_window(quarter)
    monthly = feed.get("monthly", {}).get(month, {})
    quarterly = feed.get("quarterly", {}).get(quarter, {})
    events_by_agent = feed.get("events", {}).get(month, {})
    agent_info = {a["name"]: a for a in feed.get("agents", [])}

    # 评分人口 = 有月度或季度报告输出的智能体（feed.agents 含非评分档案，如设计部）
    scored_names = sorted(set(list(monthly.keys()) + list(quarterly.keys())))

    agents_out = []
    flags_out = []
    for name in scored_names:
        info = agent_info.get(name, {})
        category = info.get("category", "execution")
        benchmark = info.get("benchmark", 300)

        m = monthly.get(name, {})
        q = quarterly.get(name, {})
        ev = events_by_agent.get(name, {})

        month_has = bool(ev.get("rows"))
        month_total = ev.get("total", 0) if month_has else 0
        month_pct = m.get("score", 0) if name in monthly else 0

        # has_data：当前月事件流水（feed 只载当月，季度其他月判断恒假——迭代 2 #8 移除死逻辑）
        has_data = month_has

        qflags = q.get("flags", []) or []
        est = q.get("estimated") or {}

        # 防失真 / 异常标记（季度表单已回填值 + 数据缺口）
        # P1 口径修复（KA-106 代码审查 · 数据缺口跨页不一致 39 vs 63）：
        # E_MISS/E_EMPTY 仅对「当月无数据」智能体记为数据缺口；有当月数据的智能体，
        # 季度内部分月份缺失（7/9 月未到期 / 待补记）不算缺口——Q3 试点仅 8 月结算，
        # 全员季度表单都带 7/9 月 E_MISS，原逻辑把 24 个有 8 月真实数据的智能体误标
        # 「数据缺口·待处理」。异常中心 / 事件流 / 排行榜 / 明细页据此跨页一致。
        agent_flags = []
        for f in qflags:
            code = f.split(":")[0].strip()
            if (code.startswith("E_MISS") or code.startswith("E_EMPTY")) and not has_data:
                agent_flags.append({"code": code, "month": None, "msg": f})
            elif code.startswith("E_PARSE"):
                agent_flags.append({"code": "E_PARSE", "month": None, "msg": f})
        af = q.get("anti_fraud") or {}
        if af.get("r71"):
            agent_flags.append({"code": "R-71", "month": None, "msg": "R-31 红线事件 ≥2 次，等级上限 C（季度表单已回填）"})
        if af.get("r72"):
            agent_flags.append({"code": "R-72", "month": None, "msg": "R-32 缺自评 ≥2 次，等级降一档（季度表单已回填）"})
        if af.get("e02"):
            agent_flags.append({"code": "E-02", "month": None, "msg": "单评分人上限 A（季度表单已回填）"})

        # 事件（当前月）：多事件行按 ';' 拆分，事件流逐条完整呈现
        events = []
        for r in ev.get("rows", []):
            events.extend(split_events(r, month))
        events.sort(key=lambda x: x["ts"], reverse=True)

        # 季度月度数组：当前月落到对应季度位（重生成自动跟随）
        q_idx = qmonths.index(month) if month in qmonths else 1
        q_totals, q_pcts = [0, 0, 0], [0, 0, 0]
        q_totals[q_idx] = month_total
        q_pcts[q_idx] = month_pct

        agents_out.append({
            "id": stable_agent_id(category, name),
            "name": name,
            "category": category,
            "categoryLabel": CATEGORY_LABELS.get(category, category),
            "benchmark": benchmark,
            "monthTotal": month_total,
            "monthPct": month_pct,
            "monthHasData": month_has,
            "quarterTotals": q_totals,
            "quarterPcts": q_pcts,
            "objective": q.get("objective"),
            "hasData": has_data,
            "human": q.get("human_final"),
            "humanNote": f"{quarter_lbl} 人评待运行（窗口 {window}）",
            "composite": q.get("comprehensive"),
            "grade": q.get("grade"),
            "reviewState": q.get("review_state", "pending"),
            "estimated": {
                "comprehensive": est.get("comprehensive"),
                "grade": est.get("grade"),
                "basis": est.get("basis", "objective_only"),
                "asOf": est.get("as_of"),
            } if est else None,
            "flags": agent_flags,
            "events": events,
            "q2": None,
            "q2g": None,
        })

    # 事件流（看板页：合并所有智能体行 + 系统运行态）
    event_rows = []
    by_id = {a["id"]: a for a in agents_out}
    for a in agents_out:
        for ev in a["events"]:
            event_rows.append({
                "ts": ev["ts"], "agentId": a["id"], "agentName": a["name"],
                "code": ev["code"], "desc": ev["desc"], "points": ev["points"],
                "status": "已入账",
            })
    # 系统运行态事件：时基按当前周期推导（月末聚合日 = 当前月最后一天，人评窗口 = 季度末 3 天）
    y, mo = int(month[:4]), int(month[5:7])
    last_day = calendar.monthrange(y, mo)[1]
    q_last_day = calendar.monthrange(int(qmonths[-1][:4]), int(qmonths[-1][5:7]))[1]
    today_d = min(datetime.datetime.now(datetime.timezone.utc).day, last_day)
    event_rows.append({
        "ts": f"{month[5:7]}-{today_d:02d} 00:11", "agentId": None, "agentName": "结算引擎",
        "code": "R-41", "desc": f"{month_short}每日结算已生成（每日 00:30 · 月末 {month[5:7]}-{last_day:02d} 聚合为月度百分制）",
        "points": None, "status": "已完成",
    })
    event_rows.append({
        "ts": f"{month[5:7]}-{last_day:02d} 01:15", "agentId": None, "agentName": "聚合引擎",
        "code": "R-51", "desc": "月度百分制月末聚合计划（R-41 → 季度客观分 R-51）",
        "points": None, "status": "排队中",
    })
    event_rows.append({
        "ts": f"{qmonths[-1][5:7]}-{q_last_day - 2:02d} 02:15", "agentId": None, "agentName": "人评引擎",
        "code": "R-52", "desc": f"{quarter_lbl} 季度人评窗口（{window}）· 客观×0.8 + 人评×0.2",
        "points": None, "status": "排队中",
    })
    for a in agents_out:
        # 仅「当月无数据」智能体进入事件流缺口标记（P1 口径：有数据智能体的
        # 7/9 月缺失为未到期/待补记，不算缺口，见上方 agent_flags 注释）
        if any(f["code"] == "E_MISS" for f in a["flags"]):
            event_rows.append({
                "ts": f"{qmonths[0][5:7]}-01 00:00", "agentId": a["id"], "agentName": a["name"],
                "code": "E_MISS", "desc": "本季事件流水缺失，按 0 计并标记（待补记）",
                "points": None, "status": "已标记",
            })
    event_rows.sort(key=lambda r: (r["ts"].split()[0], r["ts"].split()[1] if " " in r["ts"] else "00:00"), reverse=True)

    # 预算：积分口径（R-42 基准推导）+ SOP 项目预算（平台元数据，feed 提供）
    cats = {}
    for a in agents_out:
        c = cats.setdefault(a["category"], {
            "category": a["category"], "label": a["categoryLabel"],
            "agents": 0, "benchmark": a["benchmark"], "spent": 0, "has_data": 0})
        c["agents"] += 1
        c["spent"] += a["monthTotal"]
        if a["hasData"]:
            c["has_data"] += 1
    total_ceiling = total_spent = 0
    cat_rows = []
    for c in cats.values():
        ceiling = c["benchmark"] * 3 * c["agents"]
        spent = c["spent"]
        util = (spent / ceiling) if ceiling else 0
        status = "红色预警" if util >= 0.95 else ("接近预警" if util >= 0.85 else "正常")
        total_ceiling += ceiling
        total_spent += spent
        cat_rows.append({
            "category": c["category"], "label": c["label"],
            "agents": c["agents"], "benchmark": c["benchmark"],
            "ceiling": ceiling, "spent": spent, "variance": ceiling - spent,
            "utilization": round(util * 100, 1), "status": status,
        })
    cat_rows.sort(key=lambda r: -r["utilization"])

    sop = []
    for e in (feed.get("budget") or {}).get("entries") or []:
        sop.append({
            "identifier": e.get("identifier", ""),
            "title": e.get("title", ""),
            "status": e.get("status", ""),
            "tier": e.get("tier", ""),
            "ceiling": e.get("ceiling"),
            "spent": e.get("spent"),
            "variance": e.get("variance"),
        })

    rt = feed.get("runtime", {})
    runtime = {
        "settlement": rt.get("settlement_last_run") or "待运行",
        "aggregation": rt.get("aggregation_last_run") or "待运行",
        "review": rt.get("review_last_run") or "待运行",
        "ratingStatus": rt.get("rating_status") or {},
        "settlementSchedule": "每日 00:30",
        "aggregationSchedule": "月末最后一日 01:15（R-41/R-51）",
        "reviewSchedule": f"季度末 3 天 02:15（{quarter_lbl} 窗口 {window}）",
        "reconcileSchedule": "每周预算对账（SOP 三级预算）",
    }

    # 异常中心
    anomalies = []
    for a in agents_out:
        for f in a["flags"]:
            if f["code"] in ("E_MISS", "E_EMPTY"):
                anomalies.append({
                    "agentId": a["id"], "agentName": a["name"],
                    "code": "E-01", "desc": f["msg"], "ts": "本季",
                    "status": "待处理", "kind": "数据缺失",
                })
            elif f["code"] == "E_PARSE":
                anomalies.append({
                    "agentId": a["id"], "agentName": a["name"],
                    "code": "E-01", "desc": f["msg"], "ts": "本季",
                    "status": "待处理", "kind": "数据解析",
                })
            elif f["code"] in ("R-71", "R-72", "E-02"):
                anomalies.append({
                    "agentId": a["id"], "agentName": a["name"],
                    "code": f["code"], "desc": f["msg"], "ts": "本季",
                    "status": "已标记", "kind": "防失真",
                })
    seen = set()
    deduped = []
    for it in anomalies:
        key = (it["agentId"], it["code"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)
    deduped.sort(key=lambda x: (0 if x["status"] == "待处理" else 1, x["agentId"]))

    with_data = [a for a in agents_out if a["hasData"]]
    return {
        "meta": {
            "project": "评分方案 C · 智能评分系统",
            "quarter": quarter,
            "quarterLabel": quarter_lbl,
            "quarterMonths": qmonths,
            "quarterMonthLabels": qlabels,
            "month": month,
            "monthLabel": f"{month[5:]}月",
            "year": str(y),
            "generatedAt": feed.get("meta", {}).get("generated_at", ""),
            "schemaVersion": feed.get("meta", {}).get("schema_version", ""),
            "agentCount": len(agents_out),
            "agentsWithData": len(with_data),
            "humanReview": "pending",
            "humanReviewWindow": window,
            "gradeThresholds": {"S": "≥95", "A": "85-94", "B": "70-84",
                                "C": "60-69", "D": "<60"},
            "categoryLabels": CATEGORY_LABELS,
            "note": f"试点初期·数据样本不足：{len(agents_out)} 个智能体中仅 {len(with_data)} 个有 {month_short} 事件流水；"
                    f"{quarter_lbl} 人评待运行（{window}），综合分/等级按系统当前状态显示「待运行」，"
                    "参考等级（预估）由客观分映射，随季度人评转正式。",
        },
        "agents": agents_out,
        "events": event_rows,
        "budget": {
            "points": {
                "ceiling": total_ceiling,
                "spent": total_spent,
                "variance": total_ceiling - total_spent,
                "utilization": round(total_spent / total_ceiling * 100, 1) if total_ceiling else 0,
                "categories": cat_rows,
            },
            "sop": sop,
        },
        "runtime": runtime,
        "anomalies": deduped,
    }


# ---------------------------------------------------------------- 输出


def main():
    parser = argparse.ArgumentParser(description="智能看板数据接口层（消费 dashboard-data-feed）")
    parser.add_argument("--prod-root", required=True,
                        help="生产树 prod/rating-system 路径")
    parser.add_argument("--feed-script", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "dashboard-data-feed.py"),
        help="dashboard-data-feed.py 路径（默认取本目录同名文件）")
    parser.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "dashboard-data.js"),
        help="输出 JS 数据文件路径")
    parser.add_argument("--no-cli", action="store_true",
                        help="离线：不调用 multica（预算/运行态计数缺省）")
    args = parser.parse_args()

    prod_root = os.path.abspath(args.prod_root)
    if not os.path.exists(args.feed_script):
        print(f"❌ 未找到 dashboard-data-feed.py: {args.feed_script}", file=sys.stderr)
        sys.exit(2)
    feed_mod = load_feed_module(args.feed_script)

    data = build_dashboard(prod_root, feed_mod, use_cli=not args.no_cli)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    body = "/* 自动生成 · 请勿手改 · 数据源 dashboard-data-feed.py（KA-96 里程碑 1，Schema v1.0） */\n" \
           "window.DASHBOARD_DATA = " + json.dumps(data, ensure_ascii=False, indent=2) + ";\n"
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(body)

    with_data = [a for a in data["agents"] if a["hasData"]]
    print(f"✓ 智能体: {len(data['agents'])}（有数据 {len(with_data)}）")
    print(f"✓ 事件: {len(data['events'])} 条（含系统运行态）")
    print(f"✓ 预算: 积分上限 {data['budget']['points']['ceiling']} / 已用 {data['budget']['points']['spent']} / "
          f"SOP 行 {len(data['budget']['sop'])}")
    print(f"✓ 异常: {len(data['anomalies'])} 条")
    print(f"✓ 运行态: 结算 {data['runtime']['settlement']} / 聚合 {data['runtime']['aggregation']} / "
          f"人评 {data['runtime']['review']}")
    print(f"✓ 输出: {os.path.abspath(args.out)}")
    print(f"注意: {data['meta']['note']}")


if __name__ == "__main__":
    main()
