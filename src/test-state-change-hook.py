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
import sys
import unittest

HOOK = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "state-change-hook.py",
))

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


class TestMainFlow(unittest.TestCase):
    """main() 集成：patch run_cli/set_metadata，验证完整编排
    （baseline → transition → event-written → 幂等）。"""

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

    def test_main_exits_1_on_read_error(self):
        # 读 metadata 失败 → 计入 read-error → 退出码=1
        it = issue(id="i-1", identifier="KA-1", status="done", assignee_id="a-1")
        self.issues = [it]
        mod.get_issue_metadata = lambda iid: (None, "simulated read failure")
        sys.argv = ["state-change-hook.py", "--issue", "i-1"]
        with self.assertRaises(SystemExit) as cm:
            mod.main()
        self.assertEqual(cm.exception.code, 1)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
