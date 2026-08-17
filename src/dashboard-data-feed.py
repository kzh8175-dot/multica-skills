#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dashboard-data-feed.py — 智能看板只读数据接口（KA-96）

职责: 把评分方案 C 的生产数据聚合为一份统一 JSON，供智能看板 8 页
（总览/排行榜/趋势/评分明细/事件流水/预算/升级队列/异常中心）只读渲染。

单一数据源（KA-97 迭代 0 · #3 单一源收敛）:
  本脚本是智能看板的**唯一**数据源（Schema v1.0）。早期并行管线
  `dashboard-data-loader.py`（口径分叉：agent 60/63、排名含无数据智能体、
  全员分母均值、等级分布预估缺失）已随迭代 0 删除，前端只消费由本脚本
  聚合映射的 `window.DASHBOARD_DATA`。发现/聚合/口径全部收敛于本模块，
  回归用例见 `test-dashboard-data-feed.py::TestSingleSourceConvergence`。

数据来源（全部只读，不产生任何写入）:
  1. 月度报告   reviews/scoring/monthly/{agent}/{YYYY-MM}.md   ← rating-aggregator.py
  2. 季度表单   reviews/scoring/quarterly/{agent}/{YYYY-Qn}.md ← 聚合器 + 人评判定
  3. 事件流水   reviews/scoring/events/{agent}/{YYYY-MM}.md    ← rating-settler.py
  4. 防失真日志 reviews/scoring/anti-distortion/{agent}/{YYYY-Qn}.md ← anti-distortion-rules.py
  5. 预算       multica issue metadata 的 budget.ceiling/spent/variance（只读 CLI）
  6. 运行态     由上述目录文件 mtime 与 pending/escalated 计数推导

口径（与 rating-aggregator.py / quarterly-review-judge.py 严格一致，避免跨页冲突）:
  R-41  月度百分制 = clamp(月积分 ÷ 基准 × 100, 0, 120)
  R-51  季度客观分 = (M1+M2+M3) / 3（缺失月按 0 计）
  R-61  季度综合分 = 客观分 × 0.8 + 人评最终分 × 0.2
  R-62~66 等级查表: ≥95 S / ≥85 A / ≥70 B / ≥60 C / <60 D
  R-71  红线事件 ≥2 → 等级上限 C；R-72 缺自评 ≥2 → 降一档；E-02 单评分人 → 上限 A

「人评待运行·预估值」约定: 季度表单尚未被 judge 判定时，
  comprehensive / grade 为 null，同时给出 objective_only 口径的
  comprehensive_estimate / grade_estimate 供 UI 以「预估值」标注呈现，
  并附 as_of 时基（聚合器最后一次写报告的时间）。

幂等/只读: 本脚本不写任何文件；同输入必得同输出（预算/运行态依赖 multica
  CLI 时以 --no-cli 关闭可保完全确定性）。

用法:
  python3 dashboard-data-feed.py                          # 当前月+当前季度，全部智能体
  python3 dashboard-data-feed.py --agents-dir <根>         # 指定 agents 根（默认取脚本上级）
  python3 dashboard-data-feed.py --month 2026-08 --quarter 2026-Q3
  python3 dashboard-data-feed.py --agent "开发者工具工程师"  # 仅单智能体
  python3 dashboard-data-feed.py --pretty                   # 缩进 JSON
  python3 dashboard-data-feed.py --no-cli                   # 离线：跳过 multica（预算/运行态缺省）
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AGENTS_ROOT_DEFAULT = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))

MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")
POINTS_RE = re.compile(r"^[+-]?\d+$")

# R-62~R-66 等级表（与 quarterly-review-judge.py 同源）
GRADE_TABLE = [(95, "S"), (85, "A"), (70, "B"), (60, "C")]
GRADE_DEFAULT = "D"
GRADE_ORDER = ["S", "A", "B", "C", "D"]

