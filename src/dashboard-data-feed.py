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
  R-61  季度综合分 = 客观分 × 0.6 + 人评最终分 × 0.4
  R-62~66 等级查表: ≥95 S / ≥85 A / ≥70 B / ≥60 C / <60 D
  R-71  红线事件 ≥2 → 等级上限 C；R-72 缺自评 ≥2 → 降一档；E-02 单评分人 → 上限 A

「人评待运行·预估值」约定: 季度表单尚未被 judge 判定时，
  comprehensive / grade 为 null，同时给出 objective_only 口径的
  comprehensive_estimate / grade_estimate 供 UI 以「预估值」标注呈现，
  并附 as_of 时基（聚合器最后一次写报告的时间）。

幂等/只读: 本脚本不写评分数据；唯一写入是 CLI 本地快照（见下），
  路径由调用方用 --cli-snapshot 指定；同输入必得同输出。

CLI 数据源与本地快照（KA-355 · 对治「exit=0 但静默发布非确定性降级数据」）:
  类别（R-42）/ 预算 / rating.status 三个数据源来自 `multica` CLI，而平台侧
  会出现与响应体大小无关的随机超时（实测失败固定发生在 CLI 默认 HTTP 超时
  10.0s，连续 6 次 `agent list` 失败 2/6）。CLI 失败时**不得**回退到语义不同的
  兜底源 —— `resolve_category()` 回退到档案 category / 关键词推断会让 11 个
  智能体（实测 95 中 11）换类别，基准分、预算上限、agent 深链 slug 一起漂移
  （实测总预算上限在 99300/100350 之间跳变）。故：
    ① CLI 成功 → 结果写入本地快照（原子写）并作为本次取值；
    ② CLI 失败 → 取**同一来源的上一次成功快照**，输出与上次一致（同输入同输出），
       并带 as_of 时基；
    ③ 无快照 / 快照过期 → source="missing"（或由调用方按 age 判定超龄），
       调用方据此**非 0 退出**并拒绝覆盖已发布产物（恢复「失败即告警」）。
  快照是「同来源的旧值」，与「换一个来源的兜底值」性质不同：前者只是陈旧，
  后者是错误 —— 后者会被下游（结算/聚合/看板）当成真实口径。

用法:
  python3 dashboard-data-feed.py                          # 当前月+当前季度，全部智能体
  python3 dashboard-data-feed.py --agents-dir <根>         # 指定 agents 根（默认取脚本上级）
  python3 dashboard-data-feed.py --month 2026-08 --quarter 2026-Q3
  python3 dashboard-data-feed.py --agent "开发者工具工程师"  # 仅单智能体
  python3 dashboard-data-feed.py --pretty                   # 缩进 JSON
  python3 dashboard-data-feed.py --no-cli                   # 离线：跳过 multica（预算/运行态缺省）
  python3 dashboard-data-feed.py --cli-snapshot <路径>      # CLI 本地快照落点（默认不写）
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
AGENTS_ROOT_DEFAULT = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))

MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")
QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")
POINTS_RE = re.compile(r"^[+-]?\d+$")
RULE_RE = re.compile(r"^(R-\d+)")  # 事件描述中的规则号，如 'R-21:自评' → 'R-21'

# KA-114 迁移口径（与 rating-aggregator.py 同源）：R-21 自评 / R-22 档案纪律
# 计入历史基线，不计入新版权重。事件流水页仍完整展示全部行（含自评/纪律），
# 但 events.total（看板「月积分」/manifest 指纹）按新口径剔除。
SELF_REVIEW_PREFIXES = ("R-21",)
DISCIPLINE_PREFIXES = ("R-22",)

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

# 平台侧类别 → 评分系统类别（与 rating-aggregator.py KA-356 / sync-agents-to-rating.py
# 的 CAT_MAP 同源）。不做映射时 `engineering`/`management` 会被判为非法类别而丢弃，
# 看板回退到档案/关键词推断 —— 而聚合器把它们映射为 technical/execution，
# 同一智能体在 R-41 报告与看板上的类别/基准分就此分叉（KA-355 口径对齐）。
CAT_MAP = {"engineering": "technical", "management": "execution"}

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


