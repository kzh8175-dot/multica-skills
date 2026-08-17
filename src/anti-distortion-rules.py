#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
anti-distortion-rules.py — 防失真修正层（方案C P1-10 / KA-75）

职责: 将季度人评自动判定（auto_grade）结合事件流水中 R-31/R-32 计数，
输出最终等级与修正记录（R-71 红线上限 C / R-72 缺自评降档）。

纯函数模块（ADR-0001）: 模块自身无副作用：
  - count_distortion_events()  统计季度内 R-31/R-32 次数（只读）
  - apply_anti_distortion()    纯函数：R-72 先降档 → R-71 最后封顶
  - write_decision_log()       唯一写入口（append-only 决策日志，幂等）
  - summarize()                生成人评表单「四、防失真校验」段摘要

流水线位置（spec 2.1）:
  [每日结算] rating-settler.py          → 事件流水 events/{agent}/YYYY-MM.md
  [月末聚合] rating-aggregator.py       → 月度百分制 + 季度客观分
  [季度人评] quarterly-review-judge.py  → auto_grade            ← P1-9 前置
  [防失真修正] 本模块                   → final_grade + corrections ← P1-10
  [裁定]     资深战略领导者             → 终审（override 能力）

判定算法（spec 2.3，终审 B-3 顺序）:
  输入: auto_grade ∈ {S,A,B,C,D}；counts = {r31, r32}；single_reviewer ∈ {false,true}
  1. grade ← auto_grade
  2. 若 single_reviewer 且 grade 优于 A：grade ← A；记录 E-02 修正（封顶 A）
  3. 若 r32 ≥ r72_threshold：grade ← demote(grade, 1)；记录 R-72 修正
     demote 到 D 为止（D 为地板，不再下探）
  4. 若 r31 ≥ r71_threshold：grade ← cap(grade, r71_cap)；记录 R-71 修正
     cap 取「更差者」：S/A/B → C；C → C；D → D（封顶不抬升 D；R-71 为最终硬性上限）
  5. 返回 final_grade = grade

失败模式（spec 4）: fail-open 原则 —— 事件数据缺失/异常时不惩罚（按 0 计）；
  惩罚必须建立在可信计数之上，反向风险（应罚未罚）由负责人裁定兜底。

用法:
  python3 anti-distortion-rules.py count --events-dir <dir> --agent <名> --months YYYY-MM,...
  python3 anti-distortion-rules.py check --events-dir <dir> --agent <名> --months YYYY-MM,...
  python3 anti-distortion-rules.py apply --auto-grade S --events-dir <dir> --agent <名> --months YYYY-MM,...
