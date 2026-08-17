#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
quarterly-review-judge.py — 季度人评表单自动判定（方案C P1-9 / KA-74）

职责: 对 `reviews/scoring/quarterly/{agent}/{quarter}.md` 季度人评表单，
自动判定四要素并回填表单：
  1. 客观分   R-51 季度客观分（rating-aggregator.py 写入「一、」区，本脚本只读取）
  2. 人评分   R-52 单评分人 = Σ(维度分 × 权重) × 20；R-53 人评最终分 = 各评分人平均
  3. 综合分   R-61 客观分 × 0.8 + 人评最终分 × 0.2
  4. 等级     R-62~R-66 查表 S/A/B/C/D（**原始等级 auto_grade**，未经防失真修正）

防失真修正（P1-10 / KA-75 联调）:
  本脚本只输出 原始等级 + single_reviewer 表单事实，R-71/R-72/E-02 修正统一委托
  `anti-distortion-rules.apply_anti_distortion(auto_grade, counts, single_reviewer)`
  计算（防失真模块唯一权威，B-1/B-3），并由本脚本调用 `write_decision_log` 留痕。
  旧 `parse_anti_fraud()`（读表单文本触发标记）与 `apply_caps()` 中 R-71/R-72 分支
  已退役：修正必须建立在事件流水结构化计数之上，不再依赖表单文案。

表单是客观分（聚合器）与人评维度分（人工填写）的「纯函数」：只要维度分就绪，
本脚本即可把 人评分/综合分/等级 自动判定并回填；人工如需调整判定，应修改输入
（维度分）而非直接改输出区，重跑即同步（--dry-run 先行预览）。

幂等:
  - 输出仅依赖（表单内容 + 人评维度分 + 事件流水计数），与运行时间无关；
  - 写入采用「临时文件 + os.replace」原子替换，内容不变跳过；
  - 决策日志由 `anti-distortion-rules.write_decision_log` 幂等追加（判定签名去重）；
  - 人评维度分未填时 no-op（标记待填写，exit 0），可安全重跑。

用法:
  python3 quarterly-review-judge.py                          # 当前季度全部表单
  python3 quarterly-review-judge.py --quarter 2026-Q3        # 指定季度
  python3 quarterly-review-judge.py --agent "开发者工具工程师"  # 指定智能体
  python3 quarterly-review-judge.py --dry-run                # 预演，不写
  python3 quarterly-review-judge.py --status                 # 只读状态，不写
  python3 quarterly-review-judge.py --json                   # 汇总输出 JSON
  python3 quarterly-review-judge.py --agents-dir <路径>       # 指定 agents 根（测试用）
