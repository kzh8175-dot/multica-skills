#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test-rating-aggregator.py — rating-aggregator.py 验收测试（方案C P0-1 / KA-16）

覆盖验收标准:
  1. 构造流水手工计算与脚本输出逐项一致（月度 30 条、季度 10 条）
  2. 全部智能体生成月度/季度报告文件
  3. 连续运行两次结果一致（幂等）
  4. --dry-run 不产生任何写入
  5. 缺失月份/空流水/坏行不崩溃，输出标记行（E_MISS/E_EMPTY/E_PARSE）
  6. 缺 agent 记录（无档案）时跳过该条并记告警（E_CAT），不中断全量聚合
  7. 报告含 category 元数据；类别解析优先级：R-42 CLI 标签 > 档案标签 > 关键词推断
  8. R-42 `[category=X]` 描述标签解析（与 tag-agent-categories.py 口径一致）

运行:
  python3 test-rating-aggregator.py
  python3 -m unittest tests.test-rating-aggregator -v
"""

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

AGGREGATOR = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "rating-aggregator.py",
))
PYTHON = sys.executable
NO_CLI = ["--no-cli-categories"]  # 测试离线执行，不依赖 multica agent list

# 每个元素: (名称, 期望类别, 档案 category 标签或 None, {月份: 积分列表 | "EMPTY" | None})
#   None  → 该月无事件流水文件（缺失）
#   "EMPTY" → 有文件但无有效积分行
AGENTS = [
    ("执行运营者", "execution", None, {
        "2026-07": [80, 80, 80],
        "2026-08": [120, 120, 160],
        "2026-09": [200, 200, 120],
    }),
    ("数据分析员", "data", None, {
        "2026-07": [100, 100, 100],
        "2026-08": [175],
        "2026-09": None,
    }),
    ("抖音增长师", "marketing", None, {
        "2026-07": [-15, -20],
        "2026-08": [350],
        "2026-09": "EMPTY",
    }),
    ("品牌设计师", "creative", None, {
        "2026-07": [300],
        "2026-08": [150],
        "2026-09": [450],
    }),
    ("系统架构师", "technical", None, {
        "2026-07": [100, 200, "abc"],
        "2026-08": None,
        "2026-09": None,
    }),
    ("技术客服", "technical", "technical", {
        "2026-07": [300],
        "2026-08": [600],
        "2026-09": [0],
    }),
    ("知乎营销员", "marketing", None, {
        "2026-07": [175, 175],
        "2026-08": [0, 0],
        "2026-09": [105],
    }),
    ("视频剪辑师", "technical", None, {
        "2026-07": [300],
        "2026-08": None,
        "2026-09": None,
    }),
    ("产品经理人", "creative", None, {
        "2026-07": None,
        "2026-08": [240],
        "2026-09": [60],
    }),
    ("实验研究员", "data", None, {
        "2026-07": None,
        "2026-08": None,
        "2026-09": [350],
    }),
    # 无档案但有流水 → 缺 agent 记录，应 E_CAT 告警且不中断（验收标准 #4/#6）
    ("无档案增长师", "marketing", None, {
        "2026-07": None,
        "2026-08": [175],
        "2026-09": None,
    }),
]

# 基准表（与 rating-benchmarks.conf 一致）
BENCHMARKS = {"execution": 400, "data": 350, "marketing": 350,
              "creative": 300, "technical": 300}

QUARTER = "2026-Q3"
MONTHS = ["2026-07", "2026-08", "2026-09"]


def monthly_expect(total, benchmark):
    """手工计算 R-41: clamp(total×100//benchmark, 0, 120)。"""
    if total is None:
        return 0
    return max(0, min(120, total * 100 // benchmark))


def quarterly_expect(monthly_scores):
    """手工计算 R-51: (M1 + M2 + M3) / 3（缺失月按 0 计，整数除法）。"""
    return sum(monthly_scores) // 3


def build_fixture(root):
    """构造临时 agents 根目录，返回 {agent: {month: (total, flags)}} 期望数据。"""
    agents_root = os.path.join(root, "agents")
    cap_dir = os.path.join(agents_root, "capability-system")
    profiles_root = os.path.join(agents_root, "profiles")
    events_root = os.path.join(agents_root, "reviews", "scoring", "events")

    os.makedirs(cap_dir)
    os.makedirs(profiles_root)

    # 共享配置（用于验证 rating-aggregator 读取共享基准）
    with open(os.path.join(cap_dir, "rating-benchmarks.conf"), "w", encoding="utf-8") as f:
        f.write("# 测试基准配置\n")
        for k, v in BENCHMARKS.items():
            f.write(f"{k}={v}\n")
        f.write("default=300\n")

    expected = {}
    for agent_name, category, tag, months in AGENTS:
        # 能力档案（category 标签可选）
        prof_dir = os.path.join(profiles_root, agent_name)
        os.makedirs(prof_dir, exist_ok=True)
        tag_line = f"category: {tag}" if tag else "# 无 category 标签"
        with open(os.path.join(prof_dir, "capabilities.md"), "w", encoding="utf-8") as f:
            f.write(f"# {agent_name} - 能力档案\n\n{tag_line}\n")

        # 事件流水
        expected[agent_name] = {}
        for month, spec in months.items():
            if spec is None:
                expected[agent_name][month] = (None, ["E_MISS"])
                continue
            agent_ev_dir = os.path.join(events_root, agent_name)
            os.makedirs(agent_ev_dir, exist_ok=True)
            path = os.path.join(agent_ev_dir, f"{month}.md")
            with open(path, "w", encoding="utf-8") as f:
                f.write("| 时间 | 任务 | 事件 | 积分 |\n")
                f.write("|------|------|------|:---:|\n")
                if spec == "EMPTY":
                    expected[agent_name][month] = (0, ["E_EMPTY"])
                    continue  # 只写表头
                total = 0
                flags = []
                for i, pts in enumerate(spec):
                    if isinstance(pts, str):
                        flags.append("E_PARSE")
                        f.write(f"| 2026-01-0{i+1} 10:00 | t-{i} | R-99 | {pts} |\n")
                        continue
                    total += int(pts)
                    f.write(f"| 2026-01-0{i+1} 10:00 | t-{i} | R-99 | {pts:+d} |\n")
                expected[agent_name][month] = (total, flags)

    # 「无档案增长师」：删除其档案目录，保留事件流水 → 缺 agent 记录场景
    shutil.rmtree(os.path.join(profiles_root, "无档案增长师"), ignore_errors=True)

    return agents_root, expected


def run_aggregator(agents_root, *args):
    cmd = [PYTHON, AGGREGATOR, "--agents-dir", agents_root, *NO_CLI, *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc


def read_report(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def extract_monthly_score(content):
    """从月度报告提取百分制分数。"""
    m = re.search(r"\*\*月度百分制\*\* = clamp\([^)]*\) = \*\*(\d+)\*\*", content)
    return int(m.group(1)) if m else None


def extract_monthly_total(content):
    m = re.search(r"\|\s*月积分\s*\|\s*([+-]?\d+)\s*\|", content)
    return int(m.group(1)) if m else None


def extract_quarterly_score(content):
    m = re.search(r"\*\*季度客观分\*\* = \([^)]*\) / 3 = \*\*(\d+)\*\*", content)
    return int(m.group(1)) if m else None


class TestRatingAggregator(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="rating-agg-test-")
        self.agents_root, self.expected = build_fixture(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def monthly_path(self, agent, month):
        return os.path.join(self.agents_root, "reviews", "scoring",
                            "monthly", agent, f"{month}.md")

    def quarterly_path(self, agent):
        return os.path.join(self.agents_root, "reviews", "scoring",
                            "quarterly", agent, f"{QUARTER}.md")

    # ---------- 1. 手工计算与脚本输出逐项一致 ----------
    def test_monthly_hand_calc_consistency(self):
        proc = run_aggregator(self.agents_root, "--all")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        items = 0
        for agent_name, category, _, months in AGENTS:
            benchmark = BENCHMARKS[category]
            for month, spec in months.items():
                total, _ = self.expected[agent_name][month]
                expect = monthly_expect(total, benchmark)
                path = self.monthly_path(agent_name, month)
                self.assertTrue(os.path.exists(path), f"缺少月度报告 {path}")
                content = read_report(path)
                got = extract_monthly_score(content)
                self.assertEqual(got, expect,
                                 f"{agent_name} {month}: 期望{expect} 实得{got}")
                # 报告中的月积分也应对
                got_total = extract_monthly_total(content)
                self.assertEqual(got_total, 0 if total is None else total)
                items += 1
        self.assertGreaterEqual(items, 10, "月度逐项核对条数应 ≥10")

    def test_quarterly_hand_calc_consistency(self):
        proc = run_aggregator(self.agents_root, "--all")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        items = 0
        for agent_name, category, _, months in AGENTS:
            benchmark = BENCHMARKS[category]
            m_scores = []
            for month, spec in months.items():
                if spec is None:
                    m_scores.append(0)  # 缺失月按 0 计（R-51）
                    continue
                total, _ = self.expected[agent_name][month]
                m_scores.append(monthly_expect(total, benchmark))
            expect = quarterly_expect(m_scores)
            path = self.quarterly_path(agent_name)
            self.assertTrue(os.path.exists(path), f"缺少季度报告 {path}")
            got = extract_quarterly_score(read_report(path))
            self.assertEqual(got, expect,
                             f"{agent_name} {QUARTER}: 期望{expect} 实得{got}")
            items += 1
        self.assertGreaterEqual(items, 10, "季度逐项核对条数应 ≥10")

    # ---------- 2. 全部智能体生成月度/季度报告 ----------
    def test_all_agents_generate_reports(self):
        proc = run_aggregator(self.agents_root, "--all")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        monthly_dirs = os.path.join(self.agents_root, "reviews", "scoring", "monthly")
        quarterly_dirs = os.path.join(self.agents_root, "reviews", "scoring", "quarterly")
        for agent_name, _, _, _ in AGENTS:
            self.assertTrue(os.path.isdir(os.path.join(monthly_dirs, agent_name)),
                            f"{agent_name} 缺少月度目录")
            self.assertTrue(os.path.isdir(os.path.join(quarterly_dirs, agent_name)),
                            f"{agent_name} 缺少季度目录")
            self.assertEqual(len(os.listdir(os.path.join(monthly_dirs, agent_name))), 3,
                             f"{agent_name} 应生成 3 个月度报告")

    # ---------- 3. 幂等：连续运行两次结果一致 ----------
    def test_idempotent(self):
        proc1 = run_aggregator(self.agents_root, "--all")
        self.assertEqual(proc1.returncode, 0, proc1.stderr)
        # 记录全部文件内容
        snap1 = {}
        for dirpath, _, files in os.walk(self.agents_root):
            for fn in files:
                p = os.path.join(dirpath, fn)
                snap1[p] = read_report(p)

        proc2 = run_aggregator(self.agents_root, "--all")
        self.assertEqual(proc2.returncode, 0, proc2.stderr)
        snap2 = {}
        for dirpath, _, files in os.walk(self.agents_root):
            for fn in files:
                p = os.path.join(dirpath, fn)
                snap2[p] = read_report(p)

        self.assertEqual(set(snap1), set(snap2), "文件集合应一致")
        for p in snap1:
            self.assertEqual(snap1[p], snap2[p], f"内容不一致: {p}")
        # 第二次运行应全部「无变化跳过」
        self.assertIn("无变化跳过: ", proc2.stdout)
        self.assertIn("实际写入: 0", proc2.stdout)

    # ---------- 4. --dry-run 不产生任何写入 ----------
    def test_dry_run_no_writes(self):
        proc = run_aggregator(self.agents_root, "--all", "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("DRY-RUN", proc.stdout)
        # 输出目录（monthly/quarterly）不应被创建或写入任何报告
        scoring = os.path.join(self.agents_root, "reviews", "scoring")
        for sub in ("monthly", "quarterly"):
            out_dir = os.path.join(scoring, sub)
            if os.path.exists(out_dir):
                for dirpath, _, files in os.walk(out_dir):
                    self.assertEqual(files, [],
                                     f"DRY-RUN 不应产生写入: {os.path.join(dirpath, ', '.join(files))}")

    # ---------- 5. 缺失/空流水/坏行标记而非崩溃 ----------
    def test_missing_empty_flags(self):
        proc = run_aggregator(self.agents_root, "--all")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # 数据分析员 2026-09 缺失 → E_MISS
        content = read_report(self.monthly_path("数据分析员", "2026-09"))
        self.assertIn("E_MISS", content)
        # 抖音增长师 2026-09 空流水 → E_EMPTY
        content = read_report(self.monthly_path("抖音增长师", "2026-09"))
        self.assertIn("E_EMPTY", content)
        # 系统架构师 2026-07 含无法解析行 → E_PARSE
        content = read_report(self.monthly_path("系统架构师", "2026-07"))
        self.assertIn("E_PARSE", content)
        self.assertEqual(extract_monthly_score(content), 100, "有效行仍应正常求和")
        # 季度报告缺失月标记
        content = read_report(self.quarterly_path("实验研究员"))
        self.assertIn("E_MISS", content)

    # ---------- 6. 缺 agent 记录：跳过该条并记告警，不中断全量聚合 ----------
    def test_missing_profile_does_not_abort(self):
        proc = run_aggregator(self.agents_root, "--all")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # 无档案增长师：无档案（被删除），但有事件流水 → 应生成报告并 E_CAT 告警
        content = read_report(self.monthly_path("无档案增长师", "2026-08"))
        self.assertIn("E_CAT", content)
        self.assertEqual(extract_monthly_score(content), 50)  # 175//350=0 → 50
        # 其他智能体不受影响，全部正常生成
        for agent_name, _, _, months in AGENTS:
            for month in months:
                self.assertTrue(os.path.exists(self.monthly_path(agent_name, month)),
                                f"{agent_name} {month} 报告缺失")

    # ---------- 7. 类别解析优先级与 clamp ----------
    def test_category_precedence(self):
        proc = run_aggregator(self.agents_root, "--all")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # 技术客服：名称关键词→execution，但档案标签 category: technical → technical(300)
        content = read_report(self.monthly_path("技术客服", "2026-08"))
        self.assertIn("**类别**: technical", content)
        self.assertIn("**基准月积分**: 300", content)
        # 600 → clamp 120
        self.assertEqual(extract_monthly_score(content), 120)
        # 执行运营者：名称关键词→execution(400)，520 → clamp 120
        content = read_report(self.monthly_path("执行运营者", "2026-09"))
        self.assertIn("**类别**: execution", content)
        self.assertEqual(extract_monthly_score(content), 120)
        # 抖音增长师：负数 → clamp 0
        content = read_report(self.monthly_path("抖音增长师", "2026-07"))
        self.assertIn("**类别**: marketing", content)
        self.assertEqual(extract_monthly_score(content), 0)

    # ---------- 默认模式（无参数）对全量智能体生成当前月+当前季度 ----------
    def test_default_mode_generates_for_all(self):
        proc = run_aggregator(self.agents_root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        monthly_dirs = os.path.join(self.agents_root, "reviews", "scoring", "monthly")
        quarterly_dirs = os.path.join(self.agents_root, "reviews", "scoring", "quarterly")
        for agent_name, _, _, _ in AGENTS:
            self.assertTrue(os.path.isdir(os.path.join(monthly_dirs, agent_name)))
            self.assertTrue(os.path.isdir(os.path.join(quarterly_dirs, agent_name)))

    # ---------- 8. 既有调度器人评表单：仅更新客观分区，保留人评区 ----------
    def test_quarterly_section_preservation(self):
        agent = "执行运营者"
        qdir = os.path.dirname(self.quarterly_path(agent))
        os.makedirs(qdir, exist_ok=True)
        form = (
            "# %s - 季度人评表单\n\n**季度**: 2026-Q3\n\n## 一、季度客观分（系统自动汇总，权重80%%）\n\n"
            "| 月份 | 积分 | 基准 | 百分制(上限120) |\n|------|:---:|:---:|:---:|\n"
            "| 2026-07 | 0 | 0 | 0 |\n\n**季度客观分** = 3个月均值 = **0** 分\n\n"
            "## 二、季度人评（人工填写，权重20%%）\n\n| 维度 | 权重 | 评分人1 |\n"
            "|------|:---:|:---:|\n| 交付质量 | 30%% | 4 |\n\n## 三、季度综合分与等级\n"
        ) % agent
        with open(self.quarterly_path(agent), "w", encoding="utf-8") as f:
            f.write(form)

        proc = run_aggregator(self.agents_root, "--quarter", QUARTER)
        self.assertEqual(proc.returncode, 0, proc.stderr)

        content = read_report(self.quarterly_path(agent))
        # 客观分区已更新为计算值
        self.assertIn("| 2026-07 | 240 | 400 | 60 |", content)
        self.assertIn("**季度客观分**", content)
        # 人评区（含人工填写）保留
        self.assertIn("## 二、季度人评", content)
        self.assertIn("| 交付质量 | 30% | 4 |", content)
        self.assertIn("## 三、季度综合分与等级", content)


class TestCategoryResolution(unittest.TestCase):
    """R-42 描述标签解析与类别解析优先级（离线单元测试）。"""

    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("rating_aggregator", AGGREGATOR)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def test_desc_category_regex(self):
        rex = self.mod.DESC_CATEGORY_RE
        self.assertEqual(rex.search("xx [category=creative] xx").group(1), "creative")
        self.assertEqual(rex.search("xx [category=technical]").group(1), "technical")
        self.assertIsNone(rex.search("no tag here"))
        # 非枚举值能被捕获，但由 VALID_CATEGORIES 在 load_cli_categories 中过滤
        self.assertNotIn(rex.search("[category=unknown]").group(1),
                         self.mod.VALID_CATEGORIES)

    def test_norm_name(self):
        self.assertEqual(self.mod._norm_name("AI 身份与信任架构师"),
                         self.mod._norm_name("AI-身份与信任架构师"))
        self.assertEqual(self.mod._norm_name("资深战略领导者"), "资深战略领导者")

    def test_resolve_category_cli_first(self):
        # CLI R-42 标签 > 档案标签 > 关键词推断
        cli = {self.mod._norm_name("技术客服"): "marketing"}  # 与档案标签冲突
        # 使用临时档案目录
        with tempfile.TemporaryDirectory() as tmp:
            prof = os.path.join(tmp, "技术客服")
            os.makedirs(prof)
            with open(os.path.join(prof, "capabilities.md"), "w", encoding="utf-8") as f:
                f.write("# 技术客服\n\ncategory: technical\n")
            cat, flag = self.mod.resolve_category("技术客服", tmp, cli)
            self.assertEqual(cat, "marketing")   # CLI 优先
            self.assertIsNone(flag)

    def test_resolve_category_profile_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            prof = os.path.join(tmp, "数据分析员")
            os.makedirs(prof)
            with open(os.path.join(prof, "capabilities.md"), "w", encoding="utf-8") as f:
                f.write("# 数据分析员\n\ncategory: data\n")
            cat, flag = self.mod.resolve_category("数据分析员", tmp, {})
            self.assertEqual(cat, "data")
            self.assertIsNone(flag)

    def test_resolve_category_keyword_fallback_no_profile(self):
        # 无档案 → 关键词推断 + E_CAT 告警
        with tempfile.TemporaryDirectory() as tmp:
            cat, flag = self.mod.resolve_category("抖音增长师", tmp, {})
            self.assertEqual(cat, "marketing")
            self.assertEqual(flag, self.mod.E_CAT)


if __name__ == "__main__":
    unittest.main(verbosity=2)