# 兜底基准（与 rating-aggregator.py 同源）
FALLBACK_BENCHMARKS = {
    "execution": 400, "data": 350, "marketing": 350,
    "creative": 300, "technical": 300, "default": 300,
}
VALID_CATEGORIES = ("execution", "data", "marketing", "creative", "technical")

KEYWORD_CATEGORIES = [
    (("运营", "客服", "零售", "Jira", "会议"), "execution"),
    (("财务", "分析", "数据", "实验", "趋势", "文档"), "data"),
    (("抖音", "快手", "小红书", "知乎", "微博", "增长", "内容", "社媒",
      "营销", "播客", "轮播", "出版", "微信", "B站"), "marketing"),
    (("战略", "品牌", "视觉", "UI", "设计", "产品"), "creative"),
    (("架构", "身份", "自动化", "流程", "工作流", "SEO", "搜索",
      "本地化", "视频", "剪辑"), "technical"),
]

CATEGORY_RE = re.compile(r"category[=: ]+\s*([a-z]+)")
DESC_CATEGORY_RE = re.compile(r"\[category\s*=\s*([a-z]+)\]")
NORM_RE = re.compile(r"[\s\-]")


# ---------------------------------------------------------------- 纯函数解析

def scoring_dirs(agents_root):
    base = os.path.join(agents_root, "reviews", "scoring")
    return {
        "events": os.path.join(base, "events"),
        "monthly": os.path.join(base, "monthly"),
        "quarterly": os.path.join(base, "quarterly"),
        "anti_distortion": os.path.join(base, "anti-distortion"),
    }


def load_benchmarks(agents_root):
    """读取 rating-benchmarks.conf；缺失/异常回退内置默认（与聚合器同源）。"""
    bench = dict(FALLBACK_BENCHMARKS)
    path = os.path.join(agents_root, "capability-system", "rating-benchmarks.conf")
    if not os.path.exists(path):
        path = os.path.join(agents_root, "config", "rating-benchmarks.conf")
    if not os.path.exists(path):
        return bench
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                if key.strip() and value.strip().isdigit():
                    bench[key.strip()] = int(value.strip())
    except OSError:
        pass
    return bench


def get_benchmark(category, benchmarks):
    return benchmarks.get(category) or benchmarks.get("default", 300)


def keyword_category(agent_name):
    for keywords, cat in KEYWORD_CATEGORIES:
        if any(k in agent_name for k in keywords):
            return cat
    return "execution"


def profile_category(agent_name, profiles_root):
    """从能力档案读 category 标签；无档案返回 None。"""
    profile_file = os.path.join(profiles_root, agent_name, "capabilities.md")
    if not os.path.exists(profile_file):
        return None
    try:
        with open(profile_file, encoding="utf-8") as f:
            for line in f:
                m = CATEGORY_RE.search(line)
                if m and m.group(1).lower() in VALID_CATEGORIES:
                    return m.group(1).lower()
    except OSError:
        pass
    return None


def resolve_category(agent_name, profiles_root, cli_cats):
    """CLI(R-42 标签) → 档案 category → 关键词推断。返回 (category, source)。"""
    norm = NORM_RE.sub("", (agent_name or "").lower())
    if norm in cli_cats:
        return cli_cats[norm], "cli"
    pc = profile_category(agent_name, profiles_root)
    if pc:
        return pc, "profile"
    return keyword_category(agent_name), "inferred"


def parse_monthly_report(path):
    """解析月度报告 → {total, benchmark, score, flags}；文件缺失返回 None。"""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    out = {"total": None, "benchmark": None, "score": None, "flags": []}
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("|") and "|" in line:
            fields = [x.strip() for x in line.strip("|").split("|")]
            if len(fields) >= 2:
                key, val = fields[0], fields[1]
                if key == "月积分" and POINTS_RE.match(val):
                    out["total"] = int(val)
                elif key == "基准月积分" and POINTS_RE.match(val):
                    out["benchmark"] = int(val)
                elif key == "月度百分制" and POINTS_RE.match(val):
                    out["score"] = int(val)
        elif line.startswith("> ⚠️"):
            out["flags"].append(line[4:].strip())
    return out


