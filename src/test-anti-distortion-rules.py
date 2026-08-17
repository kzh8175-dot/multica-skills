#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test-anti-distortion-rules.py — anti-distortion-rules.py 验收测试（方案C P1-10 / KA-75）

覆盖验收标准:
  1. apply_anti_distortion 10 条边界用例（spec 3 表）全通过
  2. count_distortion_events:
     - 仅统计季度内月份（B1 修复回归：不再匹配全年 12 个月）
     - 结构化事件 ID 计数（B2 修复回归：'红线'/'违规'/'-20' 文本不误计）
     - (issue, event_id) 去重
     - 同一 issue 多事件（R-21 自评 + R-31 违规）均被计数（S-1 去重键对齐）
     - 文件缺失 → 0（fail-open）
  3. summarize 输出含触发/未触发与最终等级信息
  4. write_decision_log: 追加写入、幂等（同一判定不重复记录）、不同判定可追加
  5. CLI count/check/apply 子命令
  6. 回归：正常数据 final == auto（spec 用例 6）

运行:
  python3 test-anti-distortion-rules.py
"""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

MODULE = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "anti-distortion-rules.py",
))

spec = importlib.util.spec_from_file_location("anti_distortion_rules", MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def write_event(path, rows):
    """写入事件流水文件：rows = [(ts, issue, event, points), ...]"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("| 时间 | 任务 | 事件 | 积分 |\n")
        f.write("|------|------|------|:---:|\n")
        for ts, issue, event, pts in rows:
            f.write(f"| {ts} | {issue} | {event} | {pts:+d} |\n")


class TestApplyAntiDistortion(unittest.TestCase):
    """spec 3 边界用例表（终审版 18 条）全通过。"""

    CASES = [
        # (auto_grade, counts, final_grade, triggered_rules, single_reviewer, config)
        ("S", {"r31": 2, "r32": 0}, "C", {"R-71"}, False, None),         # 1 R-31×2 强制 C
        ("S", {"r31": 0, "r32": 2}, "A", {"R-72"}, False, None),         # 2 R-32×2 降一档
        ("S", {"r31": 1, "r32": 0}, "S", set(), False, None),            # 3 R-31×1 不触发
        ("S", {"r31": 0, "r32": 1}, "S", set(), False, None),            # 4 R-32×1 不触发
        ("A", {"r31": 1, "r32": 1}, "A", set(), False, None),            # 5 混合各1不触发
        ("B", {"r31": 0, "r32": 0}, "B", set(), False, None),            # 6 正常数据回归
        ("S", {"r31": 2, "r32": 2}, "C", {"R-72", "R-71"}, False, None), # 7 双触发先降后封顶
        ("D", {"r31": 2, "r32": 0}, "D", {"R-71"}, False, None),         # 8 R-31×2 且 auto=D 不抬升
        ("D", {"r31": 0, "r32": 2}, "D", {"R-72"}, False, None),         # 9 R-32×2 撞地板
        ("A", {"r31": 1, "r32": 2}, "B", {"R-72"}, False, None),         # 10 R-31×1+R-32×2 仅降档
        ("C", {"r31": 2, "r32": 2}, "D", {"R-72", "R-71"}, False, None), # 11 auto=C 双触发
        ("C", {"r31": 2, "r32": 0}, "C", {"R-71"}, False, None),         # 12 auto=C 仅 R-31（封顶 no-op）
        ("C", {"r31": 0, "r32": 2}, "D", {"R-72"}, False, None),         # 13 auto=C 仅 R-32
        ("S", {"r31": 1, "r32": 0}, "C", {"R-71"}, False, {"r71_threshold": 1}),  # 14 阈值=1 变体
        ("S", {"r31": 0, "r32": 0}, "A", {"E-02"}, True, None),          # 15 单评分人 封顶 A
        ("S", {"r31": 0, "r32": 2}, "B", {"E-02", "R-72"}, True, None),  # 16 单评分人 + R-32×2
        ("S", {"r31": 2, "r32": 0}, "C", {"E-02", "R-71"}, True, None),  # 17 单评分人 + R-31×2
        ("S", {"r31": 2, "r32": 2}, "C", {"E-02", "R-72", "R-71"}, True, None),  # 18 单评分人+双触发
    ]

    def test_all_spec_cases(self):
        for auto, counts, want_grade, want_rules, single, config in self.CASES:
            with self.subTest(auto=auto, counts=counts, single=single, config=config):
                r = mod.apply_anti_distortion(auto, counts,
                                              single_reviewer=single, config=config)
                self.assertEqual(r.final_grade, want_grade)
                self.assertEqual({c.rule for c in r.corrections}, want_rules)
                self.assertEqual(r.auto_grade, auto)
                self.assertEqual(r.single_reviewer, single)

    def test_dual_trigger_order_r72_first_then_r71_cap(self):
        # spec 3 顺序决策：R-72 先降档（S→A），R-71 最后封顶（A→C）
        r = mod.apply_anti_distortion("S", {"r31": 2, "r32": 2})
        self.assertEqual(r.final_grade, "C")
        self.assertEqual([(c.rule, c.from_grade, c.to_grade) for c in r.corrections],
                         [("R-72", "S", "A"), ("R-71", "A", "C")])

    def test_e02_before_r72_order(self):
        # 终审 B-3 关键语义 #16：S + 单评分人 + R-32×2 → E-02(S→A) → R-72(A→B) = B
        r = mod.apply_anti_distortion("S", {"r31": 0, "r32": 2}, single_reviewer=True)
        self.assertEqual(r.final_grade, "B")
        self.assertEqual([(c.rule, c.from_grade, c.to_grade) for c in r.corrections],
                         [("E-02", "S", "A"), ("R-72", "A", "B")])

    def test_e02_not_raise_below_a(self):
        # E-02 仅封顶：auto 为 A/B/C/D 时不受影响（不抬升）
        self.assertEqual(
            mod.apply_anti_distortion("A", {"r31": 0, "r32": 0},
                                      single_reviewer=True).final_grade, "A")
        self.assertEqual(
            mod.apply_anti_distortion("B", {"r31": 0, "r32": 0},
                                      single_reviewer=True).final_grade, "B")
        self.assertEqual(
            mod.apply_anti_distortion("D", {"r31": 0, "r32": 0},
                                      single_reviewer=True).final_grade, "D")

    def test_invalid_auto_grade(self):
        with self.assertRaises(ValueError):
            mod.apply_anti_distortion("X", {"r31": 0, "r32": 0})

    def test_invalid_r71_cap(self):
        with self.assertRaises(ValueError):
            mod.apply_anti_distortion("S", {"r31": 2}, config={"r71_cap": "X"})

    def test_config_override(self):
        # 阈值可配置：r71_threshold=1 时 1 次红线即触发
        r = mod.apply_anti_distortion("S", {"r31": 1, "r32": 0},
                                      config={"r71_threshold": 1})
        self.assertEqual(r.final_grade, "C")


