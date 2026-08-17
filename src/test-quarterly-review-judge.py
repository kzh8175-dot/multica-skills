#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test-quarterly-review-judge.py — quarterly-review-judge.py 验收测试（方案C P1-9 / KA-74 · P1-10 联调）

覆盖验收标准:
  1. 计算正确性：人评分 / 人评最终分 / 综合分 / 等级 与手工计算逐项一致
  2. 表单回填：填维度分后运行，全部空白被自动判定并写回
  3. 幂等：二次运行 0 写入
  4. dry-run 零写
  5. 待填写：人评维度分未填 no-op 不崩
  6. 防失真（P1-10 联调）：修正统一由 anti-distortion-rules 施加——
     事件流水 R-31→上限C / R-32→降一档 / E-02 单评分人上限A；
     judge 只输出原始等级 + single_reviewer 并写决策日志
  7. 等级边界：95/85/70/60 档位切换
  8. 缺失/异常：缺表单 / 缺客观分 / 非权重行 不崩

运行:
  python3 test-quarterly-review-judge.py
  python3 -m unittest test-quarterly-review-judge -v
"""

import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

JUDGE = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "quarterly-review-judge.py",
))
PYTHON = sys.executable

QUARTER = "2026-Q3"
AGENT = "测试智能体"


def load_judge():
    spec = importlib.util.spec_from_file_location("quarterly_review_judge", JUDGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class JudgeComputeTest(unittest.TestCase):
    """纯计算函数（不触碰文件系统）。"""

    @classmethod
    def setUpClass(cls):
        cls.j = load_judge()

    def make_dims(self, scores1, scores2=None):
        """构造 dims：scores1/2 为 [维度1..5] 分数，None 表示缺失。"""
        dims = []
        for i, (name, weight) in enumerate(self.j.DEFAULT_DIMENSIONS):
            s = {}
            if scores1 is not None:
                s[0] = scores1[i]
            if scores2 is not None:
                s[1] = scores2[i]
            dims.append({"name": name, "weight": weight, "scores": s})
        return dims

    def test_reviewer_score_formula(self):
        """R-52：Σ(维度×权重)×20，标准权重下为整数。"""
        j = self.j
        # 全 5 分 → 5×100/100×20 = 100
        self.assertEqual(j.compute_reviewer_score(self.make_dims([5, 5, 5, 5, 5]), 0), 100)
        # 全 4 分 → 80
        self.assertEqual(j.compute_reviewer_score(self.make_dims([4, 4, 4, 4, 4]), 0), 80)
        # 5,4,5,4,5 → (1.5+1.0+1.0+0.6+0.5)×20 = 92
        self.assertEqual(j.compute_reviewer_score(self.make_dims([5, 4, 5, 4, 5]), 0), 92)
        # 缺任一维度 → None
        self.assertIsNone(j.compute_reviewer_score(self.make_dims([5, 5, None, 5, 5]), 0))
        # 两评分人各自独立
        dims = self.make_dims([5, 5, 5, 5, 5], [4, 4, 4, 4, 4])
        self.assertEqual(j.compute_reviewer_score(dims, 1), 80)

    def test_grade_boundaries(self):
        """R-62~R-66 档位边界：95/85/70/60。"""
        j = self.j
        self.assertEqual(j.grade_for(95), "S")
        self.assertEqual(j.grade_for(94.9), "A")
        self.assertEqual(j.grade_for(85), "A")
        self.assertEqual(j.grade_for(84.9), "B")
        self.assertEqual(j.grade_for(70), "B")
        self.assertEqual(j.grade_for(69.9), "C")
        self.assertEqual(j.grade_for(60), "C")
        self.assertEqual(j.grade_for(59.9), "D")

    def test_apply_caps(self):
        """防失真叠加（P1-10 联调后统一由 anti-distortion-rules 唯一权威）。

        `apply_caps`/`parse_anti_fraud` 已退役（judge 只输出原始等级 + single_reviewer），
        叠加逻辑在 `apply_anti_distortion`。关键行为变更（终审 B-3）：
        S + 单评分人 + R-32×2 → E-02(S→A) → R-72(A→B) = **B**（旧顺序为 A）。
        """
        j = self.j
        ad = j._ANTI_MOD
        self.assertIsNotNone(ad, "anti-distortion 模块应可加载")
        # 无触发：正常数据回归
        self.assertEqual(ad.apply_anti_distortion("S", {"r31": 0, "r32": 0}).final_grade, "S")
        # R-71：上限 C（S/A/B → C；C 不变；D 不抬升）
        self.assertEqual(ad.apply_anti_distortion("S", {"r31": 2, "r32": 0}).final_grade, "C")
        self.assertEqual(ad.apply_anti_distortion("A", {"r31": 2, "r32": 0}).final_grade, "C")
        self.assertEqual(ad.apply_anti_distortion("B", {"r31": 2, "r32": 0}).final_grade, "C")
        self.assertEqual(ad.apply_anti_distortion("C", {"r31": 2, "r32": 0}).final_grade, "C")
        self.assertEqual(ad.apply_anti_distortion("D", {"r31": 2, "r32": 0}).final_grade, "D")
        # R-72：降一档
        self.assertEqual(ad.apply_anti_distortion("S", {"r31": 0, "r32": 2}).final_grade, "A")
        self.assertEqual(ad.apply_anti_distortion("A", {"r31": 0, "r32": 2}).final_grade, "B")
        self.assertEqual(ad.apply_anti_distortion("D", {"r31": 0, "r32": 2}).final_grade, "D")
        # E-02：单评分人上限 A（仅 S → A；A/B/C/D 不受影响）
        self.assertEqual(ad.apply_anti_distortion(
            "S", {"r31": 0, "r32": 0}, single_reviewer=True).final_grade, "A")
        self.assertEqual(ad.apply_anti_distortion(
            "A", {"r31": 0, "r32": 0}, single_reviewer=True).final_grade, "A")
        self.assertEqual(ad.apply_anti_distortion(
            "B", {"r31": 0, "r32": 0}, single_reviewer=True).final_grade, "B")
        self.assertEqual(ad.apply_anti_distortion(
            "D", {"r31": 0, "r32": 0}, single_reviewer=True).final_grade, "D")
        # E-02 + R-72 叠加（终审 B-3）：S + 单评分人 + R-32×2 → B
        self.assertEqual(ad.apply_anti_distortion(
            "S", {"r31": 0, "r32": 2}, single_reviewer=True).final_grade, "B")
        # E-02 + R-71 叠加：S + 单评分人 + R-31×2 → C（R-71 为最终天花板）
        self.assertEqual(ad.apply_anti_distortion(
            "S", {"r31": 2, "r32": 0}, single_reviewer=True).final_grade, "C")

    def test_fmt_score(self):
        j = self.j
        self.assertEqual(j.fmt_score(92), "92")
        self.assertEqual(j.fmt_score(90.0), "90")
        self.assertEqual(j.fmt_score(90.5), "90.5")
        # 浮点尾差：整数综合分不得显示为 X.0
        self.assertEqual(j.fmt_score(92.00000000000001), "92")
        self.assertEqual(j.fmt_score(9.000000000000002), "9")
        self.assertEqual(j.fmt_score(90.50000000000001), "90.5")


class JudgeFormTest(unittest.TestCase):
    """端到端：临时 agents 根 + 表单夹具。"""

    FORMAT = """# {agent} - 季度人评表单