def split_event_points(event_desc, pts):
    """单行多事件拆分（KA-154 · 与聚合器 split_event_points 同口径）。

    事件描述可含多个 `;` 分隔子事件（如 `R-21:自评;R-22:更新能力档案;R-23:协作反馈`）。
    行积分按子事件数均分（余数给前几条）；无 `;` 时整行为单个事件、保留整行积分。
    返回 [(rule, desc, sub_pts), ...]；子事件无 `R-\d+` 规则号时 rule 为 ""。
    """
    parts = [p.strip() for p in (event_desc or "").split(";") if p.strip()]
    if not parts:
        parts = [event_desc or ""]
    n = len(parts)
    out = []
    for i, part in enumerate(parts):
        if ":" in part:
            code, _, desc = part.partition(":")
            code, desc = code.strip(), desc.strip()
        else:
            code, desc = part, part
        m = RULE_RE.match(code)
        rule = m.group(1) if m else ""
        sub_pts = pts if n == 1 else pts // n + (1 if i < pts % n else 0)
        out.append((rule, desc, sub_pts))
    return out


def parse_events_file(path):
    """解析事件流水 → {total, rows: [{time, issue, event, points}], flags}。

    points 列无法解析的行记入 flags（与聚合器 E_PARSE 同源，不中断）。
    文件缺失返回 None。

    KA-114 + KA-154 迁移口径：`total` 剔除 R-21 自评 / R-22 档案纪律（计入
    历史基线、不计入新版权重，与聚合器一致）；单行多事件（`;` 分隔）按子事件
    拆分、积分均分（余数给前几条），R-23 等子事件计入 total；`rows` 仍完整
    返回全部行（事件流水页由生成层 `split_events` 拆分呈现）。
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
            # 新口径（KA-114 + KA-154）：单行多事件拆分后，R-21/R-22 子事件
            # 不参与 total，其余子事件按拆分积分计入（rows 保留完整基线）
            for rule, _sub_desc, sub_pts in split_event_points(fields[2], row["points"]):
                if rule in SELF_REVIEW_PREFIXES or rule in DISCIPLINE_PREFIXES:
                    continue
                total += sub_pts
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

# CLI 侧参数（KA-355）。HTTP 超时由 `MULTICA_HTTP_TIMEOUT` 环境变量控制，
# 默认 10s；调用方（包装脚本）应按 KA-333 约定前置 export MULTICA_HTTP_TIMEOUT=60。
CLI_TIMEOUT_SECONDS = 60      # subprocess 级兜底，防 CLI 自身卡死
CLI_ATTEMPTS = 3              # 平台健康时的瞬时超时可被重试吃掉
CLI_RETRY_BASE_DELAY = 2.0    # 指数退避 2s / 4s

CLI_SNAPSHOT_SCHEMA = 1
CLI_SNAPSHOT_SECTIONS = ("categories", "issue_scan")


def _utcnow(now=None):
    return now or datetime.now(timezone.utc)


def _iso(now=None):
    return _utcnow(now).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_cli(args):
    """执行 `multica <args>` → stdout 字符串；失败（含超时）退避重试后返回 None。

    KA-355: 单次调用失败是常态（实测 `agent list` 连续 6 次失败 2/6，
    失败固定发生在 CLI 默认 HTTP 超时 10.0s）。退避重试能把**平台健康时的
    瞬时抖动**吃掉；平台整体降级时重试救不回来 —— 那种场景由调用方按
    resolve_cli_source() 的 source/age 走快照或失败路径，不再静默降级。
    """
    delay = CLI_RETRY_BASE_DELAY
    for attempt in range(1, CLI_ATTEMPTS + 1):
        try:
            result = subprocess.run(
                ["multica"] + args, capture_output=True, text=True,
                timeout=CLI_TIMEOUT_SECONDS)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout
        except Exception:
            pass
        if attempt < CLI_ATTEMPTS:
            time.sleep(delay)
            delay *= 2
    return None


def read_cli_snapshot(path):
    """读 CLI 本地快照 → {section: {"as_of": iso, "value": ...}}。

    缺失 / 损坏 / schema 不符一律返回 {}（按「无快照」处理，由调用方失败）。
    """
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or data.get("schema") != CLI_SNAPSHOT_SCHEMA:
        return {}
    sections = data.get("sections")
    return sections if isinstance(sections, dict) else {}


def update_cli_snapshot(path, section, value, now=None):
    """把某数据源的最新成功结果并入快照（原子写，其余 section 保留）。

    写失败不影响本次取值（快照是加速器，不是正确性依赖）——但下次仍会
    走 live，不会因此发布错误数据。
    """
    if not path:
        return
    sections = read_cli_snapshot(path)
    sections[section] = {"as_of": _iso(now), "value": value}
    tmp = f"{path}.tmp"
    try:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"schema": CLI_SNAPSHOT_SCHEMA, "sections": sections},
                      f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _age_hours(as_of, now=None):
    try:
        ts = datetime.strptime(as_of, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return max(0.0, (_utcnow(now) - ts).total_seconds() / 3600.0)


def evaluate_cli_sources(cli_sources, max_stale_hours=26):
    """判定 CLI 数据源是否可用于**发布** → (ok, failures, degraded)。

    ok=False 时调用方必须非 0 退出并**拒绝覆盖已发布产物**（保留上一次正确产物，
    恢复「失败即告警」）。判定口径：
      missing            → 失败（没读到，且没有可用的同来源旧值）
      ok=False           → 失败
      snapshot 且超龄    → 失败（快照比 max_stale_hours 更旧 = 已跨过一个完整刷新周期）
      snapshot 未超龄    → 降级（可用，但必须标注新鲜度）
      cli / offline      → 正常
    max_stale_hours=None 表示不设上限（只在观测期手工运行使用）。
    """
    failures, degraded = [], []
    for name, status in (cli_sources or {}).items():
        status = status or {}
        source = status.get("source")
        if source == "offline":
            continue
        if not status.get("ok") or source == "missing":
            failures.append(f"{name}: {status.get('note') or '数据源不可用'}")
            continue
        if source == "snapshot":
            age = status.get("age_hours")
            if age is None:
                failures.append(f"{name}: 快照缺少可解析时基（as_of="
                                f"{status.get('as_of')}），无法判定新鲜度")
            elif max_stale_hours is not None and age > max_stale_hours:
                failures.append(
                    f"{name}: 快照超龄 {age:.1f}h > {max_stale_hours}h"
                    f"（as_of {status.get('as_of')}）")
            else:
                age_txt = f"{age:.1f}h 前" if age is not None else "时基未知"
                degraded.append(
                    f"{name}: 取本地快照（{age_txt}，as_of {status.get('as_of')}）")
    return (not failures), failures, degraded


def resolve_cli_source(name, fetch, snapshot_path=None, use_cli=True, now=None):
    """解析一个 CLI 数据源 → (value, status)。

    status = {name, source, ok, as_of, age_hours, note}
      source: "cli"      live 成功（已写入快照）
              "snapshot" CLI 不可用，取同一来源的上一次成功快照
              "missing"  CLI 不可用且无快照 —— 调用方应失败
              "offline"  显式 --no-cli，本就不取该源

    fetch() 必须遵守「失败返回 None」而**不是**返回空值 —— 空字典在语义上
    是「成功但没有数据」（如 95 个智能体里确实没有带 R-42 标签的），
    与「没读到」必须可区分，这正是 KA-355 的失效点。
    """
    if not use_cli:
        return None, {"name": name, "source": "offline", "ok": True,
                      "as_of": None, "age_hours": None, "note": "offline（--no-cli）"}
    note = None
    try:
        value = fetch()
    except Exception as exc:                      # 数据源自身异常视同不可用
        value = None
        note = f"{type(exc).__name__}: {exc}"
    if value is not None:
        update_cli_snapshot(snapshot_path, name, value, now=now)
        return value, {"name": name, "source": "cli", "ok": True,
                       "as_of": _iso(now), "age_hours": 0.0, "note": note}
    section = read_cli_snapshot(snapshot_path).get(name) or {}
    cached = section.get("value")
    if cached is not None:
        as_of = section.get("as_of")
        return cached, {"name": name, "source": "snapshot", "ok": True,
                        "as_of": as_of, "age_hours": _age_hours(as_of, now),
                        "note": f"{name}: multica CLI 不可用，取本地快照（{as_of}）"}
    return None, {"name": name, "source": "missing", "ok": False,
                  "as_of": None, "age_hours": None,
                  "note": note or f"{name}: multica CLI 不可用且无本地快照"}


def _parse_cli_agents(data):
    """multica agent list 的 list 载荷 → [{name,id,category,archived,description}]。

    平台侧 `engineering`/`management` 经 CAT_MAP 映射（与聚合器同源）。
    """
    agents = []
    for agent in data:
        if not isinstance(agent, dict) or not agent.get("name"):
            continue
        cat = agent.get("category") or agent.get("agent.category")
        if not cat:
            m = DESC_CATEGORY_RE.search(agent.get("description") or "")
            if m:
                cat = m.group(1)
        cat = CAT_MAP.get(cat, cat)
        if cat not in VALID_CATEGORIES:
            cat = None
        agents.append({
            "name": agent["name"],
            "id": agent.get("id"),
            "category": cat,
            "archived": bool(agent.get("archived_at")),
            "description": agent.get("description") or "",
        })
    return agents


def fetch_cli_agents():
    """live 成员表；CLI 不可用返回 None（区别于「成功但列表为空」）。"""
    out = run_cli(["agent", "list", "--output", "json"])
    if not out:
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, list):
        return None
    return _parse_cli_agents(data)


def load_cli_agents():
    """读 multica agent list 的实时成员表（best-effort，成员页同步数据源）。

    返回 list[dict]（每名成员一条：{name, id, category, archived, description}）；
    以**列表**返回而不按规范化名建字典，是因为「UI 设计师」与「UI设计师」是两个
    不同成员，按 norm 去键会互相覆盖。CLI 不可用 / 返回结构异常时返回 []。

    注意: `[]` 无法区分「CLI 失败」与「平台确实没有成员」。需要该区分时用
    `fetch_cli_agents()`（失败返回 None），或直接读 build_feed 的 meta.cli_sources。
    """
    return fetch_cli_agents() or []


def fetch_cli_categories():
    """live R-42 类别表 {归一化名: 类别}；CLI 不可用返回 None。

    返回 {} 是**合法**的（CLI 成功但无任何智能体带 R-42 标签），
    与 None（没读到）语义不同 —— 调用方据此决定是否走快照/失败。
    """
    agents = fetch_cli_agents()
    if agents is None:
        return None
    cats = {}
    for rec in agents:
        if rec.get("category"):
            cats[NORM_RE.sub("", rec["name"].lower())] = rec["category"]
    return cats


def load_cli_categories():
    """读 multica agent list 的 R-42 `[category=X]` 标签（best-effort）。

    CLI 不可用时返回 {}（旧行为，保留兼容）。build_feed 内部改用
    fetch_cli_categories() 以便区分「失败」与「无标签」。
    """
    return fetch_cli_categories() or {}


def fetch_all_issues(page_size=200, max_pages=25):
    """分页拉取全量 issue（multica issue list --limit/--offset）。

    单次 `--limit 200` 会在工作区 issue >200 时静默截断尾部，导致预算条目
    与 rating.status 计数遗漏（KA-98 #7）。本函数按页拉取，直到空页 / 非满页 /
    has_more=false / 达最大页数，并对分页期间新插入的 issue 按 id 去重。

    返回 (issues, note):
      issues  合并后的全量 issue 列表；首页即失败返回 None
      note    非致命降级说明（后续页失败 / 达最大页数），正常为 None
    """
    collected = []
    offset = 0
    note = None
    for page in range(1, max_pages + 1):
        out = run_cli(["issue", "list", "--limit", str(page_size),
                       "--offset", str(offset), "--output", "json"])
        if not out:
            if not collected:
                return None, "multica issue list 不可用（离线？）"
            note = f"第 {page} 页拉取失败，已返回前 {len(collected)} 条"
            break
        try:
            data = json.loads(out)
        except json.JSONDecodeError:
            if not collected:
                return None, "multica 返回 JSON 解析失败"
            note = f"第 {page} 页 JSON 解析失败，已返回前 {len(collected)} 条"
            break
        issues = data.get("issues", data) if isinstance(data, dict) else data
        if not isinstance(issues, list):
            if not collected:
                return None, "multica 返回结构异常"
            note = f"第 {page} 页结构异常，已返回前 {len(collected)} 条"
            break
        if not issues:
            break
        collected.extend(issues)
        has_more = data.get("has_more") if isinstance(data, dict) else None
        if has_more is False or len(issues) < page_size:
            break
        offset += page_size
    else:
        note = f"已达最大分页数（{max_pages} 页 × {page_size} 条），结果可能不完整"

    # 分页期间工作区可能插入新 issue，offset 分页会重复/偏移：按 id 去重
    seen = set()
    deduped = []
    for it in collected:
        if isinstance(it, dict):
            iid = it.get("id")
            if iid is not None and iid in seen:
                continue
            if iid is not None:
                seen.add(iid)
        deduped.append(it)
    return deduped, note


def load_budget(limit=200):
    """通过 multica issue list 分页读预算 metadata；CLI 不可用返回 (None, "CLI 不可用")。"""
    issues, note = fetch_all_issues(page_size=limit)
    if issues is None:
        return None, note
    return filter_budget_issues(issues), note


def load_rating_stats(limit=200):
    """统计 rating.status 分布（异常中心/运行态用）；分页拉取避免 >limit 截断。"""
    issues, note = fetch_all_issues(page_size=limit)
    if issues is None:
        return None, note
    return parse_pending_escalated(issues), note


ORG_SECTION_RE = re.compile(r"^\[department\s+(.+)\]$")


def load_org_chart(agents_root):
    """解析 org-chart.conf → 部门归属表 {成员精确名: dept_name}。

    兼容两种登记格式（KA-114 B-2 统一后新格式为唯一格式）：
      ① 新格式（单行）：`部门名|主管|成员1|成员2|...` —— `|` 拆分，
         首字段部门名，第 3 字段起为成员（主管须为成员之首）；
      ② 旧格式（兼容保留）：`[department X]` 段 + `members=成员1,成员2,...`。
    顶层评分链锚点键（`ORG_*`，`KEY=VALUE` 且 KEY 全大写）不计入部门。
    文件缺失返回 {}。
    注意：以**精确名**为键（「UI 设计师」与「UI设计师」是两个不同成员），
    规范化（去空格/短横）匹配由调用方在确无精确命中时兜底。
    """
    path = os.path.join(agents_root, "capability-system", "org-chart.conf")
    if not os.path.exists(path):
        path = os.path.join(agents_root, "config", "org-chart.conf")
    if not os.path.exists(path):
        return {}
    org = {}
    dept = None
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.split("#", 1)[0].strip()
                if not line:
                    continue
                # 顶层评分链锚点键（ORG_TOP_SUPERVISOR / ORG_OWNER / ORG_LEAD_REVIEWER2）
                # 非部门登记行，跳过（与 test-org-chart-conf.py 同口径）
                if "=" in line and line.split("=", 1)[0].strip().isupper():
                    continue
                # 新格式：`部门名|主管|成员1|成员2|...`
                if "|" in line:
                    parts = [p.strip() for p in line.split("|")]
                    if len(parts) >= 3 and parts[0] and parts[1] and parts[2]:
                        dept_name = parts[0]
                        for member in parts[2:]:
                            if member:
                                org[member] = dept_name
                    continue
                # 旧格式：`[department X]` 段 + `members=...`
                m = ORG_SECTION_RE.match(line)
                if m:
                    dept = m.group(1)
                    continue
                if dept and line.startswith("members"):
                    members_csv = line.split("=", 1)[1].strip()
                    for member in [x.strip() for x in members_csv.split(",") if x.strip()]:
                        org[member] = dept
    except OSError:
        pass
    return org


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


def fetch_issue_scan():
    """一次分页拉取 issue 全量 → {"budget": [...], "rating_status": {...}}。

    预算与 rating.status 同源于 `issue list`，合并成一次拉取（KA-355）：
    既省一半请求，也把「会不会撞上平台抖动」的窗口减半 —— 原先两次
    独立拉取，任一次失败就各自降级，产出更容易在两次运行间跳变。
    CLI 不可用返回 None。
    """
    issues, note = fetch_all_issues()
    if issues is None:
        return None
    return {
        "budget": filter_budget_issues(issues),
        "rating_status": parse_pending_escalated(issues),
        "note": note,
    }


def build_feed(agents_root, months, quarters, agents, use_cli=True,
               cli_snapshot_path=None, now=None):
    dirs = scoring_dirs(agents_root)
    profiles_root = os.path.join(agents_root, "profiles")
    benchmarks = load_benchmarks(agents_root)

    # CLI 数据源（KA-355）：live → 本地快照 → missing。missing 由调用方
    # （generate-dashboard-data.py）判定为失败并非 0 退出。
    cli_cats, cats_status = resolve_cli_source(
        "categories", fetch_cli_categories, cli_snapshot_path, use_cli, now)
    scan, scan_status = resolve_cli_source(
        "issue_scan", fetch_issue_scan, cli_snapshot_path, use_cli, now)

    agent_list = []
    for agent in agents:
        cat, cat_src = resolve_category(agent, profiles_root, cli_cats or {})
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

    if use_cli:
        scan = scan or {}
        budget = scan.get("budget")
        rating_stats = scan.get("rating_status")
        # scan_status.note = 源不可用/取快照；scan.note = 分页期间的部分降级。
        # 两者都要透出，否则「拿到了数据」会把「数据可能不完整」盖掉。
        notes = [n for n in (scan_status.get("note"), scan.get("note")) if n]
        budget_note = rating_note = " / ".join(notes) or None
    else:
        budget = None
        rating_stats = None
        budget_note = "offline（--no-cli）"
        rating_note = "offline（--no-cli）"

    return {
        "meta": {
            "generated_at": _iso(now),
            "agents_root": agents_root,
            "months": months,
            "quarters": quarters,
            "schema_version": "1.0",
            "read_only": True,
            # CLI 数据源的可观测面（KA-355）：每个源给出来源/时基/年龄，
            # 调用方据此判失败，看板据此标注新鲜度。
            "cli_sources": {
                "categories": cats_status,
                "issue_scan": scan_status,
            },
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
    parser.add_argument("--cli-snapshot", default=None,
                        help="CLI 本地快照路径（KA-355）：CLI 成功时写入、失败时取用；"
                             "缺省不写快照（纯离线/测试）")
    parser.add_argument("--pretty", action="store_true", help="缩进输出 JSON")
    args = parser.parse_args()

    if args.cli_snapshot:
        args.cli_snapshot = os.path.abspath(args.cli_snapshot)

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

    feed = build_feed(agents_root, months, quarters, agents, use_cli=not args.no_cli,
                      cli_snapshot_path=args.cli_snapshot)
    print(json.dumps(feed, ensure_ascii=False, indent=2 if args.pretty else None))

    # CLI 数据源完全缺失（连快照都没有）→ 输出里的类别是语义不同的兜底值，
    # 不是真实口径；以非 0 退出，避免被当成正常数据消费（KA-355）。
    missing = [f"{name}: {(st or {}).get('note')}"
               for name, st in (feed["meta"]["cli_sources"] or {}).items()
               if (st or {}).get("source") == "missing"]
    if missing:
        print("❌ CLI 数据源不可用且无本地快照（输出含兜底类别，非真实口径）:",
              file=sys.stderr)
        for line in missing:
            print(f"   - {line}", file=sys.stderr)
        print("   处理: 重试 / 检查 `multica agent list` / 传 --cli-snapshot 启用快照；"
              "离线请显式加 --no-cli。", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    main()