class TestCountDistortionEvents(unittest.TestCase):
    """计数：季度范围 / 结构化事件 ID / (issue, event_id) 去重 / fail-open。"""

    def test_quarter_scope_only(self):
        # B1 回归：季度外月份不计入
        with tempfile.TemporaryDirectory() as tmp:
            ev = os.path.join(tmp, "events", "测试智能体")
            write_event(os.path.join(ev, "2026-06.md"),
                        [("2026-06-05 10:00", "i0", "R-31:违反约束", -20)])
            write_event(os.path.join(ev, "2026-07.md"),
                        [("2026-07-05 10:00", "i1", "R-31:违反约束", -20)])
            write_event(os.path.join(ev, "2026-08.md"),
                        [("2026-08-05 10:00", "i2", "R-31:违反约束", -20)])
            write_event(os.path.join(ev, "2026-09.md"),
                        [("2026-09-05 10:00", "i3", "R-31:违反约束", -20)])
            counts = mod.count_distortion_events(
                os.path.join(tmp, "events"), "测试智能体",
                ["2026-07", "2026-08", "2026-09"])
            self.assertEqual(counts, {"r31": 3, "r32": 0})

    def test_structured_event_ids_not_text(self):
        # B2 回归：'红线'/'违规'/'-20' 文本不误计；仅 R-31/R-32 前缀计入
        with tempfile.TemporaryDirectory() as tmp:
            ev = os.path.join(tmp, "events", "测试智能体")
            write_event(os.path.join(ev, "2026-08.md"), [
                ("2026-08-01 10:00", "i1", "R-31:违反约束（红线）", -20),
                ("2026-08-02 10:00", "i2", "R-99:其他违规", -20),       # 含"违规"不计
                ("2026-08-03 10:00", "i3", "R-50:其他-20扣分", -20),     # 含 -20 不计
                ("2026-08-04 10:00", "i4", "R-21:自评;R-32:未提交自评", -5),  # R-32 计
            ])
            counts = mod.count_distortion_events(
                os.path.join(tmp, "events"), "测试智能体", ["2026-08"])
            self.assertEqual(counts, {"r31": 1, "r32": 1})

    def test_dedup_by_issue_event(self):
        # 同一 (issue, R-31) 跨月重复 → 只计 1 次
        with tempfile.TemporaryDirectory() as tmp:
            ev = os.path.join(tmp, "events", "测试智能体")
            write_event(os.path.join(ev, "2026-07.md"),
                        [("2026-07-01 10:00", "i1", "R-31:违反约束", -20)])
            write_event(os.path.join(ev, "2026-08.md"), [
                ("2026-08-01 10:00", "i1", "R-31:违反约束", -20),  # 与 7 月重复
                ("2026-08-02 10:00", "i2", "R-31:违反约束", -20),
            ])
            counts = mod.count_distortion_events(
                os.path.join(tmp, "events"), "测试智能体",
                ["2026-07", "2026-08"])
            self.assertEqual(counts, {"r31": 2, "r32": 0})

    def test_same_issue_multi_event_counted(self):
        # S-1 对齐：同一 issue 既有 R-21 自评又有 R-31 违规 → 事件均可计数
        with tempfile.TemporaryDirectory() as tmp:
            ev = os.path.join(tmp, "events", "测试智能体")
            write_event(os.path.join(ev, "2026-08.md"), [
                ("2026-08-01 10:00", "i1", "R-21:自评;R-22:更新能力档案", 10),
                ("2026-08-02 10:00", "i1", "R-31:违反约束", -20),
            ])
            counts = mod.count_distortion_events(
                os.path.join(tmp, "events"), "测试智能体", ["2026-08"])
            self.assertEqual(counts, {"r31": 1, "r32": 0})

    def test_missing_dir_fail_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            counts = mod.count_distortion_events(
                os.path.join(tmp, "events"), "不存在智能体",
                ["2026-07", "2026-08", "2026-09"])
            self.assertEqual(counts, {"r31": 0, "r32": 0})
            # 有目录但无月份文件 → 0
            os.makedirs(os.path.join(tmp, "events", "测试智能体"))
            counts = mod.count_distortion_events(
                os.path.join(tmp, "events"), "测试智能体", ["2026-07"])
            self.assertEqual(counts, {"r31": 0, "r32": 0})

    def test_fullwidth_colon_normalized(self):
        # N-4：全角冒号 'R-31：违反约束' 与半角 'R-31:违反约束' 同样计数（前缀解析归一化）
        with tempfile.TemporaryDirectory() as tmp:
            ev = os.path.join(tmp, "events", "测试智能体")
            write_event(os.path.join(ev, "2026-08.md"), [
                ("2026-08-01 10:00", "i1", "R-31:违反约束", -20),
                ("2026-08-02 10:00", "i2", "R-31：违反约束", -20),
                ("2026-08-03 10:00", "i3", "R-32：未提交自评", -5),
            ])
            counts = mod.count_distortion_events(
                os.path.join(tmp, "events"), "测试智能体", ["2026-08"])
            self.assertEqual(counts, {"r31": 2, "r32": 1})

    def test_skip_bad_month_strings(self):
        with tempfile.TemporaryDirectory() as tmp:
            counts = mod.count_distortion_events(
                os.path.join(tmp, "events"), "x", ["not-a-month", "2026-08"])
            self.assertEqual(counts, {"r31": 0, "r32": 0})


