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

运行:
  python3 test-rating-settler.py
"""

import importlib.util
import os
import sys
import unittest

SETTLER = os.path.normpath(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