"""

import argparse
import importlib.util
import os
import re
import sys
import tempfile
from datetime import datetime, timezone

# ---------------------------------------------------------------- 规则常量

# R-62~R-66 等级表（下限 → 等级）；与 review-scheduler.sh 表单模板一致
GRADE_TABLE = [
    (95, "S"), (85, "A"), (70, "B"), (60, "C"),
]
GRADE_DEFAULT = "D"
GRADE_ORDER = ["S", "A", "B", "C", "D"]

# 标准 5 维度权重（%）——仅作校验基准；实际权重从表单表头逐行解析
DEFAULT_DIMENSIONS = [("交付质量", 30), ("专业能力", 25), ("自我优化", 20),
                      ("协作与沟通", 15), ("任务完成度", 10)]

QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")
DIM_LINE_RE = re.compile(r"^##\s+二、")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 与 rating-aggregator.py 约定一致：脚本位于 agents/capability-system/（或仓库 src/）下，
# agents 根即上一级；测试通过 --agents-dir 显式指定。
AGENTS_ROOT_DEFAULT = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))


def load_anti_distortion():
    """加载防失真修正模块（与 judge 同目录；生产镜像 agents/capability-system/ 同约定）。

    返回模块对象；加载失败返回 None → 调用方 fail-open（不应用修正，
    仅输出原始等级并标注，与 spec 4 fail-open 原则一致）。
    """
    candidates = [
        os.path.join(SCRIPT_DIR, "anti-distortion-rules.py"),
        os.path.join(os.path.normpath(os.path.join(SCRIPT_DIR, "..", "agents")),
                     "capability-system", "anti-distortion-rules.py"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                spec = importlib.util.spec_from_file_location(
                    "anti_distortion_rules", path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                return mod
            except Exception:
                continue
    return None


_ANTI_MOD = load_anti_distortion()


# ---------------------------------------------------------------- 路径

def scoring_dirs(agents_root):
    """返回 (events, monthly, quarterly) 目录。"""
    base = os.path.join(agents_root, "reviews", "scoring")
    return (
        os.path.join(base, "events"),
        os.path.join(base, "monthly"),
        os.path.join(base, "quarterly"),
    )


def current_quarter():
    now = datetime.now(timezone.utc)
    q = (now.month - 1) // 3 + 1
    return f"{now.year}-Q{q}"


def quarter_months(quarter):
    """YYYY-Qn → 该季度 3 个月份列表（如 2026-Q3 → ['2026-07','2026-08','2026-09']）。"""
    m = QUARTER_RE.match(quarter or "")
    if not m:
        raise ValueError(f"季度格式非法: {quarter!r}（应为 YYYY-Qn）")
    year = int(m.group(1))
    start_month = (int(m.group(2)) - 1) * 3 + 1
    return [f"{year}-{mm:02d}" for mm in range(start_month, start_month + 3)]


def discover_agents(quarterly_dir, quarter):
    """返回拥有该季度表单的智能体名（稳定排序）。"""
    agents = []
    if os.path.isdir(quarterly_dir):
        for name in sorted(os.listdir(quarterly_dir)):
            p = os.path.join(quarterly_dir, name)
            if os.path.isdir(p) and os.path.isfile(os.path.join(p, f"{quarter}.md")):
                agents.append(name)
    return agents


# ---------------------------------------------------------------- 解析

def read_file(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def parse_objective(text):
    """R-51 季度客观分：从表单「一、」区读取（聚合器写入）。

    兼容两种写法:
      `**季度客观分** = (0+2+0) / 3 = **0**`
      `**季度客观分** = 3个月均值 = **0** 分（(0+2+0) / 3）`
    """
    m = re.search(r"季度客观分.*?=\s*\*\*(\d+(?:\.\d+)?)\*\*", text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def section_text(text, marker):
    """取 `## <marker>` 到下一个 `## ` 标题之间的文本。"""
    m = re.search(rf"^##\s+{re.escape(marker)}", text, re.M)
    if not m:
        return None
    start = m.start()
    nxt = re.search(r"^##\s+", text[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(text)
    return text[start:end]


def parse_human_section(text):
    """解析「二、季度人评」维度分表格。

    返回 dict:
      reviewers   [{idx, name}] 按表头列序
      dims        [{name, weight, scores: {reviewer_idx: float}}]
      complete    {reviewer_idx: bool}  该评分人全部维度已填
      present     {reviewer_idx: bool}  该评分人至少一个维度已填
    表单无二区 / 无表头 / 无数据行时返回对应空结构。
    """
    sec = section_text(text, "二、")
    empty = {"reviewers": [], "dims": [], "complete": {}, "present": {}}
    if not sec:
        return empty

    lines = sec.splitlines()
    header_idx = None
    reviewers = []
    for i, ln in enumerate(lines):
        if ln.startswith("|") and "维度" in ln and "权重" in ln:
            header_idx = i
            fields = [f.strip() for f in ln.strip("|").split("|")]
            for j, f in enumerate(fields):
                if f.startswith("评分人"):
                    reviewers.append({"idx": j, "name": f})
            break
    if header_idx is None or not reviewers:
        return empty

    dims = []
    for ln in lines[header_idx + 1:]:
        if not ln.startswith("|"):
            continue
        fields = [f.strip() for f in ln.strip("|").split("|")]
        if len(fields) < 2:
            continue
        if not fields[1].endswith("%"):
            continue  # 非权重行（如汇总/分隔）
        wm = re.match(r"(\d+)", fields[1])
        if not wm:
            continue
        scores = {}
        for rv in reviewers:
            j = rv["idx"]
            if j < len(fields):
                s = fields[j].strip()
                if re.fullmatch(r"\d+(?:\.\d+)?", s):
                    scores[j] = float(s)
        dims.append({"name": fields[0], "weight": int(wm.group(1)), "scores": scores})

    present = {rv["idx"]: any(d["scores"].get(rv["idx"]) is not None for d in dims)
               for rv in reviewers}
    complete = {rv["idx"]: all(rv["idx"] in d["scores"] for d in dims)
                for rv in reviewers}
    return {"reviewers": reviewers, "dims": dims,
            "complete": complete, "present": present}


# ---------------------------------------------------------------- 计算

def compute_reviewer_score(dims, reviewer_idx):
    """R-52: Σ(维度分 × 权重%) × 20，四舍五入到整数。

    任一维度缺失返回 None（判定需要全维度就绪）。
    标准权重（和为 100%）下结果恒为整数（20-100）。
    """
    pairs = [(d["scores"].get(reviewer_idx), d["weight"]) for d in dims]
    if any(s is None for s, _ in pairs):
        return None
    total_w = sum(w for _, w in pairs)
    if total_w <= 0:
        return None
    weighted = sum(s * w / 100.0 for s, w in pairs if s is not None)
    return round(weighted * 20)


def grade_for(comprehensive):
    """R-62~R-66: 等级查表（综合分 ≥95→S / ≥85→A / ≥70→B / ≥60→C / <60→D）。

    输出**原始等级 auto_grade**（未经任何防失真修正）；R-71/R-72/E-02 修正
    由防失真模块 `apply_anti_distortion` 统一施加（P1-10 联调，B-1）。
    """
    for low, grade in GRADE_TABLE:
        if comprehensive >= low:
            return grade
    return GRADE_DEFAULT


# ---------------------------------------------------------------- 渲染回填

def fmt_score(v):
    """整数/整值浮点显示为整数，否则保留 1 位小数。"""
    if isinstance(v, int):
        return str(v)
    v = round(v, 6)  # 消除浮点尾差（如 92.00000000000001 → 92）
    if float(v).is_integer():
        return str(int(v))
    return f"{v:.1f}"


def set_value_after_eq(line, value):
    """`... = ______` / `... = **旧值**` → `... = **新值**`（取最后一个 `=`）。"""
    idx = line.rfind("=")
    if idx < 0:
        return line
    return line[: idx + 1] + f" **{value}**"


def set_comp_value(line, value):
    """整行加粗的综合分行: `**季度综合分 = ... = ______**` → 值写入加粗内。"""
    stripped = line.strip()
    inner = stripped[2:-2] if stripped.startswith("**") and stripped.endswith("**") \
        else stripped
    idx = inner.rfind("=")
    if idx < 0:
        return line
    return "**" + inner[: idx + 1] + f" {value}" + "**"


def set_grade_value(line, grade):
    """`**本季等级**: ______ （等级上限C）` → `**本季等级**: **C** （等级上限C）`。"""
    m = re.match(r"^(\*\*本季等级\*\*:\s*)(.*)$", line)
    if not m:
        return line
    rest = re.sub(r"^(______|\*\*[^\s*][^*]*\*\*)", f"**{grade}**", m.group(2))
    return m.group(1) + rest


def render_form(text, human_scores, final_score, comprehensive, grade,
                single_reviewer, force=False):
    """回填表单空白/旧值；未命中的行保持原样。

    human_scores: {"评分人1": int, ...}
    force: 为 False 时若目标行已含非空值则保留（idempotent 主路径）；
           为 True 时无条件同步（用于输入变化后的刷新）。
    """
    lines = text.splitlines()
    out = []
    for ln in lines:
        new = ln
        m = re.match(r"^\*\*人评分(?P<n>\d+)\*\*", ln)
        if m:
            name = f"评分人{m.group('n')}"
            if name in human_scores:
                new = set_value_after_eq(ln, fmt_score(human_scores[name]))
            elif not force:
                new = ln
        elif ln.startswith("**人评最终分**"):
            new = set_value_after_eq(ln, fmt_score(final_score))
            if single_reviewer:
                new += "（E-02 单评分人，非平均）"
        elif ln.startswith("**季度综合分"):
            new = set_comp_value(ln, fmt_score(comprehensive))
        elif ln.startswith("**本季等级**"):
            new = set_grade_value(ln, grade)
        elif re.match(r"^\|\s*[SABCD]\s*\|", ln):
            # 等级表为纯函数：先清全部行 ☑，仅标记当前等级行（等级变更后重跑不残留）
            fields = [f.strip() for f in ln.strip("|").split("|")]
            if len(fields) >= 3:
                fields[2] = "☑" if fields[0] == grade else ""
                new = "| " + " | ".join(fields) + " |"
        elif re.match(r"^- \[ \] 人评评分人|^- \[x\] 人评评分人", ln):
            cnt = len(human_scores)
            if cnt >= 2:
                new = f"- [ ] 人评评分人 ≥ 2: {cnt}人（满足）"
            elif cnt == 1:
                new = f"- [ ] 人评评分人 ≥ 2: {cnt}人（E-02 单评分人，等级上限A）"
        out.append(new)
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- 写入

def atomic_write(path, content):
    """原子写: 临时文件 + os.replace；内容一致时跳过（严格幂等）。"""
    content_bytes = content.encode("utf-8")
    if os.path.exists(path):
        try:
            with open(path, "rb") as f:
                if f.read() == content_bytes:
                    return False
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


# ---------------------------------------------------------------- 主流程

def judge_form(agent, quarter, agents_root, dry_run=False):
    """判定单个智能体的季度人评表单，返回状态 dict。"""
    if not agent or "/" in agent or "\\" in agent or ".." in agent:
        raise ValueError(f"非法的 agent 参数（禁止空值/路径分隔符/..）: {agent!r}")
    _, _, quarterly_dir = scoring_dirs(agents_root)
    form_path = os.path.join(quarterly_dir, agent, f"{quarter}.md")
    status = {"agent": agent, "quarter": quarter, "path": form_path,
              "changed": False, "stage": "ok", "note": ""}

    text = read_file(form_path)
    if text is None:
        status["stage"] = "missing"
        status["note"] = "表单缺失"
        return status

    obj = parse_objective(text)
    if obj is None:
        status["stage"] = "no-objective"
        status["note"] = "客观分缺失"
        return status
    status["objective"] = obj

    human = parse_human_section(text)
    if not human["dims"]:
        status["stage"] = "pending"
        status["note"] = "人评区未填写（维度分就绪后自动判定）"
        return status

    human_scores = {}
    for rv in human["reviewers"]:
        if human["complete"].get(rv["idx"]):
            s = compute_reviewer_score(human["dims"], rv["idx"])
            if s is not None:
                human_scores[rv["name"]] = s

    if not human_scores:
        status["stage"] = "pending"
        status["note"] = "人评维度分未填写（维度分就绪后自动判定）"
        return status

    single_reviewer = len(human_scores) < 2
    final_score = sum(human_scores.values()) / len(human_scores)
    comprehensive = obj * 0.8 + final_score * 0.2
    auto_grade = grade_for(comprehensive)  # 原始等级（未经防失真修正，B-1）

    # 防失真修正（P1-10 联调）：由 anti-distortion-rules 唯一权威计算最终等级。
    # 计数基于事件流水结构化 R-31/R-32（fail-open：缺事件文件按 0 计，不冤枉）。
    counts = {"r31": 0, "r32": 0}
    corrections = []
    triggers = []
    result = None
    if _ANTI_MOD is not None:
        events_dir, _, _ = scoring_dirs(agents_root)
        counts = _ANTI_MOD.count_distortion_events(
            events_dir, agent, quarter_months(quarter))
        result = _ANTI_MOD.apply_anti_distortion(
            auto_grade, counts, single_reviewer=single_reviewer)
        grade = result.final_grade
        corrections = [
            {"rule": c.rule, "action": c.action, "reason": c.reason,
             "from_grade": c.from_grade, "to_grade": c.to_grade}
            for c in result.corrections
        ]
        triggers = [c.rule for c in result.corrections]
        status["anti_distortion"] = "ok"
    else:
        grade = auto_grade  # fail-open：防失真模块缺失不惩罚
        status["anti_distortion"] = "missing"
        status["note"] = "防失真模块缺失，未应用修正（fail-open）"

    status.update({
        "human_scores": human_scores,
        "human_final": final_score,
        "comprehensive": comprehensive,
        "auto_grade": auto_grade,
        "counts": counts,
        "corrections": corrections,
        "triggers": triggers,
        "grade": grade,
        "single_reviewer": single_reviewer,
    })

    new_text = render_form(text, human_scores, final_score, comprehensive,
                           grade, single_reviewer)
    if new_text != text:
        if dry_run:
            status["changed"] = True
            status["note"] = "DRY-RUN：将回填判定"
        else:
            changed = atomic_write(form_path, new_text)
            status["changed"] = changed
            status["note"] = "已回填判定" if changed else "已是最新（无变化）"
    else:
        status["note"] = "已是最新（无变化）"

    # 决策日志留痕（唯一写入口，幂等：同一判定重复运行不重复追加）
    if not dry_run and result is not None and status["stage"] == "ok":
        _ANTI_MOD.write_decision_log(agents_root, agent, quarter, result)
    return status


def main():
    parser = argparse.ArgumentParser(description="季度人评表单自动判定 (quarterly-review-judge)")
    parser.add_argument("--quarter", help="季度 YYYY-Qn（默认当前季度）")
    parser.add_argument("--agent", help="仅处理指定智能体")
    parser.add_argument("--dry-run", action="store_true", help="预演，不产生任何写入")
    parser.add_argument("--status", action="store_true", help="只读状态，不写入")
    parser.add_argument("--agents-dir", default=AGENTS_ROOT_DEFAULT,
                        help="agents 根目录（默认取脚本上级，测试用）")
    parser.add_argument("--json", action="store_true", help="汇总输出 JSON")
    args = parser.parse_args()

    agents_root = os.path.abspath(args.agents_dir)
    _, _, quarterly_dir = scoring_dirs(agents_root)
    quarter = args.quarter or current_quarter()
    if not QUARTER_RE.match(quarter):
        print(f"❌ 季度格式非法: {quarter}（应为 YYYY-Qn）")
        sys.exit(2)

    read_only = args.dry_run or args.status
    if args.agent is not None:
        if (not args.agent.strip() or "/" in args.agent or "\\" in args.agent
                or args.agent in (".", "..") or ".." in args.agent):
            print(f"❌ --agent 参数非法（禁止空值/路径分隔符/..）: {args.agent!r}")
            sys.exit(2)
        agents = [args.agent]
    else:
        agents = discover_agents(quarterly_dir, quarter)
    if not agents:
        print(f"❌ 未找到 {quarter} 季度表单（{quarterly_dir}/{{agent}}/{quarter}.md）")
        sys.exit(1)

    results = [judge_form(a, quarter, agents_root, dry_run=read_only) for a in agents]

    if args.json:
        import json
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
        return

    print("=== 季度人评表单自动判定 (quarterly-review-judge) ===")
    print(f"agents 根: {agents_root}")
    print(f"季度: {quarter} | 模式: {'DRY-RUN' if read_only else '正常判定'}")
    print()
    counts = {}
    for r in results:
        stage = r["stage"]
        counts[stage] = counts.get(stage, 0) + 1
        icon = {"ok": "✅", "pending": "⏳", "missing": "❌",
                "no-objective": "⚠️"}.get(stage, "•")
        line = f"  {icon} {r['agent']}: "
        if stage == "ok":
            line += (f"综合{fmt_score(r['comprehensive'])} 等级{r['grade']}"
                     f"（人评{fmt_score(r['human_final'])}）")
            if r["changed"]:
                line += " (DRY-RUN 将写入)" if read_only else " (写入)"
            else:
                line += " (已是最新)"
            if r["single_reviewer"]:
                line += " ⚠️E-02单评分人"
            for rule in r.get("triggers", []):
                line += f" ⚠️{rule}"
        else:
            line += r["note"]
        print(line)
    print()
    print(f"汇总: 已判定{counts.get('ok', 0)} 待填写{counts.get('pending', 0)} "
          f"缺表单{counts.get('missing', 0)} 缺客观分{counts.get('no-objective', 0)}")


if __name__ == "__main__":
    main()