class TestSummarize(unittest.TestCase):
    def test_counts_only_summary(self):
        r = mod.AntiDistortionResult(
            auto_grade="", final_grade="", counts={"r31": 2, "r32": 0},
            corrections=[], config=dict(mod.DEFAULT_CONFIG))
        text = mod.summarize(r)
        self.assertIn("R-31 红线事件: 2 次", text)
        self.assertIn("触发 R-71", text)
        self.assertIn("R-32 缺自评事件: 0 次", text)
        self.assertIn("未触发", text)

    def test_full_summary_with_grade(self):
        r = mod.apply_anti_distortion("S", {"r31": 2, "r32": 0})
        text = mod.summarize(r)
        self.assertIn("R-71 cap: S → C", text)
        self.assertIn("最终等级: C", text)


class TestWriteDecisionLog(unittest.TestCase):
    def test_write_and_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents_root = os.path.join(tmp, "agents")
            result = mod.apply_anti_distortion("S", {"r31": 2, "r32": 0})
            p1 = mod.write_decision_log(agents_root, "测试智能体", "2026-Q3", result)
            p2 = mod.write_decision_log(agents_root, "测试智能体", "2026-Q3", result)
            self.assertEqual(p1, p2)
            with open(p1, encoding="utf-8") as f:
                content = f.read()
            self.assertIn("final_grade: C", content)
            self.assertIn("R-71 cap: S → C", content)
            # 幂等：同一次判定只记录一条
            self.assertEqual(content.count("防失真判定（2026-Q3）"), 1)

    def test_decision_sig_sha256(self):
        # N-6：决策签名对齐 sha256（64 位 hex；原实现为 sha1 截断 12 位）
        result = mod.apply_anti_distortion("S", {"r31": 2, "r32": 0})
        sig = mod._decision_sig(result)
        self.assertRegex(sig, r"^[0-9a-f]{64}$")
        # 同判定签名稳定；不同判定签名不同
        self.assertEqual(sig, mod._decision_sig(result))
        other = mod.apply_anti_distortion("A", {"r31": 0, "r32": 2})
        self.assertNotEqual(sig, mod._decision_sig(other))

    def test_append_different_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            agents_root = os.path.join(tmp, "agents")
            mod.write_decision_log(
                agents_root, "测试智能体", "2026-Q3",
                mod.apply_anti_distortion("S", {"r31": 2, "r32": 0}))
            mod.write_decision_log(
                agents_root, "测试智能体", "2026-Q3",
                mod.apply_anti_distortion("A", {"r31": 0, "r32": 2}))
            path = os.path.join(agents_root, "reviews", "scoring",
                                "anti-distortion", "测试智能体", "2026-Q3.md")
            with open(path, encoding="utf-8") as f:
                content = f.read()
            self.assertEqual(content.count("防失真判定（2026-Q3）"), 2)
            self.assertIn("final_grade: C", content)
            self.assertIn("final_grade: B", content)