**季度**: {quarter}
**生成日期**: 2026-08-17
**规则版本**: 方案C (R-51~R-76)

---

## 一、季度客观分（系统自动汇总，权重80%）

| 月份 | 积分 | 基准 | 百分制(上限120) |
|------|:---:|:---:|:---:|
| 2026-07 | 300 | 400 | 75 |
| 2026-08 | 300 | 400 | 75 |
| 2026-09 | 300 | 400 | 75 |

**季度客观分** = 3个月均值 = **{objective}** 分（(75+75+75) / 3）

> ⚠️ 上表积分流水若缺失请补记: reviews/scoring/events/{{agent}}/YYYY-MM.md
> 缺失月份按 0 计入均值并标记（如需排除缺失月，由负责人按 E-01 裁定）。

---

## 二、季度人评（人工填写，权重20%）

请负责人 + 至少1位相关协作方，按 1-5 分独立评分：

| 维度 | 权重 | 评分人1 | 评分人2 | 备注 |
|------|:---:|:---:|:---:|------|
| 交付质量 | 30% | {d1} | {e1} | |
| 专业能力 | 25% | {d2} | {e2} | |
| 自我优化 | 20% | {d3} | {e3} | |
| 协作与沟通 | 15% | {d4} | {e4} | |
| 任务完成度 | 10% | {d5} | {e5} | |

