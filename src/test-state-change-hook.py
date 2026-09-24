#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test-state-change-hook.py — 状态变更钩子（P2-11 / KA-76）验收测试

覆盖验收标准:
  1. 事件映射（纯函数 map_transition）
     - → done: R-01 按时完成 +20 / R-02 超时完成 +10（按 due_date 判定）
     - → cancelled: R-03 任务未完成/失败 -15（from=done 的取消不重复记失败，防双计）
     - done/in_review → todo/in_progress: R-04 任务被退回返工 -10
     - 非评分 transition（in_progress→in_review / →blocked / backlog→todo）不写事件
  2. 按时/超时判定（classify_completion）
     - 无 due_date → 按时；按日期比较，当天完成 → 按时
  3. 跳过逻辑（skip_reason）
     - rating.status=pending → 延后（event-pending，尊重已有事件）
     - rating.status=escalated → 跳过（escalated-blocked）
     - rating.status=credited 且同一 R-xx → 跳过（credited-same-event，防双计）
     - credited 但不同事件 → 允许写入（新事件）
  4. 事件 metadata 构建（build_event_metadata）
     - 5 键齐备；trigger=reviewer（行为类事件，P2-11 授权系统自动化）
     - points 为整数（正负正确）
  5. 决策流（decide / process_issue）
     - 无 baseline → 自动建 baseline（不写事件）
     - last_status == 当前 → no-transition
     - 检测到 transition → 写事件 + 更新 last_status
     - event-pending → 延后且不更新 last_status（下一轮待 pending 清理后补写）
     - 幂等：重复运行同状态 → 不重复写事件
  6. 测试数据隔离（rating.test=true → 跳过）

运行:
  python3 test-state-change-hook.py
