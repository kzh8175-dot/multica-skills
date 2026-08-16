#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rating-aggregator.py — 评分聚合器（方案C P0-1）

职责: 将 `reviews/scoring/events/{agent}/YYYY-MM.md` 积分事件流水
  聚合为月度百分制（R-41），再汇总为季度客观分（R-51）。

规则:
  R-41  月度百分制 = clamp(月积分 ÷ 基准月积分 × 100, 0, 120)
  R-42  类别 → 基准月积分（共享配置 rating-benchmarks.conf）:
        execution=400 / data=350 / marketing=350 / creative=300 / technical=300 / default=300
  R-51  季度客观分 = (M1 + M2 + M3) / 3；缺失月按 E-01 排除（不计入分母）

幂等:
  - 输出文件内容仅依赖 (agent, 周期, 事件流水)，与运行时间无关；
  - 写文件采用「临时文件 + os.replace」原子替换；
  - 目标内容与现有文件一致时跳过写入。

异常（对齐 rating-settler.py 的 error code 风格，标记而非崩溃）:
  E_MISS   缺少事件流水文件
  E_EMPTY  流水文件存在但无有效积分行
  E_PARSE  流水存在无法解析的数据行（跳过并标记）
  E_CAT    无法确定类别（无档案且无法推断）

用法:
  python3 rating-aggregator.py                     # 当前月 + 当前季度（全部智能体）
  python3 rating-aggregator.py --month 2026-08     # 仅聚合指定月份
  python3 rating-aggregator.py --quarter 2026-Q3   # 仅聚合指定季度
  python3 rating-aggregator.py --month 2026-08 --quarter 2026-Q3
  python3 rating-aggregator.py --dry-run           # 预演，不产生任何写入
  python3 rating-aggregator.py --all               # 扫描 events 下全部月份/季度
  python3 rating-aggregator.py --no-cli-categories # 离线/测试：不从 CLI 读 R-42 类别
  python3 rating-aggregator.py --agents-dir <路径>  # 指定 agents 根（测试用）
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

# 错误码（与 rating-settler.py 风格一致）
E_MISS = "E_MISS"      # 缺少事件流水
E_EMPTY = "E_EMPTY"    # 流水存在但无有效积分行
E_PARSE = "E_PARSE"    # 流水存在无法解析的行
E_CAT = "E_CAT"        # 无法确定类别

# 兜底基准（共享配置缺失时使用，与 review-scheduler.sh 内置默认一致）
FALLBACK_BENCHMARKS = {
    "execution": 400,
    "data": 350,
    "marketing": 350,
    "creative": 300,
    "technical": 300,
    "default": 300,
}
VALID_CATEGORIES = ("execution", "data", "marketing", "creative", "technical")

POINTS_RE = re.compile(r"^[+-]?\d+$")
QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")
MONTH_RE = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")

# 与 review-scheduler.sh get_agent_category() 的关键词推断保持一致的兜底映射
KEYWORD_CATEGORIES = [
    # 执行/运营/客服类
    (("运营", "客服", "零售", "Jira", "会议"), "execution"),
    # 数据/分析/财务类
    (("财务", "分析", "数据", "实验", "趋势", "文档"), "data"),
    # 营销/增长/内容类
    (("抖音", "快手", "小红书", "知乎", "微博", "增长", "内容", "社媒",
      "营销", "播客", "轮播", "出版", "微信", "B站"), "marketing"),
    # 战略/设计/创意类
    (("战略", "品牌", "视觉", "UI", "设计", "产品"), "creative"),
    # 系统/技术/架构类
    (("架构", "身份", "自动化", "流程", "工作流", "SEO", "搜索",
      "本地化", "视频", "剪辑"), "technical"),
]


# ---------------------------------------------------------------- 路径

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 脚本位于 agents/capability-system/ 下，agents 根即上一级
AGENTS_ROOT_DEFAULT = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))


def scoring_dirs(agents_root):
    """按规则书 7.2 返回 (events, monthly, quarterly) 目录。"""
    base = os.path.join(agents_root, "reviews", "scoring")
    return (
        os.path.join(base, "events"),
        os.path.join(base, "monthly"),
        os.path.join(base, "quarterly"),
    )


def config_path(agents_root):
    return os.path.join(agents_root, "capability-system", "rating-benchmarks.conf")


def profiles_dir(agents_root):
    return os.path.join(agents_root, "profiles")


# ---------------------------------------------------------------- 配置与类别