**人评分1** = Σ(维度×权重)×20 = ______
**人评分2** = Σ(维度×权重)×20 = ______
**人评最终分** = (评分人1+评分人2)/2 = ______

---

## 三、季度综合分与等级

**季度综合分 = 客观分×0.8 + 人评最终分×0.2 = ______**

| 等级 | 区间 | 判定 | 定位 |
|------|------|:---:|------|
| S | ≥95 |  | 卓越标杆 |
| A | 85-94 |  | 优秀骨干 |
| B | 70-84 |  | 稳定主力 |
| C | 60-69 |  | 待提升 |
| D | <60 |  | 风险 |

**本季等级**: ______ {cap}

---

## 四、防失真校验（自动）

- [ ] 红线一票否决检查: {fraud}
- [ ] 自评缺失检查: （累计未提交自评次数）
- [ ] 人评评分人 ≥ 2: （人数）
- [ ] 人评未含"效率"维度: 通过（模板已剔除）

---

## 五、异常处理记录

| 异常类型 | 是否触发 | 处理动作 |
|---------|:---:|---------|
| 积分流水缺失 |  | E-01: 补记或排除该月 |
| 评分人不足 |  | E-02: 单评分人可用，等级上限A |
| 档案缺失 |  | E-03: 先创建档案 |
| 等级=D |  | E-04: 升级最高决策者专项复盘 |

---

## 六、下季改进建议