"""

import importlib.util
import json
import os
import subprocess
import sys
import unittest
from unittest import mock

_HERE = os.path.dirname(os.path.abspath(__file__))


def _resolve_hook(here=_HERE):
    """定位被测模块，兼容两种布局（KA-424）：

      - 仓库布局：被测模块与测试同目录      → src/state-change-hook.py
      - 生产树布局：测试在 tests/ 子目录      → agents/capability-system/state-change-hook.py

    生产树把测试放在 `agents/capability-system/tests/`（runbook §5 的复验命令路径），
    旧实现只按同目录解析 → `python3 agents/capability-system/tests/test-state-change-hook.py`
    直接 FileNotFoundError，本文件的用例在生产树**一条都跑不了**（同目录下的
    test-rating-aggregator.py 用的是 dirname(dirname(...))，故不受影响）。
    """
    same_dir = os.path.normpath(os.path.join(here, "state-change-hook.py"))
    if os.path.exists(same_dir):
        return same_dir
    return os.path.normpath(os.path.join(here, os.pardir, "state-change-hook.py"))


HOOK = _resolve_hook()

spec = importlib.util.spec_from_file_location("state_change_hook", HOOK)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def issue(**overrides):
    """构造 issue dict（测试夹具）。"""
    base = {
        "id": "i-1",
        "identifier": "KA-1",
        "status": "done",
        "due_date": None,
        "updated_at": "2026-08-16T10:00:00Z",
        "assignee_type": "agent",
        "assignee_id": "a-1",
    }
    base.update(overrides)
    return base


def meta(**overrides):
    """构造 metadata dict（测试夹具）。"""
    base = {}
    base.update(overrides)
    return base


class TestClassifyCompletion(unittest.TestCase):
    def test_no_due_date_is_on_time(self):
        self.assertEqual(mod.classify_completion(None, "2026-08-16T10:00:00Z"), "on_time")

    def test_completed_before_due_is_on_time(self):
        self.assertEqual(
            mod.classify_completion("2026-08-20", "2026-08-16T10:00:00Z"), "on_time")

    def test_completed_same_day_is_on_time(self):
        self.assertEqual(
            mod.classify_completion("2026-08-16", "2026-08-16T23:59:00Z"), "on_time")

    def test_completed_after_due_is_overdue(self):
        self.assertEqual(
            mod.classify_completion("2026-08-16", "2026-08-17T00:01:00Z"), "overdue")

    def test_missing_completed_at_is_on_time(self):
        self.assertEqual(mod.classify_completion("2026-08-16", None), "on_time")


class TestMapTransition(unittest.TestCase):
    def test_to_done_no_due_is_r01(self):
        ev = mod.map_transition("in_review", "done", due_date=None, completed_at="2026-08-16T10:00:00Z")
        self.assertEqual(ev["event"], "R-01:任务按时完成")
        self.assertEqual(ev["points"], 20)
        self.assertEqual(ev["trigger"], "reviewer")

    def test_to_done_on_time_is_r01(self):
        ev = mod.map_transition("in_progress", "done", due_date="2026-08-20",
                                completed_at="2026-08-16T10:00:00Z")
        self.assertEqual(ev["event"], "R-01:任务按时完成")
        self.assertEqual(ev["points"], 20)

    def test_to_done_overdue_is_r02(self):
        ev = mod.map_transition("in_progress", "done", due_date="2026-08-15",
                                completed_at="2026-08-16T10:00:00Z")
        self.assertEqual(ev["event"], "R-02:任务超时完成")
        self.assertEqual(ev["points"], 10)

    def test_to_cancelled_is_r03(self):
        ev = mod.map_transition("in_progress", "cancelled")
        self.assertEqual(ev["event"], "R-03:任务未完成/失败")
        self.assertEqual(ev["points"], -15)

    def test_cancelled_after_done_is_not_scored(self):
        # 已完成任务再取消，不重复记失败（防双计）
        self.assertIsNone(mod.map_transition("done", "cancelled"))

    def test_done_to_in_progress_is_r04(self):
        ev = mod.map_transition("done", "in_progress")
        self.assertEqual(ev["event"], "R-04:任务被退回返工")
        self.assertEqual(ev["points"], -10)

    def test_in_review_to_todo_is_r04(self):
        ev = mod.map_transition("in_review", "todo")
        self.assertEqual(ev["event"], "R-04:任务被退回返工")
        self.assertEqual(ev["points"], -10)

    def test_in_review_to_done_is_r01(self):
        ev = mod.map_transition("in_review", "done", due_date=None)
        self.assertEqual(ev["event"], "R-01:任务按时完成")

    def test_in_progress_to_in_review_is_not_scored(self):
        self.assertIsNone(mod.map_transition("in_progress", "in_review"))

    def test_to_blocked_is_not_scored(self):
        self.assertIsNone(mod.map_transition("in_progress", "blocked"))

    def test_backlog_to_todo_is_not_scored(self):
        self.assertIsNone(mod.map_transition("backlog", "todo"))

    def test_cancelled_then_done_is_r01(self):
        # 已取消任务恢复并完成 → 正常记完成事件
        ev = mod.map_transition("cancelled", "done", due_date="2026-08-20",
                                completed_at="2026-08-16T10:00:00Z")
        self.assertEqual(ev["event"], "R-01:任务按时完成")


class TestEventId(unittest.TestCase):
    def test_extract_rxx_prefix(self):
        self.assertEqual(mod.event_id("R-04:任务被退回返工"), "R-04")

    def test_unknown_desc_returns_whole(self):
        self.assertEqual(mod.event_id("some-note"), "some-note")

    def test_empty_returns_empty(self):
        self.assertEqual(mod.event_id(""), "")


class TestSkipReason(unittest.TestCase):
    def test_pending_defers(self):
        m = meta(**{"rating.last_status": "in_review", "rating.status": "pending"})
        self.assertEqual(mod.skip_reason(m, {"event": "R-01:任务按时完成"}), "event-pending")

    def test_escalated_blocks(self):
        m = meta(**{"rating.last_status": "in_review", "rating.status": "escalated"})
        self.assertEqual(mod.skip_reason(m, {"event": "R-01:任务按时完成"}), "escalated")

    def test_credited_same_event_skips(self):
        m = meta(**{
            "rating.last_status": "in_review",
            "rating.status": "credited",
            "rating.event": "R-01:任务按时完成",
        })
        self.assertEqual(mod.skip_reason(m, {"event": "R-01:任务按时完成"}), "credited-same-event")

    def test_credited_different_event_allows(self):
        m = meta(**{
            "rating.last_status": "done",
            "rating.status": "credited",
            "rating.event": "R-01:任务按时完成",
        })
        self.assertIsNone(mod.skip_reason(m, {"event": "R-04:任务被退回返工"}))

    def test_no_rating_status_allows(self):
        m = meta(**{"rating.last_status": "in_review"})
        self.assertIsNone(mod.skip_reason(m, {"event": "R-01:任务按时完成"}))


class TestBuildEventMetadata(unittest.TestCase):
    def test_five_keys_and_values(self):
        ev = {"event": "R-03:任务未完成/失败", "points": -15, "trigger": "reviewer"}
        rows = mod.build_event_metadata(ev, "2026-08-16T10:00:00Z")
        d = dict((k, v) for k, v, _ in rows)
        self.assertEqual(d["rating.trigger"], "reviewer")
        self.assertEqual(d["rating.event"], "R-03:任务未完成/失败")
        self.assertEqual(d["rating.points"], "-15")
        self.assertEqual(d["rating.status"], "pending")
        self.assertEqual(d["rating.occurred_at"], "2026-08-16T10:00:00Z")

    def test_points_type_is_number(self):
        ev = {"event": "R-01:任务按时完成", "points": 20, "trigger": "reviewer"}
        rows = mod.build_event_metadata(ev, "2026-08-16T10:00:00Z")
        t = dict((k, t) for k, _, t in rows)
        self.assertEqual(t["rating.points"], "number")
        self.assertEqual(t["rating.trigger"], "string")
        self.assertEqual(t["rating.status"], "string")


class TestDecide(unittest.TestCase):
    def test_baseline_recorded_no_event(self):
        it = issue(status="done")
        plan = mod.decide(it, meta())
        self.assertEqual(plan["action"], "baseline")
        self.assertEqual(plan["updates"], [("rating.last_status", "done", "string")])

    def test_no_auto_baseline_strict(self):
        it = issue(status="done")
        plan = mod.decide(it, meta(), no_auto_baseline=True)
        self.assertEqual(plan["action"], "needs-baseline")
        self.assertEqual(plan["updates"], [])

    def test_no_transition_noop(self):
        it = issue(status="done")
        plan = mod.decide(it, meta(**{"rating.last_status": "done"}))
        self.assertEqual(plan["action"], "no-transition")
        self.assertEqual(plan["updates"], [])

    def test_test_data_skipped(self):
        it = issue(status="done")
        plan = mod.decide(it, meta(**{"rating.test": True}))
        self.assertEqual(plan["action"], "test-skip")
        self.assertEqual(plan["updates"], [])

    def test_non_scoring_transition_updates_last_status(self):
        it = issue(status="in_review")
        plan = mod.decide(it, meta(**{"rating.last_status": "in_progress"}))
        self.assertEqual(plan["action"], "non-scoring")
        self.assertEqual(plan["updates"], [("rating.last_status", "in_review", "string")])

    def test_event_written_includes_metadata_and_last_status(self):
        it = issue(status="done", due_date="2026-08-20", updated_at="2026-08-16T10:00:00Z")
        plan = mod.decide(it, meta(**{"rating.last_status": "in_review"}))
        self.assertEqual(plan["action"], "event-written")
        self.assertEqual(plan["event"]["event"], "R-01:任务按时完成")
        updates = dict((k, v) for k, v, _ in plan["updates"])
        self.assertEqual(updates["rating.status"], "pending")
        self.assertEqual(updates["rating.event"], "R-01:任务按时完成")
        self.assertEqual(updates["rating.last_status"], "done")
        self.assertEqual(updates["rating.occurred_at"], "2026-08-16T10:00:00Z")

    def test_overdue_event_written_is_r02(self):
        it = issue(status="done", due_date="2026-08-15", updated_at="2026-08-16T10:00:00Z")
        plan = mod.decide(it, meta(**{"rating.last_status": "in_progress"}))
        self.assertEqual(plan["action"], "event-written")
        self.assertEqual(plan["event"]["event"], "R-02:任务超时完成")
        self.assertEqual(plan["event"]["points"], 10)

    def test_return_event_written_is_r04(self):
        it = issue(status="in_progress")
        plan = mod.decide(it, meta(**{"rating.last_status": "done"}))
        self.assertEqual(plan["action"], "event-written")
        self.assertEqual(plan["event"]["event"], "R-04:任务被退回返工")
        self.assertEqual(plan["event"]["points"], -10)

    def test_pending_defers_and_keeps_last_status(self):
        it = issue(status="done")
        plan = mod.decide(it, meta(**{"rating.last_status": "in_review", "rating.status": "pending"}))
        self.assertEqual(plan["action"], "deferred")
        # 不更新 last_status（延后），仅记录 transitioned_at
        keys = [k for k, _, _ in plan["updates"]]
        self.assertNotIn("rating.last_status", keys)
        self.assertIn("rating.transitioned_at", keys)

    def test_pending_defer_preserves_existing_transitioned_at(self):
        it = issue(status="done", updated_at="2026-08-16T10:00:00Z")
        plan = mod.decide(it, meta(**{
            "rating.last_status": "in_review",
            "rating.status": "pending",
            "rating.transitioned_at": "2026-08-15T09:00:00Z",
        }))
        self.assertEqual(plan["action"], "deferred")
        self.assertEqual(plan["updates"], [])  # transitioned_at 已存在 → 无写入

    def test_escalated_blocks_and_touches_nothing(self):
        it = issue(status="done")
        plan = mod.decide(it, meta(**{"rating.last_status": "in_review", "rating.status": "escalated"}))
        self.assertEqual(plan["action"], "escalated-blocked")
        self.assertEqual(plan["updates"], [])

    def test_credited_same_event_updates_last_status_only(self):
        it = issue(status="done")
        plan = mod.decide(it, meta(**{
            "rating.last_status": "in_review",
            "rating.status": "credited",
            "rating.event": "R-01:任务按时完成",
        }))
        self.assertEqual(plan["action"], "credited-same-event")
        self.assertEqual(plan["updates"], [("rating.last_status", "done", "string")])


class TestBaselinePlan(unittest.TestCase):
    """_baseline_plan 纯函数：--baseline 模式决策与 decide() 口径对齐（KA-101）。

    过滤顺序与 decide() 一致：未知/空 status → 测试数据 → 已有 baseline → 缺 baseline 写。
    """

    def test_valid_missing_writes_baseline(self):
        plan = mod._baseline_plan(issue(status="in_progress"), meta())
        self.assertEqual(plan["action"], "baseline")
        self.assertEqual(plan["updates"],
                         [("rating.last_status", "in_progress", "string")])

    def test_invalid_status_skipped(self):
        plan = mod._baseline_plan(issue(status="archived"), meta())
        self.assertEqual(plan["action"], "invalid-status")
        self.assertEqual(plan["updates"], [])
        self.assertIsNone(plan["event"])

    def test_empty_status_skipped(self):
        plan = mod._baseline_plan(issue(status=""), meta())
        self.assertEqual(plan["action"], "invalid-status")
        self.assertEqual(plan["updates"], [])

    def test_test_data_skipped(self):
        plan = mod._baseline_plan(issue(status="done"),
                                  meta(**{"rating.test": True}))
        self.assertEqual(plan["action"], "test-skip")
        self.assertEqual(plan["updates"], [])

    def test_existing_baseline_not_overwritten(self):
        plan = mod._baseline_plan(issue(status="done"),
                                  meta(**{"rating.last_status": "in_review"}))
        self.assertEqual(plan["action"], "already-baselined")
        self.assertEqual(plan["updates"], [])

    def test_test_data_beats_existing_baseline(self):
        # 过滤顺序：测试数据在已有 baseline 之前 → 报告 test-skip，不写不重写
        plan = mod._baseline_plan(issue(status="done"),
                                  meta(**{"rating.last_status": "done",
                                          "rating.test": True}))
        self.assertEqual(plan["action"], "test-skip")


class TestProcessIssue(unittest.TestCase):
    """process_issue 集成：注入 fake write，验证写入与幂等。"""

    def setUp(self):
        self.writes = []

    def fake_write(self, key, value, vtype):
        self.writes.append((key, value, vtype))
        return True, None

    def test_event_written_via_write_callback(self):
        it = issue(status="done", due_date="2026-08-20", updated_at="2026-08-16T10:00:00Z")
        plan = mod.process_issue(
            it, meta(**{"rating.last_status": "in_review"}),
            dry_run=False, write=self.fake_write)
        self.assertEqual(plan["action"], "event-written")
        keys = [k for k, _, _ in self.writes]
        self.assertIn("rating.event", keys)
        self.assertIn("rating.last_status", keys)
        self.assertEqual(len(self.writes), 6)  # 5 键事件 + last_status

    def test_dry_run_writes_nothing(self):
        it = issue(status="done")
        plan = mod.process_issue(
            it, meta(**{"rating.last_status": "in_review"}),
            dry_run=True, write=self.fake_write)
        self.assertEqual(plan["action"], "event-written")
        self.assertEqual(self.writes, [])

    def test_no_transition_writes_nothing(self):
        it = issue(status="done")
        plan = mod.process_issue(
            it, meta(**{"rating.last_status": "done"}),
            dry_run=False, write=self.fake_write)
        self.assertEqual(plan["action"], "no-transition")
        self.assertEqual(self.writes, [])

    def test_write_error_sets_action(self):
        it = issue(status="done")
        def failing_write(k, v, t):
            return False, "boom"
        plan = mod.process_issue(
            it, meta(**{"rating.last_status": "in_review"}),
            dry_run=False, write=failing_write)
        self.assertEqual(plan["action"], "write-error")

    def test_baseline_writes_last_status_only(self):
        it = issue(status="done")
        plan = mod.process_issue(it, meta(), dry_run=False, write=self.fake_write)
        self.assertEqual(plan["action"], "baseline")
        self.assertEqual(self.writes, [("rating.last_status", "done", "string")])


class _HookMainFixture(unittest.TestCase):
    """main() 集成测试夹具：patch run_cli / set_metadata / load_agents / get_issue_metadata。

    只提供夹具，不含用例 —— 供 TestMainFlow（编排/幂等）与 TestExitCodeSplit
    （KA-424 退出码分轨）共用，避免两份 fake 漂移。
    """

    def setUp(self):
        self.store = {}          # issue_id -> metadata dict（共享 fake）
        self.issues = []         # issue 列表
        self.writes = []         # (issue_id, key, value, vtype)
        self._orig_run_cli = mod.run_cli
        self._orig_set_metadata = mod.set_metadata
        self._orig_load_agents = mod.load_agents
        self._orig_get_issue_metadata = mod.get_issue_metadata
        self._orig_argv = sys.argv
        mod.run_cli = self._fake_run_cli
        mod.set_metadata = self._fake_set_metadata
        mod.load_agents = lambda: {"a-1": "测试智能体"}
        mod.get_issue_metadata = self._fake_get_issue_metadata

    def tearDown(self):
        mod.run_cli = self._orig_run_cli
        mod.set_metadata = self._orig_set_metadata
        mod.load_agents = self._orig_load_agents
        mod.get_issue_metadata = self._orig_get_issue_metadata
        sys.argv = self._orig_argv

    def _fake_get_issue_metadata(self, issue_id):
        return self.store.get(issue_id, {}), None

    def _fake_set_metadata(self, issue_id, key, value, vtype="string"):
        self.store.setdefault(issue_id, {})[key] = value
        self.writes.append((issue_id, key, value, vtype))
        return True, None

    def _fake_run_cli(self, args):
        if args[0] == "issue" and args[1] == "list":
            payload = {"issues": [i for i in self.issues
                                  if i.get("assignee_type") == "agent"],
                       "has_more": False}
            return True, json.dumps(payload, ensure_ascii=False)
        if args[0] == "issue" and args[1] == "get":
            iid = args[2]
            for i in self.issues:
                if i["id"] == iid:
                    return True, json.dumps(i, ensure_ascii=False)
            return False, "not found"
        if args[0] == "issue" and args[1] == "metadata" and args[2] == "list":
            iid = args[3]
            return True, json.dumps(self.store.get(iid, {}), ensure_ascii=False)
        return False, f"unexpected cli: {args}"


class TestMainFlow(_HookMainFixture):
    """main() 集成：patch run_cli/set_metadata，验证完整编排
    （baseline → transition → event-written → 幂等）。"""

    def test_full_lifecycle_baseline_then_event_then_idempotent(self):
        it = issue(id="i-1", identifier="KA-1", status="in_progress",
                   assignee_id="a-1")
        self.issues = [it]
        # 第一轮：建 baseline，不写事件
        sys.argv = ["state-change-hook.py", "--issue", "i-1"]
        mod.main()
        self.assertEqual(self.store["i-1"]["rating.last_status"], "in_progress")
        self.assertNotIn("rating.event", self.store["i-1"])

        # 第二轮：状态 → done，写 R-01 事件（pending），更新 last_status
        it["status"] = "done"
        it["due_date"] = "2026-08-20"
        it["updated_at"] = "2026-08-16T10:00:00Z"
        mod.main()
        self.assertEqual(self.store["i-1"]["rating.event"], "R-01:任务按时完成")
        self.assertEqual(self.store["i-1"]["rating.points"], "20")
        self.assertEqual(self.store["i-1"]["rating.status"], "pending")
        self.assertEqual(self.store["i-1"]["rating.trigger"], "reviewer")
        self.assertEqual(self.store["i-1"]["rating.last_status"], "done")

        # 第三轮：幂等 —— 状态无变更，不再写事件
        n_before = len(self.writes)
        mod.main()
        self.assertEqual(len(self.writes), n_before)

    def test_main_scan_detects_return_to_rework(self):
        it = issue(id="i-1", identifier="KA-1", status="in_progress",
                   assignee_id="a-1")
        self.issues = [it]
        self.store["i-1"] = {"rating.last_status": "done"}
        # 无 --issue：走列表扫描
        sys.argv = ["state-change-hook.py"]
        mod.main()
        self.assertEqual(self.store["i-1"]["rating.event"], "R-04:任务被退回返工")
        self.assertEqual(self.store["i-1"]["rating.points"], "-10")

    def test_main_baseline_flag_only_records_missing(self):
        it = issue(id="i-1", identifier="KA-1", status="done", assignee_id="a-1")
        self.issues = [it]
        self.store["i-1"] = {"rating.last_status": "done"}
        sys.argv = ["state-change-hook.py", "--baseline"]
        mod.main()
        # baseline 已存在 → 不重复写，也不写事件
        self.assertNotIn("rating.event", self.store["i-1"])
        event_writes = [w for w in self.writes if w[1] == "rating.event"]
        self.assertEqual(event_writes, [])

    def test_main_baseline_flag_writes_missing_baseline(self):
        # 缺陷回归（KA-100 修复 1）：缺 baseline 的 issue 必须真实写入 rating.last_status
        it = issue(id="i-1", identifier="KA-1", status="in_progress", assignee_id="a-1")
        self.issues = [it]
        self.store["i-1"] = {}
        sys.argv = ["state-change-hook.py", "--baseline"]
        mod.main()
        self.assertEqual(self.store["i-1"].get("rating.last_status"), "in_progress")
        # baseline 模式不写事件
        self.assertNotIn("rating.event", self.store["i-1"])
        event_writes = [w for w in self.writes if w[1] == "rating.event"]
        self.assertEqual(event_writes, [])

    def test_main_baseline_flag_dry_run_writes_nothing(self):
        # --baseline --dry-run：只读预演，缺 baseline 也不产生写入
        it = issue(id="i-1", identifier="KA-1", status="done", assignee_id="a-1")
        self.issues = [it]
        self.store["i-1"] = {}
        sys.argv = ["state-change-hook.py", "--baseline", "--dry-run"]
        mod.main()
        self.assertNotIn("rating.last_status", self.store["i-1"])
        self.assertEqual(self.writes, [])

    def test_main_baseline_flag_skips_invalid_status(self):
        # KA-101 非阻塞项 1：未知/空 status 的 issue 不写 baseline（与 decide() 对齐）
        it = issue(id="i-1", identifier="KA-1", status="archived", assignee_id="a-1")
        self.issues = [it]
        self.store["i-1"] = {}
        sys.argv = ["state-change-hook.py", "--baseline"]
        mod.main()
        self.assertNotIn("rating.last_status", self.store["i-1"])
        self.assertEqual(self.writes, [])

    def test_main_baseline_flag_skips_test_data(self):
        # KA-101 非阻塞项 2：rating.test=true 测试数据不写 baseline（测试数据隔离）
        it = issue(id="i-1", identifier="KA-1", status="done", assignee_id="a-1")
        self.issues = [it]
        self.store["i-1"] = {"rating.test": True}
        sys.argv = ["state-change-hook.py", "--baseline"]
        mod.main()
        self.assertNotIn("rating.last_status", self.store["i-1"])
        self.assertEqual(self.writes, [])

    def test_main_baseline_flag_mixed_stats(self):
        # 混合场景：有效缺 baseline 写、invalid-status/test-skip 跳过且计入 stats
        from contextlib import redirect_stdout
        import io
        self.issues = [
            issue(id="i-1", identifier="KA-1", status="in_progress", assignee_id="a-1"),
            issue(id="i-2", identifier="KA-2", status="archived", assignee_id="a-1"),
            issue(id="i-3", identifier="KA-3", status="done", assignee_id="a-1"),
        ]
        self.store["i-1"] = {}
        self.store["i-2"] = {}
        self.store["i-3"] = {"rating.test": True}
        buf = io.StringIO()
        sys.argv = ["state-change-hook.py", "--baseline", "--json"]
        with redirect_stdout(buf):
            mod.main()
        data = json.loads(buf.getvalue())
        self.assertEqual(data["stats"].get("baseline"), 1)
        self.assertEqual(data["stats"].get("invalid-status"), 1)
        self.assertEqual(data["stats"].get("test-skip"), 1)
        self.assertEqual(self.store["i-1"].get("rating.last_status"), "in_progress")
        self.assertNotIn("rating.last_status", self.store["i-2"])
        self.assertNotIn("rating.last_status", self.store["i-3"])

    def test_main_exits_1_on_write_error(self):
        # 缺陷回归（KA-100 修复 2）：写失败 → 进程退出码=1（cron 告警契约）
        it = issue(id="i-1", identifier="KA-1", status="done", assignee_id="a-1")
        self.issues = [it]
        self.store["i-1"] = {"rating.last_status": "in_review"}
        def failing_set(issue_id, key, value, vtype="string"):
            return False, "simulated write failure"
        mod.set_metadata = failing_set
        sys.argv = ["state-change-hook.py", "--issue", "i-1"]
        with self.assertRaises(SystemExit) as cm:
            mod.main()
        self.assertEqual(cm.exception.code, 1)

    def test_main_json_exits_1_on_write_error(self):
        # --json 输出同样遵守退出码契约
        it = issue(id="i-1", identifier="KA-1", status="done", assignee_id="a-1")
        self.issues = [it]
        self.store["i-1"] = {"rating.last_status": "in_review"}
        def failing_set(issue_id, key, value, vtype="string"):
            return False, "simulated write failure"
        mod.set_metadata = failing_set
        sys.argv = ["state-change-hook.py", "--json", "--issue", "i-1"]
        with self.assertRaises(SystemExit) as cm:
            mod.main()
        self.assertEqual(cm.exception.code, 1)

    def test_main_exits_3_on_read_error(self):
        # KA-424 分轨：读 metadata 失败（只读重试耗尽）→ 输入不可用 → 退出码 **3**，
        # 不占 P1 通道。分轨前此处断言 1（read-error 与 write-error 同档）。
        it = issue(id="i-1", identifier="KA-1", status="done", assignee_id="a-1")
        self.issues = [it]
        mod.get_issue_metadata = lambda iid: (None, "simulated read failure")
        sys.argv = ["state-change-hook.py", "--issue", "i-1"]
        with self.assertRaises(SystemExit) as cm:
            mod.main()
        self.assertEqual(cm.exception.code, 3)

    def test_main_no_error_exits_zero(self):
        # 无错误：不抛 SystemExit（退出码=0 契约）
        it = issue(id="i-1", identifier="KA-1", status="done", assignee_id="a-1")
        self.issues = [it]
        self.store["i-1"] = {"rating.last_status": "done"}
        sys.argv = ["state-change-hook.py", "--issue", "i-1"]
        mod.main()  # 不应抛 SystemExit
        self.assertEqual(self.store["i-1"].get("rating.last_status"), "done")

    def test_main_dry_run_writes_nothing(self):
        it = issue(id="i-1", identifier="KA-1", status="done", assignee_id="a-1",
                   due_date="2026-08-20", updated_at="2026-08-16T10:00:00Z")
        self.issues = [it]
        self.store["i-1"] = {"rating.last_status": "in_review"}
        sys.argv = ["state-change-hook.py", "--dry-run"]
        mod.main()
        self.assertEqual(self.writes, [])

    def test_main_ignores_non_agent_issues(self):
        it = issue(id="i-1", identifier="KA-1", status="done",
                   assignee_type="member", assignee_id=None)
        self.issues = [it]
        sys.argv = ["state-change-hook.py", "--baseline"]
        mod.main()
        self.assertEqual(self.store, {})  # 非 agent 分配 issue 不处理

    def test_main_json_output_is_pure_json(self):
        from contextlib import redirect_stdout
        import io
        it = issue(id="i-1", identifier="KA-1", status="done", assignee_id="a-1")
        self.issues = [it]
        self.store["i-1"] = {"rating.last_status": "done"}
        buf = io.StringIO()
        sys.argv = ["state-change-hook.py", "--json"]
        with redirect_stdout(buf):
            mod.main()
        # --json 输出必须为可解析的纯 JSON（无 human 文本混入）
        data = json.loads(buf.getvalue())
        self.assertEqual(data["scanned"], 1)
        self.assertEqual(data["stats"].get("no-transition"), 1)
        self.assertEqual(data["events_written"], [])


class TestExitCodeFor(unittest.TestCase):
    """KA-424：退出码分轨的纯函数口径（read-error→3 / write-error→1）。

    分轨前 `_exit_on_error()` 对 read-error 与 write-error 一视同仁 exit 1，
    后果是 0.5% 的瞬时读抖动直接进 P1 通道（KA-415 / KA-416 / KA-422 连开三单），
    而真正的写入故障被同一档掩盖。
    """

    def test_clean_stats_is_zero(self):
        for stats in ({}, {"no-transition": 399}, {"event-written": 2, "baseline": 1}):
            self.assertEqual(mod.exit_code_for(stats), mod.EXIT_OK)
            self.assertEqual(mod.exit_code_for(stats), 0)

    def test_write_error_is_one(self):
        self.assertEqual(mod.exit_code_for({"write-error": 1}), 1)

    def test_read_error_is_three(self):
        self.assertEqual(mod.exit_code_for({"read-error": 1}), 3)
        self.assertEqual(mod.exit_code_for({"read-error": 3, "no-transition": 396}), 3)

    def test_write_error_wins_over_read_error(self):
        # 混轮：真·写入故障不得被 read-error 降级掩盖（否则就是换个档位重演旧缺陷）
        self.assertEqual(mod.exit_code_for({"read-error": 2, "write-error": 1}), 1)

    def test_exit_code_constants_match_runbook_contract(self):
        # 与 runbook §3「告警分轨」/ sync-agents-to-rating.sh 既有口径一致
        self.assertEqual(mod.EXIT_OK, 0)
        self.assertEqual(mod.EXIT_SCRIPT_ERROR, 1)
        self.assertEqual(mod.EXIT_INPUT_UNAVAILABLE, 3)

    def test_exit_reason_labels(self):
        self.assertEqual(mod.exit_reason_for(0), "ok")
        self.assertEqual(mod.exit_reason_for(1), "script-error")
        self.assertEqual(mod.exit_reason_for(3), "input-unavailable")

    def test_summary_line_distinguishes_branches(self):
        # runbook §3：退出码 3 的动作含「记日志 + 摘要行」——摘要行必须能区分三档
        self.assertIn("退出码 0", mod._exit_summary_line({}))
        self.assertIn("退出码 1", mod._exit_summary_line({"write-error": 1}))
        line = mod._exit_summary_line({"read-error": 2})
        self.assertIn("退出码 3", line)
        self.assertIn("不占 P1", line)


class TestExitCodeSplit(_HookMainFixture):
    """KA-424 验收：main() 层面的退出码分轨 + read-error 不变量。

    验收 (b) 的 main 层版本在此；(a) 与 (b) 的端到端（真·重试循环）版本见
    TestReadRetryComposition。
    """

    def test_read_error_exits_three(self):
        # 验收 (b)：读失败（只读重试耗尽）→ exit 3
        it = issue(id="i-1", identifier="KA-1", status="done", assignee_id="a-1")
        self.issues = [it]
        mod.get_issue_metadata = lambda iid: (None, "simulated read failure")
        sys.argv = ["state-change-hook.py", "--issue", "i-1"]
        with self.assertRaises(SystemExit) as cm:
            mod.main()
        self.assertEqual(cm.exception.code, mod.EXIT_INPUT_UNAVAILABLE)

    def test_read_error_does_not_advance_last_status(self):
        """不变量（退出码 3 的全部依据）：read-error 分支不得推进 rating.last_status。

        读失败必须发生在任何写入路径之前 —— 最坏只晚一个周期（次日窗口重读同一状态
        并补写事件），不产生永久遗漏。若此断言失败，read-error 已退化为静默数据丢失，
        必须把退出码立刻改回 1。
        """
        it = issue(id="i-1", identifier="KA-1", status="done", assignee_id="a-1")
        self.issues = [it]
        self.store["i-1"] = {"rating.last_status": "in_review"}
        mod.get_issue_metadata = lambda iid: (None, "simulated read failure")
        sys.argv = ["state-change-hook.py", "--issue", "i-1"]
        with self.assertRaises(SystemExit) as cm:
            mod.main()
        self.assertEqual(cm.exception.code, 3)
        self.assertEqual(self.writes, [])                                   # 零写入
        self.assertEqual(self.store["i-1"], {"rating.last_status": "in_review"})

    def test_read_error_does_not_advance_last_status_in_baseline_mode(self):
        # --baseline 模式同样适用：读失败不建 baseline（不写 rating.last_status）
        it = issue(id="i-1", identifier="KA-1", status="in_progress", assignee_id="a-1")
        self.issues = [it]
        mod.get_issue_metadata = lambda iid: (None, "simulated read failure")
        sys.argv = ["state-change-hook.py", "--baseline"]
        with self.assertRaises(SystemExit) as cm:
            mod.main()
        self.assertEqual(cm.exception.code, 3)
        self.assertEqual(self.writes, [])
        self.assertEqual(self.store, {})

    def test_read_error_is_isolated_to_the_failing_issue(self):
        # 单条读失败不阻断整轮：坏条计入 read-error，好条照常处理
        good = issue(id="i-1", identifier="KA-1", status="in_progress", assignee_id="a-1")
        bad = issue(id="i-2", identifier="KA-2", status="done", assignee_id="a-1")
        self.issues = [good, bad]
        self.store["i-1"] = {}

        def flaky(iid):
            if iid == "i-2":
                return None, "simulated read failure"
            return self.store.get(iid, {}), None

        mod.get_issue_metadata = flaky
        sys.argv = ["state-change-hook.py", "--json"]
        with self.assertRaises(SystemExit) as cm:
            mod.main()
        self.assertEqual(cm.exception.code, 3)
        self.assertEqual(self.store["i-1"].get("rating.last_status"), "in_progress")
        self.assertNotIn("i-2", self.store)          # 坏条零写入

    def test_json_report_carries_exit_code_and_reason(self):
        # --json 消费方无需自己重算退出码口径
        it = issue(id="i-1", identifier="KA-1", status="done", assignee_id="a-1")
        self.issues = [it]
        mod.get_issue_metadata = lambda iid: (None, "simulated read failure")
        from contextlib import redirect_stdout
        import io
        buf = io.StringIO()
        sys.argv = ["state-change-hook.py", "--json"]
        with redirect_stdout(buf), self.assertRaises(SystemExit) as cm:
            mod.main()
        data = json.loads(buf.getvalue())
        self.assertEqual(data["stats"]["read-error"], 1)
        self.assertEqual(data["exit_code"], 3)
        self.assertEqual(data["exit_reason"], "input-unavailable")
        self.assertEqual(cm.exception.code, 3)

    def test_json_exits_three_on_read_error(self):
        it = issue(id="i-1", identifier="KA-1", status="done", assignee_id="a-1")
        self.issues = [it]
        mod.get_issue_metadata = lambda iid: (None, "simulated read failure")
        sys.argv = ["state-change-hook.py", "--json", "--issue", "i-1"]
        with self.assertRaises(SystemExit) as cm:
            mod.main()
        self.assertEqual(cm.exception.code, 3)

    def test_write_error_still_exits_one(self):
        # 写失败语义不变：仍是 L1/P1
        it = issue(id="i-1", identifier="KA-1", status="done", assignee_id="a-1")
        self.issues = [it]
        self.store["i-1"] = {"rating.last_status": "in_review"}
        mod.set_metadata = lambda *a, **k: (False, "simulated write failure")
        sys.argv = ["state-change-hook.py", "--issue", "i-1"]
        with self.assertRaises(SystemExit) as cm:
            mod.main()
        self.assertEqual(cm.exception.code, 1)

    def test_mixed_write_and_read_error_exits_one(self):
        # 同轮既有 write-error 又有 read-error → 按更严重档 1 报
        writing = issue(id="i-1", identifier="KA-1", status="done", assignee_id="a-1")
        unreadable = issue(id="i-2", identifier="KA-2", status="done", assignee_id="a-1")
        self.issues = [writing, unreadable]
        self.store["i-1"] = {"rating.last_status": "in_review"}
        mod.set_metadata = lambda *a, **k: (False, "simulated write failure")

        def flaky(iid):
            if iid == "i-2":
                return None, "simulated read failure"
            return self.store.get(iid, {}), None

        mod.get_issue_metadata = flaky
        sys.argv = ["state-change-hook.py", "--json"]
        with self.assertRaises(SystemExit) as cm:
            mod.main()
        self.assertEqual(cm.exception.code, 1)

    def test_entry_gate_failure_stays_one(self):
        """入口闸门（issue list / issue get）失败仍按 1 报，**不得**降级为 3。

        闸门失败 = 整轮没跑；本 job 每日只跑一次，若按「不占 P1、等次日自愈」处理，
        就永远凑不满「同日连续 ≥3 次」的升级条件 → 退化为静默失火。
        """
        it = issue(id="i-1", identifier="KA-1", status="done", assignee_id="a-1")
        self.issues = [it]
        mod.run_cli = lambda args: (False, "simulated list failure")
        sys.argv = ["state-change-hook.py"]
        with self.assertRaises(SystemExit) as cm:
            mod.main()
        self.assertEqual(cm.exception.code, 1)

        mod.run_cli = self._fake_run_cli
        mod.get_issue_metadata = lambda iid: (None, "irrelevant")
        sys.argv = ["state-change-hook.py", "--issue", "missing"]
        with self.assertRaises(SystemExit) as cm:
            mod.main()
        self.assertEqual(cm.exception.code, 1)

    def test_no_error_exits_zero(self):
        # 无错误不抛 SystemExit（契约 exit 0）
        it = issue(id="i-1", identifier="KA-1", status="done", assignee_id="a-1")
        self.issues = [it]
        self.store["i-1"] = {"rating.last_status": "done"}
        sys.argv = ["state-change-hook.py", "--issue", "i-1"]
        mod.main()
        self.assertEqual(self.writes, [])


class TestReadRetryComposition(unittest.TestCase):
    """验收 (a) 端到端：读抖动被 KA-416 的只读重试吸收 → exit 0 且 read-error=0。

    这里**不替换 `run_cli`**，而是替换更底层的 `subprocess.run`，走真实的重试循环 ——
    「重试 + 分轨」只有组合起来才成立的口径，必须由组合测试锁定：只有重试没有分轨，
    抖动仍会推进 exit 码；只有分轨没有重试，抖动会被计成 read-error → exit 3。
    """

    TIMEOUT_ERR = ("Request timed out: the server did not respond in time. "
                   "Check your network connection or try again later.")
    ISSUE = {"id": "i-1", "identifier": "KA-1", "status": "done",
             "assignee_type": "agent", "assignee_id": "a-1", "due_date": None,
             "updated_at": "2026-08-16T10:00:00Z"}

    def setUp(self):
        self._orig_argv = sys.argv
        self._store = {"rating.last_status": "done"}   # 无 transition → 本轮无需写入
        self._meta_calls = 0
        self._sleeps = []
        self._metadata_always_fails = False

    def tearDown(self):
        sys.argv = self._orig_argv

    @staticmethod
    def _completed(rc=0, stdout="", stderr=""):
        return subprocess.CompletedProcess(
            args=["multica"], returncode=rc, stdout=stdout, stderr=stderr)

    def _fake_run(self, cmd, **kwargs):
        argv = list(cmd[1:])
        if argv[:2] == ["agent", "list"]:
            return self._completed(0, "[]")
        if argv[:2] == ["issue", "get"]:
            return self._completed(0, json.dumps(self.ISSUE, ensure_ascii=False))
        if argv[:3] == ["issue", "metadata", "list"]:
            self._meta_calls += 1
            if self._metadata_always_fails or self._meta_calls == 1:
                return self._completed(2, "", self.TIMEOUT_ERR)
            return self._completed(0, json.dumps(self._store, ensure_ascii=False))
        if argv[:3] == ["issue", "metadata", "set"]:
            raise AssertionError("本轮不应发生任何写入")
        raise AssertionError(f"unexpected cli call: {argv}")

    def _run_main(self, argv):
        from contextlib import redirect_stdout, redirect_stderr
        import io
        out, err = io.StringIO(), io.StringIO()
        sys.argv = ["state-change-hook.py"] + argv
        with mock.patch.object(mod.subprocess, "run", self._fake_run), \
                mock.patch.object(mod.time, "sleep", self._sleeps.append), \
                redirect_stdout(out), redirect_stderr(err):
            try:
                mod.main()
                code = 0
            except SystemExit as e:
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_transient_read_failure_absorbed_by_retry_exits_zero(self):
        """验收 (a)：首次读失败、重试成功 → exit 0 且 read-error=0。"""
        code, out, _ = self._run_main(["--issue", "i-1", "--json"])
        self.assertEqual(code, 0)                       # 不抛 SystemExit
        data = json.loads(out)                          # stdout 仍是纯 JSON
        self.assertEqual(data["stats"].get("read-error", 0), 0)
        self.assertNotIn("read-error", data["stats"])
        self.assertEqual(data["exit_code"], 0)
        self.assertEqual(data["stats"].get("no-transition"), 1)
        self.assertEqual(self._meta_calls, 2)           # 首次失败 + 第 2 次成功
        self.assertEqual(self._sleeps, [1])             # 一次退避

    def test_exhausted_read_retries_exit_three_without_advancing_status(self):
        """验收 (b) 端到端：3 次尝试全部耗尽 → exit 3，且该 issue 的
        rating.last_status 未被写入（不变量在真·重试路径上同样成立）。"""
        self._metadata_always_fails = True
        code, out, _ = self._run_main(["--issue", "i-1", "--json"])
        self.assertEqual(code, 3)
        data = json.loads(out)
        self.assertEqual(data["stats"]["read-error"], 1)
        self.assertEqual(data["exit_code"], 3)
        self.assertEqual(data["exit_reason"], "input-unavailable")
        self.assertEqual(self._meta_calls, mod.CLI_READ_RETRIES)   # 3 次全耗尽
        self.assertEqual(self._sleeps, [1, 3])                     # 2 次退避
        self.assertEqual(data["events_written"], [])

    def test_retry_diagnostics_go_to_stderr_not_stdout(self):
        """重试提示不得污染 `--json` 的 stdout（否则消费方解析失败）。"""
        self._metadata_always_fails = True
        _, out, err = self._run_main(["--issue", "i-1", "--json"])
        json.loads(out)                                  # stdout 必须可解析
        self.assertIn("次失败", err)
        self.assertNotIn("次失败", out)


class TestRunCliRetry(unittest.TestCase):
    """KA-416 回归：CLI 只读调用有限次重试 + 退避；写调用一律不重试。

    背景：2026-09-24 00:20 运行中 2/393 条 `issue metadata list` 瞬时超时
    （`Request timed out: the server did not respond in time`）→ 计 read-error
    → 整轮 exit 1 → L1 告警。只读调用无副作用，重试即可收敛。
    """

    def _completed(self, rc=0, stdout="{}", stderr=""):
        return subprocess.CompletedProcess(
            args=["multica"], returncode=rc, stdout=stdout, stderr=stderr)

    def _patch(self, results):
        """results: 按调用顺序返回的 CompletedProcess 或待抛出的 Exception。"""
        calls = []
        sleeps = []

        def fake_run(cmd, **kwargs):
            calls.append((list(cmd), kwargs.get("timeout")))
            r = results[len(calls) - 1]
            if isinstance(r, Exception):
                raise r
            return r

        return fake_run, calls, sleeps

    def _run(self, results, argv=None):
        fake, calls, sleeps = self._patch(results)
        with mock.patch.object(mod.subprocess, "run", fake), \
                mock.patch.object(mod.time, "sleep", sleeps.append):
            out = mod.run_cli(argv or ["issue", "list", "--limit", "100"])
        return out, calls, sleeps

    def test_first_attempt_success_does_not_retry(self):
        out, calls, sleeps = self._run([self._completed(rc=0, stdout='{"a":1}')])
        self.assertEqual(out, (True, '{"a":1}'))
        self.assertEqual(len(calls), 1)
        self.assertEqual(sleeps, [])

    def test_transient_failure_recovered_by_retry(self):
        timeout = ("Request timed out: the server did not respond in time. "
                   "Check your network connection or try again later.")
        out, calls, sleeps = self._run([
            self._completed(rc=2, stderr=timeout),
            self._completed(rc=2, stderr=timeout),
            self._completed(rc=0, stdout="[]"),
        ])
        self.assertEqual(out, (True, "[]"))
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [1, 3])   # 两次退避，最后一次失败后不再等待

    def test_exhausted_retries_report_last_error(self):
        timeout = "Request timed out: the server did not respond in time."
        out, calls, sleeps = self._run([self._completed(rc=2, stderr=timeout)] * 3)
        self.assertEqual(out, (False, timeout))
        self.assertEqual(len(calls), 3)
        self.assertEqual(sleeps, [1, 3])

    def test_exception_path_is_also_retried(self):
        exc = subprocess.TimeoutExpired(cmd=["multica"], timeout=60)
        out, calls, sleeps = self._run([exc, self._completed(rc=0, stdout="{}")])
        self.assertEqual(out, (True, "{}"))
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, [1])

    def test_per_call_timeout_is_configurable(self):
        _, calls, _ = self._run([self._completed(rc=0)], )
        self.assertEqual(calls[0][1], mod.CLI_READ_TIMEOUT)

    def test_write_path_never_retries(self):
        """写 metadata 失败 → 只调用一次（重放会把「结果未知」变成「重复写入」）。"""
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            return self._completed(rc=1, stderr="boom")

        with mock.patch.object(mod.subprocess, "run", fake_run), \
                mock.patch.object(mod.time, "sleep", lambda s: None):
            ok, err = mod.set_metadata("i-1", "rating.status", "pending")
        self.assertFalse(ok)
        self.assertEqual(err, "boom")
        self.assertEqual(len(calls), 1)

    def test_gate_issue_list_shares_read_retry_budget(self):
        """入口闸门 `issue list` 同样走只读重试（整轮中止比单条昂贵）。"""
        out, calls, _ = self._run([
            self._completed(rc=2, stderr="Could not reach the Multica server"),
            self._completed(rc=0, stdout=json.dumps([
                {"id": "i-1", "assignee_type": "agent"}] * 1)),
        ], argv=["issue", "list"])
        self.assertTrue(out[0])
        self.assertEqual(len(calls), 2)


class TestHookResolution(unittest.TestCase):
    """KA-424 顺带修正：被测模块定位必须兼容仓库布局与生产树布局。

    否则 `python3 agents/capability-system/tests/test-state-change-hook.py`
    （runbook §5 的复验路径）在本补丁新增用例之前就先 FileNotFoundError ——
    即回归在生产树里一条都跑不了，验收 2 无从核验。
    """

    def test_repo_layout_resolves_to_sibling(self):
        # 仓库布局：src/test-state-change-hook.py 与 src/state-change-hook.py 同目录
        self.assertTrue(os.path.exists(HOOK))
        self.assertEqual(os.path.basename(HOOK), "state-change-hook.py")
        self.assertEqual(_resolve_hook(_HERE), HOOK)

    def test_prod_layout_resolves_to_parent_dir(self):
        # 生产树布局：tests/ 子目录，被测模块在上一级
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            tests_dir = os.path.join(root, "tests")
            os.makedirs(tests_dir)
            target = os.path.join(root, "state-change-hook.py")
            open(target, "w", encoding="utf-8").close()
            self.assertEqual(_resolve_hook(tests_dir), target)

    def test_missing_module_still_raises_loudly(self):
        # 两种布局都找不到时不得静默兜底成错误路径 —— 交给 importlib 响亮报错
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(FileNotFoundError):
                spec = importlib.util.spec_from_file_location(
                    "nowhere", _resolve_hook(root))
                m = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(m)


if __name__ == "__main__":
    unittest.main(verbosity=2)
