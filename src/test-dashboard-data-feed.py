#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test-dashboard-data-feed.py — dashboard-data-feed 只读数据接口测试（KA-96）

覆盖:
  - 月度 R-41 解析（total/benchmark/score/flags）
  - 事件流水解析（rows/total/异常行标记）
  - 季度表单解析（已判定 vs 待运行·预估值）
  - 防失真日志解析
  - 类别解析优先级（CLI → 档案 → 推断）
  - 等级查表（R-62~R-66）
  - 预算过滤（纯函数）
  - build_feed 集成 + 只读性（不改动 agents 根）
"""

import importlib.util
import os
import shutil
import sys
import tempfile
import unittest

MODULE = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "dashboard-data-feed.py"))

spec = importlib.util.spec_from_file_location("dashboard_data_feed", MODULE)
feed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feed)


def make_agents_root():
    """构造测试用 agents 根。"""
    root = tempfile.mkdtemp(prefix="feed-test-")
    dirs = {
        "events": os.path.join(root, "reviews", "scoring", "events"),
        "monthly": os.path.join(root, "reviews", "scoring", "monthly"),
        "quarterly": os.path.join(root, "reviews", "scoring", "quarterly"),
        "ad": os.path.join(root, "reviews", "scoring", "anti-distortion"),
        "profiles": os.path.join(root, "profiles"),
    }
    for d in dirs.values():
        os.makedirs(d, exist_ok=True)
    bench_dir = os.path.join(root, "capability-system")
    os.makedirs(bench_dir, exist_ok=True)
    with open(os.path.join(bench_dir, "rating-benchmarks.conf"), "w",
              encoding="utf-8") as f:
        f.write("execution=400\ndata=350\nmarketing=350\ncreative=300\ntechnical=300\ndefault=300\n")
    return root, dirs


def write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def seed_fixture(root, dirs):
    """写入真实格式样例数据（开发者工具工程师 + 资深战略领导者）。"""
    # 档案（category 标签）
    write(os.path.join(dirs["profiles"], "开发者工具工程师", "capabilities.md"),
          "# 开发者工具工程师\ncategory=technical\n")
    write(os.path.join(dirs["profiles"], "资深战略领导者", "capabilities.md"),
          "# 资深战略领导者\ncategory=creative\n")
    # 无档案 agent：走关键词推断（"数据" → data）
    write(os.path.join(dirs["profiles"], "数据工程师", "capabilities.md"),
          "# 数据工程师\n")
    # 事件流水
    write(os.path.join(dirs["events"], "开发者工具工程师", "2026-08.md"),
          "| 时间 | 任务 | 事件 | 积分 |\n"
          "|------|------|------|:---:|\n"
          "| 2026-08-16 10:16 | issue-1 | R-21:自评 | +5 |\n"
          "| 2026-08-16 11:04 | issue-2 | R-22:档案 | +5 |\n"
          "| 2026-08-16 12:00 | issue-3 | 坏行 | +x |\n")
    # 月度报告
    write(os.path.join(dirs["monthly"], "开发者工具工程师", "2026-08.md"),
          "# 开发者工具工程师 - 月度积分报告\n"
          "**月份**: 2026-08\n**类别**: technical\n**基准月积分**: 300\n"
          "## 月度汇总\n"
          "| 项目 | 数值 |\n|------|:---:|\n"
          "| 月积分 | 10 |\n| 基准月积分 | 300 |\n| 月度百分制 | 3 |\n"
          "> ⚠️ E_PARSE: 流水有无法解析的行\n")
    # 季度表单（pending，人评未跑）
    write(os.path.join(dirs["quarterly"], "开发者工具工程师", "2026-Q3.md"),
          "# 开发者工具工程师 - 季度客观分报告\n"
          "**季度**: 2026-Q3\n**类别**: technical\n**基准月积分**: 300\n"
          "## 季度客观分\n"
          "| 月份 | 积分 | 基准 | 百分制 |\n|------|:---:|:---:|:---:|\n"
          "| 2026-07 | 0 | 300 | 0 |\n| 2026-08 | 10 | 300 | 3 |\n"
          "| 2026-09 | 0 | 300 | 0 |\n"
          "**季度客观分** = (0+3+0) / 3 = **1**\n"
          "> ⚠️ E_MISS: 2026-07: 缺少事件流水\n")
    # 季度表单（judged，含人评）
    write(os.path.join(dirs["quarterly"], "资深战略领导者", "2026-Q3.md"),
          "# 资深战略领导者 - 季度人评表单\n"
          "## 一、季度客观分\n"
          "**季度客观分** = 3个月均值 = **80** 分（(0+0+0) / 3）\n"
          "## 二、季度人评\n"
          "| 维度 | 权重 | 评分人1 | 评分人2 | 备注 |\n"
          "|------|:---:|:---:|:---:|------|\n"
          "| 交付质量 | 30% | 5 | 4 | |\n"
          "**人评分1** = Σ(维度×权重)×20 = **100**\n"
          "**人评分2** = Σ(维度×权重)×20 = **80**\n"
          "**人评最终分** = (评分人1+评分人2)/2 = **90**\n"
          "## 三、季度综合分与等级\n"
          "**季度综合分 = 客观分×0.8 + 人评最终分×0.2 = **82**\n"
          "**本季等级**: **B** （等级上限C）\n")
    # 季度表单（pending 完整模板：含静态描述「E-02: 单评分人可用，等级上限A」
    # 但无人评判定 → 不得触发 e02，KA-96 代码审查回归用例）
    write(os.path.join(dirs["quarterly"], "SEO优化专家", "2026-Q3.md"),
          "# SEO优化专家 - 季度人评表单\n"
          "**季度**: 2026-Q3\n**规则版本**: 方案C (R-51~R-76)\n"
          "## 一、季度客观分（系统自动汇总，权重80%）\n"
          "| 月份 | 积分 | 基准 | 百分制(上限120) |\n"
          "|------|:---:|:---:|:---:|\n"
          "| 2026-07 | 0 | 350 | 0 |\n"
          "**季度客观分** = 3个月均值 = **0** 分（(0+0+0) / 3）\n"
          "## 二、季度人评（人工填写，权重20%）\n"
          "| 维度 | 权重 | 评分人1 | 评分人2 | 备注 |\n"
          "|------|:---:|:---:|:---:|------|\n"
          "| 交付质量 | 30% |  |  | |\n"
          "**人评分1** = Σ(维度×权重)×20 = ______\n"
          "**人评最终分** = (评分人1+评分人2)/2 = ______\n"
          "## 三、季度综合分与等级\n"
          "**季度综合分 = 客观分×0.8 + 人评最终分×0.2 = ______**\n"
          "**本季等级**: ______ \n"
          "## 四、防失真校验（自动）\n"
          "- [ ] 红线一票否决检查: 红线计数=0次|未触发(需≥2次) | 自评缺失计数=0次|未触发(需≥2次)\n"
          "- [ ] 人评评分人 ≥ 2: （人数）\n"
          "## 五、异常处理记录\n"
          "| 异常类型 | 是否触发 | 处理动作 |\n"
          "|---------|:---:|---------|\n"
          "| 积分流水缺失 |  | E-01: 补记或排除该月 |\n"
          "| 评分人不足 |  | E-02: 单评分人可用，等级上限A |\n"
          "| 档案缺失 |  | E-03: 先创建档案 |\n"
          "| 等级=D |  | E-04: 升级最高决策者专项复盘 |\n")
    # 季度表单（judged + E-02 单评分人：judge 回填标记 → e02=true）
    write(os.path.join(dirs["quarterly"], "销售工程师", "2026-Q3.md"),
          "# 销售工程师 - 季度人评表单\n"
          "## 一、季度客观分\n"
          "**季度客观分** = 3个月均值 = **70** 分\n"
          "## 二、季度人评\n"
          "| 维度 | 权重 | 评分人1 | 备注 |\n"
          "|------|:---:|:---:|------|\n"
          "| 交付质量 | 30% | 5 | |\n"
          "**人评分1** = Σ(维度×权重)×20 = **100**\n"
          "**人评最终分** = (评分人1+评分人2)/2 = **100**（E-02 单评分人，非平均）\n"
          "## 三、季度综合分与等级\n"
          "**季度综合分 = 客观分×0.8 + 人评最终分×0.2 = **76**\n"
          "**本季等级**: **B**\n")
    # 防失真日志
    write(os.path.join(dirs["ad"], "开发者工具工程师", "2026-Q3.md"),
          "# 开发者工具工程师 - 防失真决策日志（append-only）\n"
          "\n### 2026-08-17T00:00:00Z · 防失真判定（2026-Q3）\n"
          "<!-- sig: abc123 -->\n"
          "- auto_grade: S\n- counts: r31=0, r32=2\n- corrections:\n"
          "  - R-72 demote: S → A（缺自评事件 2 ≥ 阈值 2）\n"
          "- final_grade: A\n")
    return root, dirs


class TestParsers(unittest.TestCase):

    def setUp(self):
        self.root, self.dirs = seed_fixture(*make_agents_root())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_parse_monthly_report(self):
        res = feed.parse_monthly_report(
            os.path.join(self.dirs["monthly"], "开发者工具工程师", "2026-08.md"))
        self.assertEqual(res["total"], 10)
        self.assertEqual(res["benchmark"], 300)
        self.assertEqual(res["score"], 3)
        self.assertIn("E_PARSE", res["flags"][0])

    def test_parse_monthly_report_missing(self):
        self.assertIsNone(feed.parse_monthly_report(
            os.path.join(self.dirs["monthly"], "不存在", "2026-08.md")))

    def test_parse_events_file(self):
        res = feed.parse_events_file(
            os.path.join(self.dirs["events"], "开发者工具工程师", "2026-08.md"))
        self.assertEqual(res["total"], 10)            # +5 +5，坏行不计
        self.assertEqual(len(res["rows"]), 2)
        self.assertEqual(res["rows"][0]["event"], "R-21:自评")
        self.assertEqual(len(res["flags"]), 1)         # 坏行被标记
        self.assertIn("积分列无法解析", res["flags"][0])

    def test_parse_quarterly_form_pending(self):
        res = feed.parse_quarterly_form(
            os.path.join(self.dirs["quarterly"], "开发者工具工程师", "2026-Q3.md"))
        self.assertEqual(res["review_state"], "pending")
        self.assertEqual(res["objective"], 1)
        self.assertIsNone(res["human_final"])
        self.assertIsNone(res["comprehensive"])
        self.assertIsNone(res["grade"])
        # 预估值（objective_only 口径，等级查表 <60 → D）
        self.assertIsNotNone(res["estimated"])
        self.assertEqual(res["estimated"]["comprehensive"], 1)
        self.assertEqual(res["estimated"]["grade"], "D")
        self.assertEqual(res["estimated"]["basis"], "objective_only")
        self.assertTrue(res["estimated"]["as_of"])
        self.assertEqual(len(res["flags"]), 1)

    def test_parse_quarterly_form_judged(self):
        res = feed.parse_quarterly_form(
            os.path.join(self.dirs["quarterly"], "资深战略领导者", "2026-Q3.md"))
        self.assertEqual(res["review_state"], "judged")
        self.assertEqual(res["objective"], 80)
        self.assertEqual(res["human_final"], 90)
        self.assertEqual(res["comprehensive"], 82)
        self.assertEqual(res["grade"], "B")
        self.assertIsNone(res["estimated"])
        self.assertTrue(res["anti_fraud"]["r71"])   # （等级上限C）→ R-71
        self.assertFalse(res["anti_fraud"]["r72"])
        self.assertFalse(res["anti_fraud"]["e02"])  # 双评分人，无 E-02 标记

    def test_parse_quarterly_form_pending_template_no_e02(self):
        """回归（KA-96 代码审查阻塞项）：pending 完整模板含静态「等级上限A」
        描述文字，不得触发 e02。"""
        res = feed.parse_quarterly_form(
            os.path.join(self.dirs["quarterly"], "SEO优化专家", "2026-Q3.md"))
        self.assertEqual(res["review_state"], "pending")
        self.assertIsNone(res["grade"])
        self.assertFalse(res["anti_fraud"]["e02"],
                         "模板静态文字「E-02: 单评分人可用，等级上限A」不应触发 e02")
        self.assertFalse(res["anti_fraud"]["r71"])
        self.assertFalse(res["anti_fraud"]["r72"])

    def test_parse_quarterly_form_judged_single_reviewer_e02(self):
        """judge 已回填「（E-02 单评分人，非平均）」标记 → e02=true。"""
        res = feed.parse_quarterly_form(
            os.path.join(self.dirs["quarterly"], "销售工程师", "2026-Q3.md"))
        self.assertEqual(res["review_state"], "judged")
        self.assertEqual(res["grade"], "B")
        self.assertEqual(res["human_final"], 100)
        self.assertTrue(res["anti_fraud"]["e02"])
        self.assertIsNone(res["estimated"])

    def test_parse_anti_distortion_log(self):
        res = feed.parse_anti_distortion_log(
            os.path.join(self.dirs["ad"], "开发者工具工程师", "2026-Q3.md"))
        self.assertEqual(res["auto_grade"], "S")
        self.assertEqual(res["final_grade"], "A")
        self.assertEqual(res["counts"], {"r31": 0, "r32": 2})
        self.assertEqual(res["corrections"][0]["rule"], "R-72")

    def test_parse_anti_distortion_log_missing(self):
        self.assertIsNone(feed.parse_anti_distortion_log(
            os.path.join(self.dirs["ad"], "不存在", "2026-Q3.md")))


class TestPureLogic(unittest.TestCase):

    def test_grade_for(self):
        self.assertEqual(feed.grade_for(95), "S")
        self.assertEqual(feed.grade_for(85), "A")
        self.assertEqual(feed.grade_for(70), "B")
        self.assertEqual(feed.grade_for(60), "C")
        self.assertEqual(feed.grade_for(59.9), "D")
        self.assertEqual(feed.grade_for(120), "S")

    def test_anti_fraud_flags_e02_marker_semantics(self):
        """E-02 仅由 judge 回填标记 + judged 状态触发（KA-96 阻塞项修复）。"""
        template_pending = (
            "| 评分人不足 |  | E-02: 单评分人可用，等级上限A |\n"
            "**本季等级**: ______\n"
        )
        # pending 模板含静态「等级上限A」描述 → 不触发
        self.assertFalse(feed._anti_fraud_flags(template_pending, judged=False)["e02"])
        # 同一文本即便 judged=False 也不触发（未判定表单无权威 E-02）
        self.assertFalse(feed._anti_fraud_flags(template_pending, judged=True)["e02"])

        judged_marker_final = "**人评最终分** = **100**（E-02 单评分人，非平均）\n"
        self.assertTrue(feed._anti_fraud_flags(judged_marker_final, judged=True)["e02"])
        # judged 但无 E-02 标记 → 不触发
        self.assertFalse(feed._anti_fraud_flags(
            "**人评最终分** = **90**\n", judged=True)["e02"])

        # judge「人评评分人 ≥ 2」行标记（另一种回填形式）也触发
        cnt_marker = "- [ ] 人评评分人 ≥ 2: 1人（E-02 单评分人，等级上限A）\n"
        self.assertTrue(feed._anti_fraud_flags(cnt_marker, judged=True)["e02"])

    def test_keyword_category(self):
        self.assertEqual(feed.keyword_category("数据分析师"), "data")
        self.assertEqual(feed.keyword_category("抖音策略师"), "marketing")
        self.assertEqual(feed.keyword_category("软件架构师"), "technical")
        self.assertEqual(feed.keyword_category("未知角色"), "execution")

    def test_resolve_category_priority(self):
        root, dirs = make_agents_root()
        try:
            write(os.path.join(dirs["profiles"], "数据工程师", "capabilities.md"),
                  "# 数据工程师\ncategory=data\n")
            # CLI 优先
            cli = {"数据工程师": "execution"}
            cat, src = feed.resolve_category("数据工程师", dirs["profiles"], cli)
            self.assertEqual((cat, src), ("execution", "cli"))
            # 无 CLI → 档案
            cat, src = feed.resolve_category("数据工程师", dirs["profiles"], {})
            self.assertEqual((cat, src), ("data", "profile"))
            # 无档案 → 关键词推断
            cat, src = feed.resolve_category("抖音策略师", dirs["profiles"], {})
            self.assertEqual((cat, src), ("marketing", "inferred"))
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_filter_budget_issues(self):
        issues = [
            {"id": "a", "identifier": "KA-40", "title": "锚点", "status": "in_progress",
             "metadata": {"budget.ceiling": 1000, "budget.spent": 397,
                          "budget.variance": -0.603}},
            {"id": "b", "identifier": "KA-99", "title": "无预算", "status": "done",
             "metadata": {"rating.status": "credited"}},
            {"id": "c", "identifier": "KA-19", "title": "子项", "status": "done",
             "metadata": {"budget.ceiling": 50, "budget.spent": 65.5, "budget.variance": 0.31}},
        ]
        res = feed.filter_budget_issues(issues)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]["identifier"], "KA-19")   # 按 identifier 排序
        self.assertEqual(res[1]["ceiling"], 1000)
        self.assertEqual(res[0]["variance"], 0.31)

    def test_parse_pending_escalated(self):
        issues = [
            {"metadata": {"rating.status": "pending"}},
            {"metadata": {"rating.status": "pending"}},
            {"metadata": {"rating.status": "escalated"}},
            {"metadata": {"rating.status": "credited"}},
            {"metadata": {}},
        ]
        stats = feed.parse_pending_escalated(issues)
        self.assertEqual(stats["pending"], 2)
        self.assertEqual(stats["escalated"], 1)
        self.assertEqual(stats["credited"], 1)


class TestBuildFeed(unittest.TestCase):

    def setUp(self):
        self.root, self.dirs = seed_fixture(*make_agents_root())

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def snapshot_tree(self):
        """记录 agents 根下全部文件内容与 mtime，用于只读校验。"""
        snap = {}
        for base, _, files in os.walk(self.root):
            for fn in files:
                p = os.path.join(base, fn)
                with open(p, "rb") as f:
                    snap[p] = (f.read(), os.path.getmtime(p))
        return snap

    def test_build_feed_structure(self):
        before = self.snapshot_tree()
        agents = feed.discover_agents(self.root, feed.scoring_dirs(self.root))
        feed_data = feed.build_feed(
            self.root, ["2026-08"], ["2026-Q3"], agents, use_cli=False)
        after = self.snapshot_tree()

        self.assertEqual(before, after)   # 只读：无任何写入/改动
        self.assertTrue(feed_data["meta"]["read_only"])
        self.assertIn("开发者工具工程师", [a["name"] for a in feed_data["agents"]])
        self.assertIn("资深战略领导者", [a["name"] for a in feed_data["agents"]])

        # 类别：开发者工具工程师 档案 technical；数据工程师 推断 data
        by_name = {a["name"]: a for a in feed_data["agents"]}
        self.assertEqual(by_name["开发者工具工程师"]["category"], "technical")
        self.assertEqual(by_name["数据工程师"]["category"], "data")

        # 月度
        m = feed_data["monthly"]["2026-08"]["开发者工具工程师"]
        self.assertEqual(m["score"], 3)

        # 季度 pending 预估值 + judged
        q = feed_data["quarterly"]["2026-Q3"]
        self.assertEqual(q["开发者工具工程师"]["review_state"], "pending")
        self.assertEqual(q["资深战略领导者"]["review_state"], "judged")
        self.assertEqual(q["资深战略领导者"]["grade"], "B")

        # 事件
        e = feed_data["events"]["2026-08"]["开发者工具工程师"]
        self.assertEqual(e["total"], 10)

        # 防失真
        d = feed_data["anti_distortion"]["2026-Q3"]["开发者工具工程师"]
        self.assertEqual(d["final_grade"], "A")

        # 预算（offline 下为 None + note）
        self.assertIsNone(feed_data["budget"]["entries"])
        self.assertIn("offline", feed_data["budget"]["note"])

    def test_build_feed_agent_filter(self):
        feed_data = feed.build_feed(
            self.root, ["2026-08"], ["2026-Q3"], ["开发者工具工程师"], use_cli=False)
        self.assertEqual(len(feed_data["agents"]), 1)
        self.assertIn("开发者工具工程师", feed_data["monthly"]["2026-08"])

    def test_discover_months_quarters(self):
        dirs = feed.scoring_dirs(self.root)
        self.assertEqual(feed.discover_months(dirs), ["2026-08"])
        self.assertEqual(feed.discover_quarters(dirs), ["2026-Q3"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