def _obj_score(text):
    """从季度表单读 R-51 客观分（兼容聚合器两种写法）。"""
    m = re.search(r"季度客观分.*?=\s*\*\*(\d+(?:\.\d+)?)\*\*", text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _human_value(text, key):
    """从表单读 `**<key>** ... = **N**`；未填返回 None。"""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith(key):
            m = re.search(r"=\s*\*\*(\d+(?:\.\d+)?)\*\*", line)
            if m:
                try:
                    return float(m.group(1))
                except ValueError:
                    return None
    return None


def _grade_value(text):
    """读 `**本季等级**: **X**` 或 `______`；已判定返回等级，未判定返回 None。"""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("**本季等级**"):
            m = re.search(r"\*\*([SABCD])\*\*", line)
            return m.group(1) if m else None
    return None


def _anti_fraud_flags(text, judged=False):
    """R-71 / R-72 / E-02 触发标记。

    E-02 仅取 judge 回填标记判定：`review_state==judged` 且含「（E-02 单评分人」
    （judge 在「人评最终分」行追加「（E-02 单评分人，非平均）」、或「人评评分人
    ≥ 2」行写「（E-02 单评分人，等级上限A）」）。模板自带的描述性文字
    「E-02: 单评分人可用，等级上限A」（五、异常处理记录）不含全角括号前缀，
    不触发，避免 pending 表单误标（KA-96 代码审查阻塞项）。
    """
    r71 = bool(re.search(r"（等级上限C）|触发一票否决\(R-71\)", text))
    r72 = bool(re.search(r"（等级降一档）|触发降档\(R-72\)", text))
    e02 = judged and bool(re.search(r"（E-02 单评分人", text))
    return {"r71": r71, "r72": r72, "e02": e02}


def grade_for(comprehensive):
    for low, grade in GRADE_TABLE:
        if comprehensive >= low:
            return grade
    return GRADE_DEFAULT


def parse_quarterly_form(path):
    """解析季度表单 → dict；文件缺失返回 None。

    返回字段:
      objective         R-51 客观分（真实）
      human_final       R-53 人评最终分（null=待运行）
      comprehensive     R-61 综合分（null=待运行）
      grade             等级（null=待运行）
      review_state      "judged" | "pending"
      estimated         待运行时的预估值（objective_only 口径）
      anti_fraud        {r71, r72, e02}
      flags             表单内 ⚠️ 标记
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None

    objective = _obj_score(text)
    grade = _grade_value(text)
    human_final = _human_value(text, "**人评最终分**")
    comprehensive = _human_value(text, "**季度综合分")
    flags = [l.strip()[4:].strip() for l in text.splitlines()
             if l.strip().startswith("> ⚠️")]

    reviewed = grade is not None
    estimated = None
    if not reviewed and objective is not None:
        estimated = {
            "comprehensive": objective,           # 人评待运行，仅客观分口径
            "grade": grade_for(objective),
            "basis": "objective_only",
            "as_of": _file_mtime(path),
        }

    return {
        "objective": objective,
        "human_final": human_final,
        "comprehensive": comprehensive,
        "grade": grade,
        "review_state": "judged" if reviewed else "pending",
        "estimated": estimated,
        "anti_fraud": _anti_fraud_flags(text, judged=reviewed),
        "flags": flags,
    }


def parse_events_file(path):
    """解析事件流水 → {total, rows: [{time, issue, event, points}], flags}。

    points 列无法解析的行记入 flags（与聚合器 E_PARSE 同源，不中断）。
    文件缺失返回 None。
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return None

    total = 0
    rows = []
    flags = []
    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line.startswith("|") or line.startswith("|---"):
            continue
        fields = [f.strip() for f in line.strip("|").split("|")]
        if len(fields) < 4:
            flags.append(f"L{lineno} 列数不足: {line[:60]}")
            continue
        if fields[-1] in ("积分", "---", ":---:"):
            continue  # 表头行
        if POINTS_RE.match(fields[-1]):
            row = {
                "time": fields[0],
                "issue": fields[1],
                "event": fields[2],
                "points": int(fields[-1]),
            }
            rows.append(row)
            total += row["points"]
        else:
            flags.append(f"L{lineno} 积分列无法解析: {fields[-1]}")
    return {"total": total, "rows": rows, "flags": flags}


def parse_anti_distortion_log(path):
    """解析防失真决策日志（append-only）→ 最近一条判定；无记录返回 None。"""
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None

    blocks = re.split(r"\n### ", text)
    latest = None
    for b in blocks:
        if "防失真判定" not in b:
            continue
        auto = re.search(r"auto_grade:\s*([SABCD])", b)
        final = re.search(r"final_grade:\s*([SABCD])", b)
        counts_m = re.search(r"counts:\s*r31=(\d+),\s*r32=(\d+)", b)
        corrections = re.findall(
            r"-\s+(R-7[12])\s+(\w+):\s*([SABCD])\s*→\s*([SABCD])", b)
        latest = {
            "auto_grade": auto.group(1) if auto else None,
            "final_grade": final.group(1) if final else None,
            "counts": {
                "r31": int(counts_m.group(1)) if counts_m else 0,
                "r32": int(counts_m.group(2)) if counts_m else 0,
            },
            "corrections": [
                {"rule": r, "action": a, "from": f, "to": t}
                for r, a, f, t in corrections
            ],
        }
    return latest


def _file_mtime(path):
    try:
        return datetime.fromtimestamp(os.path.getmtime(path), timezone.utc) \
            .strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return None


def filter_budget_issues(issues):
    """从 multica issue list 结果中提取带 budget.* 的条目（纯函数，可测）。

    issues: list[dict]（含 id/identifier/title/status/metadata）
    返回: [{issue, identifier, title, status, ceiling, spent, variance}]
    """
    out = []
    for it in issues:
        md = it.get("metadata") or {}
        keys = [k for k in md if k.startswith("budget.")]
        if not keys:
            continue
        entry = {
            "issue": it.get("id"),
            "identifier": it.get("identifier"),
            "title": it.get("title"),
            "status": it.get("status"),
            "ceiling": md.get("budget.ceiling"),
            "spent": md.get("budget.spent"),
            "variance": md.get("budget.variance"),
        }
        out.append(entry)
    out.sort(key=lambda x: x["identifier"] or "")
    return out


def parse_pending_escalated(issues):
    """统计 pending / escalated 状态 issue 数（rating.status 口径）。"""
    stats = {"pending": 0, "escalated": 0, "credited": 0}
    for it in issues:
        md = it.get("metadata") or {}
        s = md.get("rating.status")
        if s in stats:
            stats[s] += 1
    return stats


# ---------------------------------------------------------------- CLI 读取（best-effort）

def run_cli(args):
    try:
        result = subprocess.run(
            ["multica"] + args, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return None
        return result.stdout
    except Exception:
        return None


def load_budget(limit=200):
    """通过 multica issue list 读预算 metadata；CLI 不可用返回 (None, "CLI 不可用")。"""
    out = run_cli(["issue", "list", "--limit", str(limit), "--output", "json"])
    if not out:
        return None, "multica issue list 不可用（离线？）"
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None, "multica 返回 JSON 解析失败"
    issues = data.get("issues", data) if isinstance(data, dict) else data
    if not isinstance(issues, list):
        return None, "multica 返回结构异常"
    return filter_budget_issues(issues), None


def load_rating_stats(limit=200):
    """统计 rating.status 分布（异常中心/运行态用）。"""
    out = run_cli(["issue", "list", "--limit", str(limit), "--output", "json"])
    if not out:
        return None, None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None, None
    issues = data.get("issues", data) if isinstance(data, dict) else data
    if not isinstance(issues, list):
        return None, None
    return parse_pending_escalated(issues), None


def load_cli_categories():
    """读 multica agent list 的 R-42 `[category=X]` 标签（best-effort）。"""
    cats = {}
    out = run_cli(["agent", "list", "--output", "json"])
    if not out:
        return cats
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return cats
    if not isinstance(data, list):
        return cats
    for agent in data:
        if not isinstance(agent, dict) or not agent.get("name"):
            continue
        cat = agent.get("category") or agent.get("agent.category")
        if not cat:
            m = DESC_CATEGORY_RE.search(agent.get("description") or "")
            if m:
                cat = m.group(1)
        if cat and cat in VALID_CATEGORIES:
            cats[NORM_RE.sub("", agent["name"].lower())] = cat
    return cats


# ---------------------------------------------------------------- 组装

def current_month():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def current_quarter():
    now = datetime.now(timezone.utc)
    return f"{now.year}-Q{(now.month - 1) // 3 + 1}"


def discover_agents(agents_root, dirs):
    """档案目录 ∪ 事件/月度/季度目录（稳定排序）——与聚合器 list_agents 同源。"""
    agents = set()
    profiles_root = os.path.join(agents_root, "profiles")
    for root in (profiles_root, dirs["events"], dirs["monthly"], dirs["quarterly"]):
        if os.path.isdir(root):
            for name in os.listdir(root):
                if os.path.isdir(os.path.join(root, name)):
                    agents.add(name)
    return sorted(agents)


def discover_months(dirs):
    """扫描 events 与 monthly 下全部月份（排序）。"""
    months = set()
    for base in (dirs["events"], dirs["monthly"]):
        if os.path.isdir(base):
            for agent_dir in os.listdir(base):
                apath = os.path.join(base, agent_dir)
                if not os.path.isdir(apath):
                    continue
                for fn in os.listdir(apath):
                    stem = fn[:-3] if fn.endswith(".md") else fn
                    if MONTH_RE.match(stem):
                        months.add(stem)
    return sorted(months)


def discover_quarters(dirs):
    quarters = set()
    if os.path.isdir(dirs["quarterly"]):
        for agent_dir in os.listdir(dirs["quarterly"]):
            apath = os.path.join(dirs["quarterly"], agent_dir)
            if not os.path.isdir(apath):
                continue
            for fn in os.listdir(apath):
                stem = fn[:-3] if fn.endswith(".md") else fn
                if QUARTER_RE.match(stem):
                    quarters.add(stem)
    return sorted(quarters)


def runtime_state(agents_root, dirs):
    """运行态：四任务 last-run 时基 + pending/escalated 计数。"""
    def latest_mtime(root):
        best = None
        if os.path.isdir(root):
            for base, _, files in os.walk(root):
                for fn in files:
                    ts = _file_mtime(os.path.join(base, fn))
                    if ts and (best is None or ts > best):
                        best = ts
        return best

    return {
        "settlement_last_run": latest_mtime(dirs["events"]),
        "aggregation_last_run": latest_mtime(dirs["monthly"]),
        "review_last_run": latest_mtime(dirs["quarterly"]),
        "budget_reconciliation": None,   # 由预算页对账状态填充
    }


def build_feed(agents_root, months, quarters, agents, use_cli=True):
    dirs = scoring_dirs(agents_root)
    profiles_root = os.path.join(agents_root, "profiles")
    benchmarks = load_benchmarks(agents_root)
    cli_cats = load_cli_categories() if use_cli else {}

    agent_list = []
    for agent in agents:
        cat, cat_src = resolve_category(agent, profiles_root, cli_cats)
        agent_list.append({
            "name": agent,
            "category": cat,
            "category_source": cat_src,
            "benchmark": get_benchmark(cat, benchmarks),
            "profile_exists": os.path.isfile(
                os.path.join(profiles_root, agent, "capabilities.md")),
        })

    monthly = {}
    for month in months:
        by_agent = {}
        for agent in agents:
            res = parse_monthly_report(
                os.path.join(dirs["monthly"], agent, f"{month}.md"))
            if res is not None:
                by_agent[agent] = res
        if by_agent:
            monthly[month] = by_agent

    quarterly = {}
    for quarter in quarters:
        by_agent = {}
        for agent in agents:
            res = parse_quarterly_form(
                os.path.join(dirs["quarterly"], agent, f"{quarter}.md"))
            if res is not None:
                by_agent[agent] = res
        if by_agent:
            quarterly[quarter] = by_agent

    events = {}
    for month in months:
        by_agent = {}
        for agent in agents:
            res = parse_events_file(
                os.path.join(dirs["events"], agent, f"{month}.md"))
            if res is not None and res["rows"]:
                by_agent[agent] = res
        if by_agent:
            events[month] = by_agent

    distortion = {}
    for quarter in quarters:
        by_agent = {}
        for agent in agents:
            res = parse_anti_distortion_log(
                os.path.join(dirs["anti_distortion"], agent, f"{quarter}.md"))
            if res is not None:
                by_agent[agent] = res
        if by_agent:
            distortion[quarter] = by_agent

    budget = None
    budget_note = None
    rating_stats = None
    rating_note = None
    if use_cli:
        budget, budget_note = load_budget()
        rating_stats, rating_note = load_rating_stats()
    else:
        budget_note = "offline（--no-cli）"

    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "agents_root": agents_root,
            "months": months,
            "quarters": quarters,
            "schema_version": "1.0",
            "read_only": True,
        },
        "agents": agent_list,
        "monthly": monthly,
        "quarterly": quarterly,
        "events": events,
        "anti_distortion": distortion,
        "budget": {"entries": budget, "note": budget_note},
        "runtime": {
            **runtime_state(agents_root, dirs),
            "rating_status": rating_stats,
            "rating_status_note": rating_note,
        },
    }