"""

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone

# ---------------------------------------------------------------- 规则常量

GRADES = ("S", "A", "B", "C", "D")           # 从优到劣
GRADE_INDEX = {g: i for i, g in enumerate(GRADES)}

DEFAULT_CONFIG = {
    "r71_threshold": 2,   # 季度内 R-31 次数阈值
    "r72_threshold": 2,   # 季度内 R-32 次数阈值
    "r71_cap": "C",       # R-71 等级上限
}

# 事件列前缀解析：'R-31:违反约束' / 'R-31：违反约束' → 'R-31'（半角/全角冒号归一化，
# N-4）；多事件以 ';' 分隔（与 rating-settler 写流水格式契约一致：事件列首字段恒为 R-xx:）
EVENT_SEG_RE = re.compile(r"^R-(\d+)[：:]")
DISTORTION_EVENTS = {"31", "32"}

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


# ---------------------------------------------------------------- 数据类

@dataclass
class RuleCorrection:
    rule: str            # "E-02" | "R-71" | "R-72"
    action: str          # "cap" | "demote"
    reason: str
    from_grade: str
    to_grade: str


@dataclass
class AntiDistortionResult:
    auto_grade: str
    final_grade: str
    counts: dict
    corrections: list
    config: dict
    single_reviewer: bool = False


# ---------------------------------------------------------------- 计数

def count_distortion_events(events_dir, agent, quarter_months):
    """统计季度内 R-31/R-32 次数。

    按事件列前缀解析（'R-31:违反约束' → 'R-31'），按 (issue, event_id) 去重，
    仅统计 quarter_months 内的月份。文件缺失/读取失败：该月计 0（fail-open）。
    返回 {"r31": int, "r32": int}。
    """
    counts = {"r31": 0, "r32": 0}
    seen = set()
    if not events_dir or not os.path.isdir(events_dir):
        return counts
    agent_dir = os.path.join(events_dir, agent)
    for month in quarter_months:
        if not MONTH_RE.match(month or ""):
            continue
        path = os.path.join(agent_dir, f"{month}.md")
        if not os.path.isfile(path):
            continue  # fail-open：该月计 0
        try:
            with open(path, encoding="utf-8") as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line.startswith("|"):
                        continue
                    fields = [f.strip() for f in line.strip("|").split("|")]
                    if len(fields) < 3:
                        continue  # 表头/分隔行或列数不足
                    issue, event_desc = fields[1], fields[2]
                    for seg in event_desc.split(";"):
                        m = EVENT_SEG_RE.match(seg.strip())
                        if not m or m.group(1) not in DISTORTION_EVENTS:
                            continue
                        ev_id = f"R-{m.group(1)}"
                        key = (issue, ev_id)
                        if key in seen:
                            continue
                        seen.add(key)
                        counts[f"r{m.group(1)}"] += 1
        except OSError:
            continue  # fail-open
    return counts


# ---------------------------------------------------------------- 判定

def demote(grade, steps=1):
    """降档，到 D 为止（D 为地板）。"""
    idx = GRADE_INDEX[grade]
    return GRADES[min(idx + steps, len(GRADES) - 1)]


def apply_anti_distortion(auto_grade, counts, single_reviewer=False, config=None):
    """纯函数：E-02 → R-72 → R-71（终审 B-3 顺序，R-71 为最终硬性上限）。

    E-02: single_reviewer=True 时封顶 A（评审置信度约束，置于最前）；
    R-72: 降一档（D 为地板）；R-71: 封顶 r71_cap（取更差者，不抬升）。
    返回 AntiDistortionResult: auto_grade / final_grade / counts /
    corrections[RuleCorrection(rule, action, reason, from_grade, to_grade)]。
    无副作用；非法入参抛 ValueError。
    """
    if auto_grade not in GRADES:
        raise ValueError(f"auto_grade 非法: {auto_grade!r}（应为 {GRADES}）")
    cfg = dict(DEFAULT_CONFIG)
    if config:
        cfg.update({k: v for k, v in config.items() if k in DEFAULT_CONFIG})
    r71_cap = cfg["r71_cap"]
    if r71_cap not in GRADES:
        raise ValueError(f"r71_cap 非法: {r71_cap!r}（应为 {GRADES}）")

    r31 = int(counts.get("r31", 0) or 0)
    r32 = int(counts.get("r32", 0) or 0)
    grade = auto_grade
    corrections = []

    # 1. E-02 先封顶 A（单评分人；仅当 grade 优于 A 时生效，A/B/C/D 不抬升）
    if single_reviewer and GRADE_INDEX[grade] < GRADE_INDEX["A"]:
        from_g = grade
        grade = "A"
        corrections.append(RuleCorrection(
            rule="E-02", action="cap",
            reason="单评分人，等级上限 A",
            from_grade=from_g, to_grade=grade))

    # 2. R-72 降一档（D 为地板）
    if r32 >= int(cfg["r72_threshold"]):
        from_g = grade
        to_g = demote(grade, 1)
        corrections.append(RuleCorrection(
            rule="R-72", action="demote",
            reason=f"缺自评事件 {r32} ≥ 阈值 {cfg['r72_threshold']}",
            from_grade=from_g, to_grade=to_g))
        grade = to_g

    # 3. R-71 最后封顶（硬性上限，不抬升更差等级）
    if r31 >= int(cfg["r71_threshold"]):
        from_g = grade
        if GRADE_INDEX[grade] < GRADE_INDEX[r71_cap]:
            grade = r71_cap
        corrections.append(RuleCorrection(
            rule="R-71", action="cap",
            reason=f"红线事件 {r31} ≥ 阈值 {cfg['r71_threshold']}",
            from_grade=from_g, to_grade=grade))

    return AntiDistortionResult(
        auto_grade=auto_grade,
        final_grade=grade,
        counts={"r31": r31, "r32": r32},
        corrections=corrections,
        config=cfg,
        single_reviewer=single_reviewer,
    )


# ---------------------------------------------------------------- 摘要与留痕

def summarize(result):
    """生成人评表单「四、防失真校验」段的人类可读摘要。"""
    cfg = result.config or DEFAULT_CONFIG
    r31 = result.counts.get("r31", 0)
    r32 = result.counts.get("r32", 0)
    # 触发状态以计数为准（与 apply_anti_distortion 的阈值判断同源）；
    # 兼容 counts-only 结果（无 corrections，如调度器表单预检）
    r71_triggered = r31 >= int(cfg["r71_threshold"])
    r72_triggered = r32 >= int(cfg["r72_threshold"])
    lines = []
    if result.single_reviewer:
        lines.append("E-02 单评分人: 是 → 等级上限 A")
    lines += [
        f"R-31 红线事件: {r31} 次（阈值 {cfg['r71_threshold']}）→ "
        + (f"触发 R-71：等级上限 {cfg['r71_cap']}" if r71_triggered else "未触发"),
        f"R-32 缺自评事件: {r32} 次（阈值 {cfg['r72_threshold']}）→ "
        + ("触发 R-72：等级降一档" if r72_triggered else "未触发"),
    ]
    if result.auto_grade:
        for c in result.corrections:
            arrow = "→" if c.to_grade != c.from_grade else "→（等级不变）"
            lines.append(f"  {c.rule} {c.action}: {c.from_grade} {arrow} {c.to_grade}（{c.reason}）")
        lines.append(f"最终等级: {result.final_grade}")
    return "\n".join(lines)


def _decision_sig(result):
    """判定决策签名（排除时间戳，保证同一次判定幂等可识别）。

    N-6（终审）：对齐 sha256 —— 判定输入的规范化 JSON 的 sha256 全量摘要
    （原实现为 sha1 截断 12 位，联调时统一）。
    """
    canonical = json.dumps({
        "auto_grade": result.auto_grade,
        "final_grade": result.final_grade,
        "counts": result.counts,
        "corrections": [
            {"rule": c.rule, "action": c.action,
             "from_grade": c.from_grade, "to_grade": c.to_grade,
             "reason": c.reason}
            for c in result.corrections
        ],
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def write_decision_log(agents_root, agent, quarter, result):
    """追加写入 reviews/scoring/anti-distortion/{agent}/{quarter}.md（append-only）。

    内容含：auto_grade、counts、触发规则编号、from→to、时间戳。
    幂等：同一次判定（quarter + 决策签名）重复调用不产生重复记录。
    返回文件路径。
    """
    log_dir = os.path.join(agents_root, "reviews", "scoring", "anti-distortion", agent)
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, f"{quarter}.md")
    sig = f"{quarter}:{_decision_sig(result)}"
    marker = f"<!-- sig: {sig} -->"

    content = ""
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                content = fh.read()
        except OSError:
            content = ""
    if marker in content:
        return path  # 幂等：同一次判定已记录

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry_lines = [
        f"\n### {ts} · 防失真判定（{quarter}）",
        f"{marker}",
        f"- auto_grade: {result.auto_grade}",
        f"- counts: r31={result.counts.get('r31', 0)}, "
        f"r32={result.counts.get('r32', 0)}",
        "- corrections:",
    ]
    if result.corrections:
        for c in result.corrections:
            entry_lines.append(
                f"  - {c.rule} {c.action}: {c.from_grade} → {c.to_grade}（{c.reason}）")
    else:
        entry_lines.append("  - （无）")
    entry_lines.append(f"- final_grade: {result.final_grade}")
    entry = "\n".join(entry_lines) + "\n"

    with open(path, "a", encoding="utf-8") as fh:
        if not content.strip():
            fh.write(f"# {agent} - 防失真决策日志（append-only）\n")
        fh.write(entry)
    return path


# ---------------------------------------------------------------- CLI

def parse_months(value):
    months = [m.strip() for m in value.split(",") if m.strip()]
    for m in months:
        if not MONTH_RE.match(m):
            raise argparse.ArgumentTypeError(f"月份格式非法: {m!r}（应为 YYYY-MM）")
    return months


def main():
    parser = argparse.ArgumentParser(description="防失真修正层（方案C P1-10）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_count = sub.add_parser("count", help="统计季度内 R-31/R-32 次数（只读）")
    p_count.add_argument("--events-dir", required=True,
                         help="事件流水根目录 reviews/scoring/events")
    p_count.add_argument("--agent", required=True, help="智能体名称")
    p_count.add_argument("--months", required=True, type=parse_months,
                         help="季度内月份，逗号分隔（如 2026-07,2026-08,2026-09）")
    p_count.add_argument("--json", action="store_true")

    p_check = sub.add_parser("check", help="生成防失真校验摘要（供人评表单「四、」区）")
    p_check.add_argument("--events-dir", required=True)
    p_check.add_argument("--agent", required=True)
    p_check.add_argument("--months", required=True, type=parse_months)
    p_check.add_argument("--json", action="store_true")

    p_apply = sub.add_parser("apply", help="应用防失真规则输出最终等级")
    p_apply.add_argument("--auto-grade", required=True, choices=GRADES)
    p_apply.add_argument("--single-reviewer", action="store_true",
                         help="单评分人（E-02：等级上限 A）")
    p_apply.add_argument("--events-dir", required=True)
    p_apply.add_argument("--agent", required=True)
    p_apply.add_argument("--months", required=True, type=parse_months)
    p_apply.add_argument("--json", action="store_true")

    args = parser.parse_args()

    if args.cmd == "count":
        counts = count_distortion_events(args.events_dir, args.agent, args.months)
        if args.json:
            print(json.dumps(counts, ensure_ascii=False))
        else:
            print(f"r31={counts['r31']} r32={counts['r32']}")

    elif args.cmd == "check":
        counts = count_distortion_events(args.events_dir, args.agent, args.months)
        result = AntiDistortionResult(
            auto_grade="", final_grade="",
            counts=counts, corrections=[], config=dict(DEFAULT_CONFIG))
        text = summarize(result)
        if args.json:
            print(json.dumps({"r31": counts["r31"], "r32": counts["r32"],
                              "summary": text}, ensure_ascii=False))
        else:
            print(text)

    elif args.cmd == "apply":
        counts = count_distortion_events(args.events_dir, args.agent, args.months)
        result = apply_anti_distortion(args.auto_grade, counts,
                                       single_reviewer=args.single_reviewer)
        if args.json:
            print(json.dumps({
                "auto_grade": result.auto_grade,
                "final_grade": result.final_grade,
                "counts": result.counts,
                "corrections": [
                    {"rule": c.rule, "action": c.action, "reason": c.reason,
                     "from_grade": c.from_grade, "to_grade": c.to_grade}
                    for c in result.corrections],
            }, ensure_ascii=False, indent=2))
        else:
            print(summarize(result))


if __name__ == "__main__":
    main()