class TestCLI(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, MODULE, *args],
                              capture_output=True, text=True)

    def test_cli_count_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev = os.path.join(tmp, "events", "测试智能体")
            write_event(os.path.join(ev, "2026-08.md"), [
                ("2026-08-01 10:00", "i1", "R-31:违反约束", -20),
                ("2026-08-02 10:00", "i2", "R-32:未提交自评", -5),
            ])
            proc = self.run_cli(
                "count", "--events-dir", os.path.join(tmp, "events"),
                "--agent", "测试智能体", "--months", "2026-08", "--json")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout), {"r31": 1, "r32": 1})

    def test_cli_check_plain(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev = os.path.join(tmp, "events", "测试智能体")
            write_event(os.path.join(ev, "2026-08.md"), [
                ("2026-08-01 10:00", "i1", "R-31:违反约束", -20),
                ("2026-08-02 10:00", "i2", "R-31:违反约束", -20),
            ])
            proc = self.run_cli(
                "check", "--events-dir", os.path.join(tmp, "events"),
                "--agent", "测试智能体", "--months", "2026-08")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("触发 R-71", proc.stdout)
            self.assertIn("R-31 红线事件: 2 次", proc.stdout)

    def test_cli_apply_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            ev = os.path.join(tmp, "events", "测试智能体")
            write_event(os.path.join(ev, "2026-08.md"), [
                ("2026-08-01 10:00", "i1", "R-31:违反约束", -20),
                ("2026-08-02 10:00", "i2", "R-31:违反约束", -20),
            ])
            proc = self.run_cli(
                "apply", "--auto-grade", "S",
                "--events-dir", os.path.join(tmp, "events"),
                "--agent", "测试智能体", "--months", "2026-08", "--json")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["auto_grade"], "S")
            self.assertEqual(data["final_grade"], "C")
            self.assertEqual(data["corrections"][0]["rule"], "R-71")

    def test_cli_apply_single_reviewer_e02(self):
        """CLI apply --single-reviewer：无事件时 S → E-02 封顶 A。"""
        with tempfile.TemporaryDirectory() as tmp:
            ev = os.path.join(tmp, "events", "测试智能体")
            write_event(os.path.join(ev, "2026-08.md"), [])
            proc = self.run_cli(
                "apply", "--auto-grade", "S", "--single-reviewer",
                "--events-dir", os.path.join(tmp, "events"),
                "--agent", "测试智能体", "--months", "2026-08", "--json")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertEqual(data["auto_grade"], "S")
            self.assertEqual(data["final_grade"], "A")
            self.assertEqual(data["corrections"][0]["rule"], "E-02")

    def test_cli_bad_month_exit2(self):
        proc = self.run_cli(
            "count", "--events-dir", "/nonexistent",
            "--agent", "x", "--months", "2026-13", "--json")
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