def load_benchmarks(agents_root):
    """读取共享配置 rating-benchmarks.conf；缺失/异常时回退内置默认。"""
    bench = dict(FALLBACK_BENCHMARKS)
    path = config_path(agents_root)
    if not os.path.exists(path):
        return bench
    try:
        with open(path, encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if key and value.isdigit():
                    bench[key] = int(value)
    except OSError as e:
        print(f"  ⚠️ 读取共享配置失败，使用内置默认: {e}", file=sys.stderr)
    return bench


def get_benchmark(category, benchmarks):
    """类别 → 基准月积分；未知类别回退 default。"""
    if category in benchmarks:
        return benchmarks[category]
    return benchmarks.get("default", FALLBACK_BENCHMARKS["default"])


def keyword_category(agent_name):
    """按名称关键词推断类别（兜底，与 review-scheduler.sh 一致）。"""
    for keywords, cat in KEYWORD_CATEGORIES:
        if any(k in agent_name for k in keywords):
            return cat
    return "execution"


def profile_category(agent_name, profiles_root):
    """从能力档案读取 `category` 标签（支持 category=X / category: X 等写法）。"""
    profile_file = os.path.join(profiles_root, agent_name, "capabilities.md")
    if not os.path.exists(profile_file):
        return None
    try:
        with open(profile_file, encoding="utf-8") as f:
            for line in f:
                m = re.search(r"category[=: ]+\s*([a-z]+)", line)
                if m:
                    cand = m.group(1).lower()
                    if cand in VALID_CATEGORIES:
                        return cand
    except OSError:
        pass
    return None


DESC_CATEGORY_RE = re.compile(r"\[category\s*=\s*([a-z]+)\]")


def _norm_name(name):
    """归一化智能体名（忽略空格/短横，小写），用于跨来源匹配。"""
    return re.sub(r"[\s\-]", "", name or "").lower()


def load_cli_categories():
    """从 multica agent list 读取 R-42 category（P0-2 已落标）。

    优先取显式 `category`/`agent.category` 字段（平台预留），否则解析
    `agent.description` 中的 `[category=X]` 标签 —— 这是 R-42 映射的实际
    载体（`tag-agent-categories.py` 写入）。键按 `_norm_name` 归一化，
    兼容档案目录名（空格/短横差异）。
    返回 {归一化agent名: 类别}；CLI 不可用或无标签时返回空 dict。
    该调用是 best-effort，失败不影响聚合。
    """
    cats = {}
    try:
        result = subprocess.run(
            ["multica", "agent", "list", "--output", "json"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            return cats
        data = json_loads(result.stdout)
        if not isinstance(data, list):
            return cats
        for agent in data:
            if not isinstance(agent, dict):
                continue
            name = agent.get("name")
            if not name:
                continue
            cat = agent.get("category") or agent.get("agent.category")
            if not cat:
                m = DESC_CATEGORY_RE.search(agent.get("description") or "")
                if m:
                    cat = m.group(1)
            if cat and cat in VALID_CATEGORIES:
                cats[_norm_name(name)] = cat
    except Exception:
        pass
    return cats


def json_loads(text):
    import json
    try:
        return json.loads(text)
    except Exception:
        return None


def resolve_category(agent_name, profiles_root, cli_cats):
    """类别解析: CLI(R-42 `[category=X]`) → 档案 category 标签 → 关键词推断。

    返回 (category, flag)。flag 仅当能力档案缺失时返回 E_CAT
    （P0-2 打标前无标签属正常，关键词推断是已文档化的兜底，不标记）。
    """
    norm = _norm_name(agent_name)
    if norm in cli_cats:
        return cli_cats[norm], None
    profile_file = os.path.join(profiles_root, agent_name, "capabilities.md")
    if os.path.exists(profile_file):
        pc = profile_category(agent_name, profiles_root)
        if pc:
            return pc, None
        return keyword_category(agent_name), None
    # 档案缺失（E-03 线索）→ 仍用关键词推断兜底，并标记
    return keyword_category(agent_name), E_CAT


# ---------------------------------------------------------------- 事件解析

def parse_events_file(events_path, events_dir_rel):
    """解析单月事件流水。

    返回 (total, anomalies):
      total      月积分合计（int）；文件缺失返回 None
      anomalies  [(error_code, 描述), ...]
    """
    if not os.path.exists(events_path):
        return None, [(E_MISS, f"缺少事件流水 {events_dir_rel}")]

    total = 0
    anomalies = []
    valid_rows = 0
    try:
        with open(events_path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as e:
        return 0, [(E_MISS, f"读取流水失败: {e}")]

    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("|----") or line.startswith("|---"):
            continue  # 表头分隔行
        if not line.startswith("|"):
            continue  # 非表格行（如注释）
        fields = [f.strip() for f in line.strip("|").split("|")]
        # 表头行（无积分数字）直接跳过
        if len(fields) < 4:
            # 表格行但列数不足 → 跳过该条并记告警（不中断）
            anomalies.append(
                (E_PARSE, f"{events_dir_rel}:{lineno} 表格行列数不足，已跳过: {line[:60]}")
            )
            continue
        points_field = fields[-1]  # 去掉首尾 | 后，最后一列即积分列
        if points_field in ("积分", "---", ":---:"):
            continue
        if POINTS_RE.match(points_field):
            total += int(points_field)
            valid_rows += 1
        else:
            # 数据行但积分列无法解析 → 标记（不崩溃）
            ts = fields[0] if fields else "?"
            event = fields[-2] if len(fields) >= 2 else "?"
            anomalies.append(
                (E_PARSE, f"{events_dir_rel}:{lineno} 积分列无法解析 "
                          f"(时间={ts}, 事件={event}, 值={points_field})")
            )

    if valid_rows == 0 and not anomalies:
        anomalies.append((E_EMPTY, f"事件流水为空或无有效积分行 {events_dir_rel}"))
    return total, anomalies


# ---------------------------------------------------------------- 计算

def monthly_percent(total, benchmark):
    """R-41: clamp(月积分 ÷ 基准月积分 × 100, 0, 120)（整数除法，与调度器口径一致）。"""
    if benchmark <= 0:
        return 0
    score = total * 100 // benchmark
    return max(0, min(120, score))


def quarterly_score(monthly_scores):
    """R-51: (M1 + M2 + M3) / 3（整数除法，与 review-scheduler.sh 口径一致）。

    季度恒取 3 个月；缺失月按 0 计并标记 E_MISS（在报告 flags 中体现）。
    如需排除缺失月，由负责人按 E-01 裁定（本函数不自动排除）。
    """
    if not monthly_scores:
        return 0
    return sum(m["score"] for m in monthly_scores) // 3


# ---------------------------------------------------------------- 渲染

def render_monthly(agent, month, category, benchmark, total, score, flags, events_dir_rel):
    lines = [
        f"# {agent} - 月度积分报告",
        "",
        f"**月份**: {month}",
        f"**类别**: {category}",
        f"**基准月积分**: {benchmark}",
        "**规则**: R-41 月度百分制 = clamp(月积分 ÷ 基准月积分 × 100, 0, 120)",
        "",
        "## 月度汇总",
        "",
        "| 项目 | 数值 |",
        "|------|:---:|",
        f"| 月积分 | {total if total is not None else 0} |",
        f"| 基准月积分 | {benchmark} |",
        f"| 月度百分制 | {score} |",
    ]
    if flags:
        lines.append("")
        for code, msg in flags:
            lines.append(f"> ⚠️ {code}: {msg}")
    lines.append("")
    lines.append(
        f"**月度百分制** = clamp({total if total is not None else 0} ÷ {benchmark} × 100, "
        f"0, 120) = **{score}**"
    )
    return "\n".join(lines) + "\n"


def render_quarterly_fresh(agent, quarter, category, benchmark, rows, score, flags):
    """全新季度客观分报告（目标路径无历史人评表单时写入）。"""
    lines = [
        f"# {agent} - 季度客观分报告",
        "",
        f"**季度**: {quarter}",
        f"**类别**: {category}",
        f"**基准月积分**: {benchmark}",
        "**规则**: R-51 季度客观分 = (M1 + M2 + M3) / 3（缺失月按 0 计并标记）",
        "",
        "## 季度客观分",
        "",
        "| 月份 | 积分 | 基准 | 百分制 |",
        "|------|:---:|:---:|:---:|",
    ]
    for m in rows:
        total = m["total"] if m["total"] is not None else 0
        lines.append(f"| {m['month']} | {total} | {m['benchmark']} | {m['score']} |")
    terms = "+".join(str(m["score"]) for m in rows)
    lines.append("")
    lines.append(f"**季度客观分** = ({terms}) / 3 = **{score}**")
    if flags:
        lines.append("")
        for code, msg in flags:
            lines.append(f"> ⚠️ {code}: {msg}")
    return "\n".join(lines) + "\n"


def render_quarterly_section(agent, quarter, category, benchmark, rows, score, flags, events_dir_rel):
    """与 review-scheduler.sh 兼容的『一、季度客观分』段落（用于更新既有表单）。"""
    lines = [
        "## 一、季度客观分（系统自动汇总，权重80%）",
        "",
        "| 月份 | 积分 | 基准 | 百分制(上限120) |",
        "|------|:---:|:---:|:---:|",
    ]
    for m in rows:
        total = m["total"] if m["total"] is not None else 0
        lines.append(f"| {m['month']} | {total} | {m['benchmark']} | {m['score']} |")
    terms = "+".join(str(m["score"]) for m in rows)
    lines.append("")
    lines.append(f"**季度客观分** = 3个月均值 = **{score}** 分（({terms}) / 3）")
    lines.append("")
    lines.append(f"> ⚠️ 上表积分流水若缺失请补记: {events_dir_rel}/{{agent}}/YYYY-MM.md")
    lines.append("> 缺失月份按 0 计入均值并标记（如需排除缺失月，由负责人按 E-01 裁定）。")
    for code, msg in flags:
        lines.append(f"> ⚠️ {code}: {msg}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- 写入

def atomic_write(path, content):
    """原子写: 临时文件 + os.replace；内容与现有文件一致时跳过。"""
    content_bytes = content.encode("utf-8")
    if os.path.exists(path):
        try:
            with open(path, "rb") as f:
                if f.read() == content_bytes:
                    return False  # 无变化，不写
        except OSError:
            pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content_bytes)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    return True


def write_quarterly_report(path, section_block, fresh_body):
    """写季度报告，兼容已有调度器人评表单。

    若目标文件已含 '## 一、' 与 '## 二、'（review-scheduler.sh 人评表单），
    仅替换『一、季度客观分』段落，保留人评区（二~六）。
    """
    existing = None
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                existing = f.read()
        except OSError:
            existing = None
    if existing and "## 一、" in existing and "## 二、" in existing:
        head = existing[: existing.index("## 一、")]
        tail = existing[existing.index("## 二、"):]
        return atomic_write(path, head + section_block + "\n" + tail)
    return atomic_write(path, fresh_body)


# ---------------------------------------------------------------- 周期工具

def current_month():
    return datetime.now(timezone.utc).strftime("%Y-%m")


def current_quarter():
    now = datetime.now(timezone.utc)
    q = (now.month - 1) // 3 + 1
    return f"{now.year}-Q{q}"


def quarter_months(quarter):
    """'2026-Q3' → ['2026-07','2026-08','2026-09']。"""
    m = QUARTER_RE.match(quarter)
    if not m:
        return None
    year, q = m.group(1), int(m.group(2))
    start = (q - 1) * 3 + 1
    return [f"{year}-{mo:02d}" for mo in range(start, start + 3)]


def month_to_quarter(month):
    """'2026-08' → '2026-Q3'。"""
    m = MONTH_RE.match(month)
    if not m:
        return None
    year, mo = m.group(1), int(m.group(2))
    return f"{year}-Q{(mo - 1) // 3 + 1}"


def discover_months(events_dir):
    """扫描 events/{agent}/*.md，返回排序后的月份集合。"""
    months = set()
    if os.path.isdir(events_dir):
        for agent_dir in os.listdir(events_dir):
            apath = os.path.join(events_dir, agent_dir)
            if not os.path.isdir(apath):
                continue
            for fn in os.listdir(apath):
                if MONTH_RE.match(fn[:-3] if fn.endswith(".md") else fn):
                    months.add(fn[:-3])
    return sorted(months)


def list_agents(profiles_root, events_dir):
    """返回待聚合的智能体名列表：档案目录 ∪ 事件流水目录（保持稳定排序）。"""
    agents = set()
    if os.path.isdir(profiles_root):
        for name in os.listdir(profiles_root):
            if os.path.isdir(os.path.join(profiles_root, name)):
                agents.add(name)
    if os.path.isdir(events_dir):
        for name in os.listdir(events_dir):
            if os.path.isdir(os.path.join(events_dir, name)):
                agents.add(name)
    return sorted(agents)


def find_profile_name(agent_name, profiles_root):
    """把事件流水里的智能体名映射到档案目录名（容忍 空格/短横 差异）。"""
    target = _norm_name(agent_name)
    if os.path.isdir(profiles_root):
        for name in sorted(os.listdir(profiles_root)):
            if _norm_name(name) == target:
                return name
    return agent_name


# ---------------------------------------------------------------- 主流程

def aggregate_month(agent, month, ctx, dry_run, written, skipped):
    """聚合单个智能体单月，返回月度百分制结果 dict；返回 None 表示跳过。"""
    events_dir, monthly_dir, _ = ctx["dirs"]
    profiles_root = ctx["profiles_root"]
    benchmarks = ctx["benchmarks"]
    cli_cats = ctx["cli_cats"]

    profile_name = find_profile_name(agent, profiles_root)
    category, cat_flag = resolve_category(profile_name, profiles_root, cli_cats)
    benchmark = get_benchmark(category, benchmarks)
    events_path = os.path.join(events_dir, agent, f"{month}.md")
    events_dir_rel = os.path.join("reviews", "scoring", "events", agent, f"{month}.md")

    total, anomalies = parse_events_file(events_path, events_dir_rel)
    flags = list(anomalies)
    if cat_flag:
        flags.append((cat_flag, f"无法确定类别，按关键词推断为 {category}"))

    score = monthly_percent(total if total is not None else 0, benchmark)

    out_path = os.path.join(monthly_dir, agent, f"{month}.md")
    content = render_monthly(agent, month, category, benchmark,
                             total if total is not None else 0, score, flags, events_dir_rel)
    if dry_run:
        status = "DRY-RUN"
    else:
        changed = atomic_write(out_path, content)
        status = "写入" if changed else "已是最新(跳过)"
    print(f"  {'🔍' if dry_run else ('📝' if status == '写入' else '⏭️')} "
          f"{agent} {month} → {score}分 [{category}/{benchmark}] {status}")
    if status == "写入":
        written.append(out_path)
    else:
        skipped.append(out_path)
    return {
        "agent": agent, "month": month, "category": category,
        "benchmark": benchmark, "total": total if total is not None else 0,
        "score": score, "flags": flags,
    }


def aggregate_quarter(agent, quarter, ctx, dry_run, written, skipped):
    """聚合单个智能体单季度。"""
    events_dir, _, quarterly_dir = ctx["dirs"]
    profiles_root = ctx["profiles_root"]
    benchmarks = ctx["benchmarks"]
    cli_cats = ctx["cli_cats"]

    months = quarter_months(quarter)
    profile_name = find_profile_name(agent, profiles_root)
    category, cat_flag = resolve_category(profile_name, profiles_root, cli_cats)
    benchmark = get_benchmark(category, benchmarks)
    events_dir_rel = os.path.join("reviews", "scoring", "events")

    rows = []
    flags = []
    for month in months:
        events_path = os.path.join(events_dir, agent, f"{month}.md")
        total, anomalies = parse_events_file(events_path,
                                             os.path.join(events_dir_rel, agent, f"{month}.md"))
        row = {
            "month": month,
            "total": total,
            "benchmark": benchmark,
            "score": monthly_percent(total if total is not None else 0, benchmark),
            "flags": list(anomalies),
        }
        rows.append(row)
        flags.extend((code, f"{month}: {msg}") for code, msg in anomalies)

    score = quarterly_score(rows)
    if cat_flag:
        flags.append((cat_flag, f"无法确定类别，按关键词推断为 {category}"))

    out_path = os.path.join(quarterly_dir, agent, f"{quarter}.md")
    section_block = render_quarterly_section(
        agent, quarter, category, benchmark, rows, score, flags, events_dir_rel)
    fresh_body = render_quarterly_fresh(
        agent, quarter, category, benchmark, rows, score, flags)
    if dry_run:
        status = "DRY-RUN"
    else:
        changed = write_quarterly_report(out_path, section_block, fresh_body)
        status = "写入" if changed else "已是最新(跳过)"
    print(f"  {'🔍' if dry_run else ('📝' if status == '写入' else '⏭️')} "
          f"{agent} {quarter} → 客观分{score} [{category}/{benchmark}] {status}")
    if status == "写入":
        written.append(out_path)
    else:
        skipped.append(out_path)
    return {"agent": agent, "quarter": quarter, "score": score, "flags": flags}


def main():
    parser = argparse.ArgumentParser(description="评分聚合器 (rating-aggregator)")
    parser.add_argument("--dry-run", action="store_true", help="预演，不产生任何写入")
    parser.add_argument("--month", help="仅聚合指定月份 YYYY-MM")
    parser.add_argument("--quarter", help="仅聚合指定季度 YYYY-Qn")
    parser.add_argument("--all", action="store_true",
                        help="扫描 events 下全部月份及其所在季度")
    parser.add_argument("--no-cli-categories", action="store_true",
                        help="不读取 multica agent list 的 R-42 category（离线/测试用）")
    parser.add_argument("--agents-dir", default=AGENTS_ROOT_DEFAULT,
                        help="agents 根目录（默认取脚本上级，测试用）")
    parser.add_argument("--quiet", action="store_true", help="只输出汇总")
    args = parser.parse_args()

    agents_root = os.path.abspath(args.agents_dir)
    events_dir, monthly_dir, quarterly_dir = scoring_dirs(agents_root)
    profiles_root = profiles_dir(agents_root)
    benchmarks = load_benchmarks(agents_root)
    cli_cats = {} if args.no_cli_categories else load_cli_categories()

    ctx = {
        "dirs": (events_dir, monthly_dir, quarterly_dir),
        "profiles_root": profiles_root,
        "benchmarks": benchmarks,
        "cli_cats": cli_cats,
    }

    print("=== 评分聚合器 (rating-aggregator) ===")
    print(f"agents 根: {agents_root}")
    print(f"模式: {'DRY-RUN' if args.dry_run else '正常聚合'}")
    print()

    # 校验参数
    if args.month and not MONTH_RE.match(args.month):
        print(f"❌ 月份格式非法: {args.month}（应为 YYYY-MM）")
        sys.exit(2)
    if args.quarter and not QUARTER_RE.match(args.quarter):
        print(f"❌ 季度格式非法: {args.quarter}（应为 YYYY-Qn）")
        sys.exit(2)

    # 确定要聚合的 (month, quarter) 集合
    #   --month 指定月 / --quarter 指定季度 / 均不指定 → 当前月 + 当前季度
    months_to_run = []
    quarters_to_run = []
    if args.all:
        found = discover_months(events_dir)
        months_to_run = found
        for m in found:
            q = month_to_quarter(m)
            if q and q not in quarters_to_run:
                quarters_to_run.append(q)
    else:
        if args.month:
            months_to_run = [args.month]
        elif not args.quarter:
            months_to_run = [current_month()]
        if args.quarter:
            quarters_to_run = [args.quarter]
        elif not args.month:
            quarters_to_run = [current_quarter()]

    agents = list_agents(profiles_root, events_dir)
    if not agents:
        print("❌ 未找到任何智能体档案/事件流水目录")
        sys.exit(1)
    print(f"智能体数量: {len(agents)}")
    print(f"聚合月份: {months_to_run}")
    print(f"聚合季度: {quarters_to_run}")
    print()

    written = []
    skipped = []
    stats = {"agents": len(agents), "monthly": 0, "quarterly": 0}

    # 月度聚合
    if months_to_run:
        print(f"—— 月度聚合（{len(agents)} 个智能体 × {len(months_to_run)} 个月）——")
        for agent in agents:
            for month in months_to_run:
                try:
                    r = aggregate_month(agent, month, ctx, args.dry_run, written, skipped)
                    if r:
                        stats["monthly"] += 1
                except Exception as e:
                    # 单个智能体异常 → 记告警、跳过该条，不中断全量聚合
                    print(f"  ⚠️ 跳过 {agent} {month}: 聚合异常 {e}", file=sys.stderr)
        print()

    # 季度聚合
    if quarters_to_run:
        print(f"—— 季度聚合（{len(agents)} 个智能体 × {len(quarters_to_run)} 个季度）——")
        for agent in agents:
            for quarter in quarters_to_run:
                try:
                    r = aggregate_quarter(agent, quarter, ctx, args.dry_run, written, skipped)
                    if r:
                        stats["quarterly"] += 1
                except Exception as e:
                    # 单个智能体异常 → 记告警、跳过该条，不中断全量聚合
                    print(f"  ⚠️ 跳过 {agent} {quarter}: 聚合异常 {e}", file=sys.stderr)
        print()

    # 汇总
    print("========== 聚合汇总 ==========")
    print(f"  智能体: {stats['agents']}")
    print(f"  月度报告: {stats['monthly']}")
    print(f"  季度报告: {stats['quarterly']}")
    if args.dry_run:
        print(f"  写入: 0（DRY-RUN 不产生任何写入）")
    else:
        print(f"  实际写入: {len(written)}")
        print(f"  无变化跳过: {len(skipped)}")
    print(f"  结果目录: {os.path.join(agents_root, 'reviews', 'scoring')}")


if __name__ == "__main__":
    main()
