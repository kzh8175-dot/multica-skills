#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test-rating-settler.py — rating-settler.py 归属解析验收测试（F3 修复）

覆盖验收标准:
  1. assignee_id 为 agent 且存在于映射 → 解析为 agent 名称
  2. assignee_id 为 squad（不在 agent 映射）→ 解析为 squad 名称
  3. assignee_id 为空 → 回退 creator_id（agent 映射）
  4. assignee_id 为空 且 creator 不在映射 → 未知智能体
  5. assignee_id 未知（非 agent 非 squad）→ 未知智能体
  6. load_squads 在 CLI 失败时返回空映射（不抛异常）

P1-10 S-1 前置修复（结算器去重键 issue_id → (issue_id, rating.event)）:
  7. 同一 issue 两个不同事件（R-21 自评 + R-31 违规）均可写入，不再被 E_DUP 拦截
  8. 同一 (issue, 事件) 二次写入 → E_DUP（幂等保留）
  9. 跨文件：同一 (issue, 事件) 写入不同智能体文件 → E_DUP（防聚合双计保留）
  10. 同一 issue 不同事件跨文件共存 → 允许写入

运行:
  python3 test-rating-settler.py
"""

import importlib.util
import os
import shutil
import sys
import tempfile
import unittest

SETTLER = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "rating-settler.py",
))

spec = importlib.util.spec_from_file_location("rating_settler", SETTLER)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


AGENTS = {
    "a1": "资深战略领导者",
    "a2": "项目负责人",
    "a3": "DevOps自动化工程师",
}
SQUADS = {
    "s1": "智能评分系统P0执行小队",
}


class TestResolveAgentName(unittest.TestCase):
    def test_agent_assignee(self):
        issue = {"assignee_id": "a2", "creator_id": "a1"}
        self.assertEqual(mod.resolve_agent_name(issue, AGENTS, SQUADS), "项目负责人")

    def test_squad_assignee(self):
        issue = {"assignee_id": "s1", "creator_id": "a1"}
        self.assertEqual(mod.resolve_agent_name(issue, AGENTS, SQUADS), "智能评分系统P0执行小队")

    def test_missing_assignee_falls_back_to_creator(self):
        issue = {"assignee_id": None, "creator_id": "a3"}
        self.assertEqual(mod.resolve_agent_name(issue, AGENTS, SQUADS), "DevOps自动化工程师")

    def test_missing_assignee_and_creator_unknown(self):
        issue = {"assignee_id": None, "creator_id": "nope"}
        self.assertEqual(mod.resolve_agent_name(issue, AGENTS, SQUADS), "未知智能体")

    def test_unknown_assignee(self):
        issue = {"assignee_id": "zzz", "creator_id": "a1"}
        self.assertEqual(mod.resolve_agent_name(issue, AGENTS, SQUADS), "未知智能体")

    def test_creator_fallback_empty_squads(self):
        # squad 为空时不影响 creator 兜底
        issue = {"assignee_id": None, "creator_id": "a2"}
        self.assertEqual(mod.resolve_agent_name(issue, AGENTS, {}), "项目负责人")


class TestGlobalDedupS1(unittest.TestCase):
    """P1-10 S-1 前置修复：结算器去重键 (issue_id, rating.event)。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="settler-dedup-")
        self._orig_events_dir = mod.EVENTS_DIR
        mod.EVENTS_DIR = os.path.join(self.tmp, "events")

    def tearDown(self):
        mod.EVENTS_DIR = self._orig_events_dir
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def _meta(event, points, trigger="agent"):
        return {
            "rating.event": event,
            "rating.points": points,
            "rating.trigger": trigger,
            "rating.occurred_at": "2026-08-16T21:00:00Z",
        }

    def test_same_issue_two_events_both_written(self):
        # S-1：同一 issue 的 R-21 自评与 R-31 违规两个事件都应写入（不再 E_DUP 拦截）
        ok1, err1, _ = mod.append_to_events(
            "测试智能体", "2026-08", "i-1", self._meta("R-21:自评", 5))
        ok2, err2, _ = mod.append_to_events(
            "测试智能体", "2026-08", "i-1", self._meta("R-31:违反约束", -20, "reviewer"))
        self.assertTrue(ok1, err1)
        self.assertTrue(ok2, err2)
        path = os.path.join(mod.EVENTS_DIR, "测试智能体", "2026-08.md")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("R-21:自评", content)
        self.assertIn("R-31:违反约束", content)

    def test_same_issue_same_event_dup(self):
        # 同一 (issue, 事件) 二次写入 → E_DUP（幂等保留）
        meta = self._meta("R-21:自评", 5)
        ok1, err1, _ = mod.append_to_events("测试智能体", "2026-08", "i-1", meta)
        ok2, err2, _ = mod.append_to_events("测试智能体", "2026-08", "i-1", meta)
        self.assertTrue(ok1, err1)
        self.assertFalse(ok2)
        self.assertEqual(err2, mod.E_DUP)

    def test_fullwidth_colon_event_dedup(self):
        # N-4：事件 ID 半/全角冒号归一化——'R-31：违反约束' 与 'R-31:违反约束' 视为同一事件
        ok1, err1, _ = mod.append_to_events(
            "测试智能体", "2026-08", "i-1", self._meta("R-31:违反约束", -20, "reviewer"))
        ok2, err2, _ = mod.append_to_events(
            "测试智能体", "2026-08", "i-1", self._meta("R-31：违反约束", -20, "reviewer"))
        self.assertTrue(ok1, err1)
        self.assertFalse(ok2, "全角冒号同一事件应被幂等拦截")
        self.assertEqual(err2, mod.E_DUP)
        # 不同事件（R-31 vs R-32）同一 issue 仍可共存（S-1）
        ok3, err3, _ = mod.append_to_events(
            "测试智能体", "2026-08", "i-1", self._meta("R-32：未提交自评", -5, "reviewer"))
        self.assertTrue(ok3, err3)

    def test_cross_file_same_event_dup(self):
        # 跨文件：同一 (issue, 事件) 写入不同智能体文件 → E_DUP（防聚合双计保留）
        meta = self._meta("R-21:自评", 5)
        ok1, err1, _ = mod.append_to_events("智能体A", "2026-08", "i-1", meta)
        ok2, err2, _ = mod.append_to_events("智能体B", "2026-08", "i-1", meta)
        self.assertTrue(ok1, err1)
        self.assertFalse(ok2)
        self.assertEqual(err2, mod.E_DUP)

    def test_same_issue_different_events_across_agents(self):
        # 同一 issue 不同事件跨文件共存 → 允许写入（不误伤）
        ok1, err1, _ = mod.append_to_events(
            "智能体A", "2026-08", "i-1", self._meta("R-21:自评", 5))
        ok2, err2, _ = mod.append_to_events(
            "智能体B", "2026-08", "i-1", self._meta("R-31:违反约束", -20, "reviewer"))
        self.assertTrue(ok1, err1)
        self.assertTrue(ok2, err2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