def main():
    parser = argparse.ArgumentParser(description="智能看板只读数据接口 (dashboard-data-feed)")
    parser.add_argument("--agents-dir", default=AGENTS_ROOT_DEFAULT,
                        help="agents 根目录（默认取脚本上级）")
    parser.add_argument("--month", help="月份 YYYY-MM（默认当前月）")
    parser.add_argument("--quarter", help="季度 YYYY-Qn（默认当前季度）")
    parser.add_argument("--agent", help="仅输出指定智能体")
    parser.add_argument("--all", action="store_true", help="扫描全部月份/季度")
    parser.add_argument("--no-cli", action="store_true",
                        help="离线：不调用 multica（预算/运行态计数缺省）")
    parser.add_argument("--pretty", action="store_true", help="缩进输出 JSON")
    args = parser.parse_args()

    agents_root = os.path.abspath(args.agents_dir)
    dirs = scoring_dirs(agents_root)

    if args.month and not MONTH_RE.match(args.month):
        print(f"❌ 月份格式非法: {args.month}", file=sys.stderr)
        sys.exit(2)
    if args.quarter and not QUARTER_RE.match(args.quarter):
        print(f"❌ 季度格式非法: {args.quarter}", file=sys.stderr)
        sys.exit(2)

    if args.all:
        months = discover_months(dirs)
        quarters = discover_quarters(dirs)
    else:
        months = [args.month] if args.month else [current_month()]
        quarters = [args.quarter] if args.quarter else [current_quarter()]

    agents = discover_agents(agents_root, dirs)
    if args.agent:
        if args.agent not in agents:
            print(f"❌ 未找到智能体: {args.agent}", file=sys.stderr)
            sys.exit(1)
        agents = [args.agent]
    if not agents:
        print("❌ 未找到任何智能体数据目录", file=sys.stderr)
        sys.exit(1)

    feed = build_feed(agents_root, months, quarters, agents, use_cli=not args.no_cli)
    print(json.dumps(feed, ensure_ascii=False, indent=2 if args.pretty else None))


if __name__ == "__main__":
    main()