- {{建议1}}
- {{建议2}}
"""

    def build_root(self, objective=75, d=None, e=None, cap="", fraud="红线计数=0次|未触发(需≥2次)"):
        """构造临时 agents 根，返回其路径。"""
        root = tempfile.mkdtemp(prefix="ka74-test-")
        d = d or [None] * 5
        e = e or [None] * 5
        form = self.FORMAT.format(
            agent=AGENT, quarter=QUARTER, objective=objective, cap=cap, fraud=fraud,
            d1=d[0] or "", d2=d[1] or "", d3=d[2] or "", d4=d[3] or "", d5=d[4] or "",
            e1=e[0] or "", e2=e[1] or "", e3=e[2] or "", e4=e[3] or "", e5=e[4] or "",
        )
        qdir = os.path.join(root, "reviews", "scoring", "quarterly", AGENT)
        os.makedirs(qdir)
        with open(os.path.join(qdir, f"{QUARTER}.md"), "w", encoding="utf-8") as f:
            f.write(form)
        return root

    def read_form(self, root):
        path = os.path.join(root, "reviews", "scoring", "quarterly", AGENT, f"{QUARTER}.md")
        with open(path, encoding="utf-8") as f:
            return f.read()

    def judge(self, root, dry_run=False):
        j = load_judge()
        return j.judge_form(AGENT, QUARTER, root, dry_run=dry_run)

    def write_events(self, root, rows):
        """写入事件流水：rows = [(month, issue, event, points), ...]（R-31/R-32 计数源）。"""
        for month, issue, event, pts in rows:
            ev_dir = os.path.join(root, "reviews", "scoring", "events", AGENT)
            os.makedirs(ev_dir, exist_ok=True)
            path = os.path.join(ev_dir, f"{month}.md")
            if not os.path.exists(path):
                with open(path, "w", encoding="utf-8") as f:
                    f.write("| 时间 | 任务 | 事件 | 积分 |\n")
                    f.write("|------|------|------|:---:|\n")
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"| 2026-{month[5:]} 10:00 | {issue} | {event} | {pts:+d} |\n")

    def test_end_to_end_fill(self):
        """维度分就绪 → 客观/人评/综合/等级 全部判定并回填。"""
        # 客观75，评分人1 全5 → 100；评分人2 全4 → 80；最终 90；综合 78；等级 B
        root = self.build_root(objective=75, d=[5, 5, 5, 5, 5], e=[4, 4, 4, 4, 4])
        r = self.judge(root)
        self.assertEqual(r["stage"], "ok")
        self.assertTrue(r["changed"])
        self.assertEqual(r["human_scores"], {"评分人1": 100, "评分人2": 80})
        self.assertEqual(r["human_final"], 90)
        self.assertAlmostEqual(r["comprehensive"], 78)
        self.assertEqual(r["grade"], "B")

        text = self.read_form(root)
        self.assertIn("**人评分1** = Σ(维度×权重)×20 = **100**", text)
        self.assertIn("**人评分2** = Σ(维度×权重)×20 = **80**", text)
        self.assertIn("**人评最终分** = (评分人1+评分人2)/2 = **90**", text)
        self.assertIn("**季度综合分 = 客观分×0.8 + 人评最终分×0.2 = 78**", text)
        self.assertIn("**本季等级**: **B**", text)
        self.assertIn("| B | 70-84 | ☑ | 稳定主力 |", text)
        self.assertIn("- [ ] 人评评分人 ≥ 2: 2人（满足）", text)

    def test_idempotent_second_run_no_write(self):
        """二次运行 0 写入。"""
        root = self.build_root(objective=75, d=[5, 5, 5, 5, 5], e=[4, 4, 4, 4, 4])
        first = self.judge(root)
        self.assertTrue(first["changed"])
        before = self.read_form(root)
        second = self.judge(root)
        self.assertFalse(second["changed"])
        self.assertEqual(second["note"], "已是最新（无变化）")
        self.assertEqual(self.read_form(root), before)

    def test_dry_run_no_write(self):
        """--dry-run 判定但不写入。"""
        root = self.build_root(objective=75, d=[5, 5, 5, 5, 5], e=[4, 4, 4, 4, 4])
        r = self.judge(root, dry_run=True)
        self.assertEqual(r["stage"], "ok")
        self.assertTrue(r["changed"])  # 标注「将写入」
        self.assertNotIn("**100**", self.read_form(root))

    def test_pending_no_scores(self):
        """维度分未填 → pending，不写不崩。"""
        root = self.build_root(objective=75)
        r = self.judge(root)
        self.assertEqual(r["stage"], "pending")
        self.assertFalse(r["changed"])
        self.assertIn("______", self.read_form(root))

    def test_missing_form(self):
        root = tempfile.mkdtemp(prefix="ka74-test-")
        r = self.judge(root)
        self.assertEqual(r["stage"], "missing")

    def test_missing_objective(self):
        """表单缺客观分 → no-objective，不崩。"""
        root = self.build_root(objective=75, d=[5, 5, 5, 5, 5])
        # 抹掉客观分行
        path = os.path.join(root, "reviews", "scoring", "quarterly", AGENT, f"{QUARTER}.md")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        text = re.sub(r"\*\*季度客观分\*\*.*", "**季度客观分** = 缺失", text)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        r = self.judge(root)
        self.assertEqual(r["stage"], "no-objective")

    def test_single_reviewer_e02(self):
        """单评分人（评分人1 全5，客观100）→ 综合100=S，E-02 上限A。"""
        root = self.build_root(objective=100, d=[5, 5, 5, 5, 5], e=[None] * 5)
        r = self.judge(root)
        self.assertEqual(r["stage"], "ok")
        self.assertTrue(r["single_reviewer"])
        self.assertEqual(r["comprehensive"], 100)
        self.assertEqual(r["grade"], "A")  # 无 E-02 应为 S，单评分人 → A
        text = self.read_form(root)
        self.assertIn("- [ ] 人评评分人 ≥ 2: 1人（E-02 单评分人，等级上限A）", text)
        # 单评分人时「人评最终分」回填该评分人分数，并标注非平均
        self.assertIn("（E-02 单评分人，非平均）", text)
        self.assertIn("**人评最终分** = (评分人1+评分人2)/2 = **100**（E-02 单评分人，非平均）", text)

    def test_r71_cap_c(self):
        """R-71 触发（事件流水 2 个 R-31 不同 issue）→ 原始 S 被压到 C。

        P1-10 联调后：修正来自事件流水计数（count_distortion_events），
        不再解析表单 cap_note/防失真区文案（parse_anti_fraud 已退役）。
        """
        root = self.build_root(objective=100, d=[5, 5, 5, 5, 5], e=[5, 5, 5, 5, 5])
        self.write_events(root, [
            ("2026-07", "i-1", "R-31:违反约束", -20),
            ("2026-08", "i-2", "R-31:违反约束", -20),
        ])
        r = self.judge(root)
        self.assertEqual(r["stage"], "ok")
        self.assertEqual(r["auto_grade"], "S")
        self.assertEqual(r["counts"], {"r31": 2, "r32": 0})
        self.assertEqual(r["triggers"], ["R-71"])
        self.assertEqual(r["grade"], "C")
        text = self.read_form(root)
        self.assertIn("**本季等级**: **C**", text)

    def test_r72_downgrade(self):
        """R-72 触发（事件流水 2 个 R-32 不同 issue）→ 原始 A 降为 B。"""
        root = self.build_root(objective=90, d=[5, 5, 5, 5, 5], e=[4, 4, 5, 4, 4])
        self.write_events(root, [
            ("2026-07", "i-1", "R-32:未提交自评", -5),
            ("2026-08", "i-2", "R-32:未提交自评", -5),
        ])
        r = self.judge(root)
        self.assertEqual(r["stage"], "ok")
        self.assertEqual(r["auto_grade"], "A")
        self.assertEqual(r["counts"], {"r31": 0, "r32": 2})
        self.assertEqual(r["triggers"], ["R-72"])
        self.assertEqual(r["grade"], "B")
        self.assertIn("**本季等级**: **B**", self.read_form(root))

    def test_single_reviewer_plus_r32(self):
        """S + 单评分人 + R-32×2 → E-02(S→A) → R-72(A→B) = B（终审 B-3 行为变更）。

        旧实现（apply_caps 顺序 R-72→R-71→E-02）得 A；新顺序 E-02→R-72→R-71 得 B。
        """
        root = self.build_root(objective=100, d=[5, 5, 5, 5, 5], e=[None] * 5)
        self.write_events(root, [
            ("2026-07", "i-1", "R-32:未提交自评", -5),
            ("2026-08", "i-2", "R-32:未提交自评", -5),
        ])
        r = self.judge(root)
        self.assertEqual(r["stage"], "ok")
        self.assertTrue(r["single_reviewer"])
        self.assertEqual(r["auto_grade"], "S")
        self.assertEqual(r["grade"], "B")
        self.assertEqual(r["triggers"], ["E-02", "R-72"])

    def test_decision_log_written_idempotent(self):
        """judge 调用 write_decision_log 留痕；重复运行幂等（不重复追加）。"""
        root = self.build_root(objective=75, d=[5, 5, 5, 5, 5], e=[4, 4, 4, 4, 4])
        first = self.judge(root)
        self.assertEqual(first["stage"], "ok")
        log_path = os.path.join(root, "reviews", "scoring",
                                "anti-distortion", AGENT, f"{QUARTER}.md")
        self.assertTrue(os.path.isfile(log_path), "决策日志应写入")
        with open(log_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("final_grade: B", content)
        # 幂等：二次运行（无输入变化）不重复追加
        self.judge(root)
        with open(log_path, encoding="utf-8") as f:
            self.assertEqual(f.read(), content)

    def test_grade_table_marker_only_selected_row(self):
        """等级表仅标记判定行。"""
        root = self.build_root(objective=75, d=[5, 5, 5, 5, 5], e=[4, 4, 4, 4, 4])
        self.judge(root)
        text = self.read_form(root)
        self.assertEqual(text.count("☑"), 1)
        self.assertIn("| B | 70-84 | ☑ | 稳定主力 |", text)

    def test_grade_table_resync_on_grade_change(self):
        """等级变更后重跑 → 旧 ☑ 清除，仅当前行 ☑（纯函数刷新，防残留）。"""
        root = self.build_root(objective=100, d=[3, 3, 3, 3, 3], e=[3, 3, 3, 3, 3])
        first = self.judge(root)
        # 全 3 分 → 人评 60 → 综合 100×0.8+60×0.2=92 → A
        self.assertEqual(first["grade"], "A")
        text = self.read_form(root)
        self.assertEqual(text.count("☑"), 1)
        self.assertIn("| A | 85-94 | ☑ | 优秀骨干 |", text)

        # 维度分 3→1 → 人评 20 → 综合 84 → B（跨 A/B 档），重跑后 ☑ 应迁移
        path = os.path.join(root, "reviews", "scoring", "quarterly", AGENT, f"{QUARTER}.md")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        text = text.replace("| 3 | 3 | |", "| 1 | 1 | |")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        second = self.judge(root)
        self.assertEqual(second["grade"], "B")
        text = self.read_form(root)
        self.assertEqual(text.count("☑"), 1)  # 旧 A 行 ☑ 已清除
        self.assertIn("| B | 70-84 | ☑ | 稳定主力 |", text)
        self.assertNotIn("| A | 85-94 | ☑ |", text)

    def test_resync_on_input_change(self):
        """维度分变化后重跑 → 判定同步刷新（输出为输入的纯函数）。"""
        root = self.build_root(objective=75, d=[5, 5, 5, 5, 5], e=[4, 4, 4, 4, 4])
        self.judge(root)
        # 修改评分人1 维度分（交付质量 5→1），重跑
        path = os.path.join(root, "reviews", "scoring", "quarterly", AGENT, f"{QUARTER}.md")
        with open(path, encoding="utf-8") as f:
            text = f.read()
        text = text.replace("| 交付质量 | 30% | 5 | 4 |", "| 交付质量 | 30% | 1 | 4 |")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        r = self.judge(root)
        self.assertTrue(r["changed"])
        # 评分人1: 1,5,5,5,5 → (0.3+1.25+1+0.75+0.5)*20=76；最终(76+80)/2=78；综合75*0.8+78*0.2=75.6 → B
        self.assertEqual(r["human_scores"]["评分人1"], 76)
        self.assertAlmostEqual(r["human_final"], 78)
        self.assertAlmostEqual(r["comprehensive"], 75.6)

    def test_fresh_objective_only_report_pending(self):
        """聚合器生成的无人评区客观分报告 → pending（等待调度器人评表单）。"""
        root = tempfile.mkdtemp(prefix="ka74-test-")
        qdir = os.path.join(root, "reviews", "scoring", "quarterly", AGENT)
        os.makedirs(qdir)
        fresh = (
            f"# {AGENT} - 季度客观分报告\n\n"
            f"**季度**: {QUARTER}\n\n"
            f"## 季度客观分\n\n"
            f"| 月份 | 积分 | 基准 | 百分制 |\n"
            f"|------|:---:|:---:|:---:|\n"
            f"| 2026-07 | 300 | 400 | 75 |\n\n"
            f"**季度客观分** = (75+75+75) / 3 = **75**\n"
        )
        with open(os.path.join(qdir, f"{QUARTER}.md"), "w", encoding="utf-8") as f:
            f.write(fresh)
        r = self.judge(root)
        self.assertEqual(r["stage"], "pending")


class JudgeCliTest(unittest.TestCase):
    """CLI 端到端（子进程）。"""

    def run_cli(self, root, *args):
        cmd = [PYTHON, JUDGE, "--agents-dir", root, "--quarter", QUARTER, *args]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return proc

    def test_cli_dry_run_exit0(self):
        root = self.build_root()
        proc = self.run_cli(root, "--dry-run")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("待填写", proc.stdout)

    def test_cli_status_no_write(self):
        root = self.build_root()
        proc = self.run_cli(root, "--status")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("待填写", proc.stdout)

    def test_cli_json(self):
        root = self.build_root(d=[5, 5, 5, 5, 5], e=[4, 4, 4, 4, 4])
        proc = self.run_cli(root, "--json")
        self.assertEqual(proc.returncode, 0)
        import json
        data = json.loads(proc.stdout)
        self.assertEqual(data[0]["grade"], "B")
        self.assertEqual(data[0]["stage"], "ok")

    def test_cli_bad_quarter_exit2(self):
        root = self.build_root()
        proc = self.run_cli(root, "--quarter", "bad")
        self.assertEqual(proc.returncode, 2)

    def test_cli_reject_agent_path_traversal(self):
        """--agent 含路径分隔符 / .. / 空值 → exit 2（防读写 quarterly/ 之外）。"""
        root = self.build_root()
        for bad in ("../escape", "..", "a/b", "a\\b", ".", ""):
            proc = self.run_cli(root, "--agent", bad)
            self.assertEqual(proc.returncode, 2, f"--agent {bad!r} 应被拒绝")

    def build_root(self, objective=75, d=None, e=None):
        root = tempfile.mkdtemp(prefix="ka74-cli-")
        d = d or [None] * 5
        e = e or [None] * 5
        form = JudgeFormTest.FORMAT.format(
            agent=AGENT, quarter=QUARTER, objective=objective, cap="", fraud="红线计数=0次|未触发",
            d1=d[0] or "", d2=d[1] or "", d3=d[2] or "", d4=d[3] or "", d5=d[4] or "",
            e1=e[0] or "", e2=e[1] or "", e3=e[2] or "", e4=e[3] or "", e5=e[4] or "",
        )
        qdir = os.path.join(root, "reviews", "scoring", "quarterly", AGENT)
        os.makedirs(qdir)
        with open(os.path.join(qdir, f"{QUARTER}.md"), "w", encoding="utf-8") as f:
            f.write(form)
        return root


if __name__ == "__main__":
    unittest.main(verbosity=2)
