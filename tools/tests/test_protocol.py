#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""teamctl 协议层单元测试：信封校验、总线路由、handoff 环/预算、乐观锁、轨迹日志。

运行：python3.10 tools/tests/test_protocol.py
"""
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import teamctl  # noqa: E402


class TestSchema(unittest.TestCase):
    def test_envelope_ok(self):
        env = {"envelope_version": 1, "id": "x1", "ts": "2026-09-14T00:00:00+00:00",
               "sender_id": "spec", "recipient_id": "dev", "type": "task_assigned",
               "payload": {}}
        self.assertTrue(teamctl.validate_envelope(env))

    def test_envelope_missing_route(self):
        env = {"envelope_version": 1, "id": "x1", "ts": "t", "sender_id": "a",
               "type": "note", "payload": {}}
        with self.assertRaises(teamctl.SchemaError):
            teamctl.validate_envelope(env)

    def test_envelope_bad_type(self):
        env = {"envelope_version": 1, "id": "x1", "ts": "t", "sender_id": "a",
               "recipient_id": "b", "type": "do_anything", "payload": {}}
        with self.assertRaises(teamctl.SchemaError):
            teamctl.validate_envelope(env)

    def test_envelope_recipient_excludes_broadcast(self):
        env = {"envelope_version": 1, "id": "x1", "ts": "t", "sender_id": "a",
               "recipient_id": "b", "broadcast": True, "type": "note", "payload": {}}
        with self.assertRaises(teamctl.SchemaError):
            teamctl.validate_envelope(env)


class TestHandoff(unittest.TestCase):
    def _pkg(self, recipient="b", visited=None, budget=5):
        return {"handoff_version": 1, "task_id": "t1", "sender_id": "a",
                "recipient_id": recipient, "goal": "do the thing",
                "constraints": [], "accepted_facts": [],
                "artifact_refs": ["shared/a/out.md"],
                "remaining_budget": budget, "budget_units": "steps",
                "visited_agents": visited or [], "created_at": "2026-09-14T00:00:00+00:00"}

    def test_ok_path(self):
        v, d = teamctl.check_handoff(self._pkg())
        self.assertEqual(v, "ok")
        self.assertEqual(d, "")

    def test_cycle_detection(self):
        v, d = teamctl.check_handoff(self._pkg(recipient="a", visited=["a"]))
        self.assertEqual(v, "cycle")
        self.assertIn("already visited", d)

    def test_budget_exhausted(self):
        v, d = teamctl.check_handoff(self._pkg(budget=0))
        self.assertEqual(v, "exhausted")

    def test_handoff_new_records_visited(self):
        with tempfile.TemporaryDirectory() as rt:
            r = teamctl.handoff_new(rt, "t9", "a", "b", "goal", 3, visited=[], record=True)
            self.assertEqual(r["verdict"], "ok")
            tasks = teamctl._read_json(teamctl.paths(rt)["tasks"])
            self.assertEqual(tasks["t9"]["visited"], ["b"])
            # 再次移交给前面访问过的 a -> 拒绝且不重复记录
            r2 = teamctl.handoff_new(rt, "t9", "b", "a", "goal", 3, visited=["a"], record=True)
            self.assertEqual(r2["verdict"], "cycle")

    def test_handoff_chain_inherits_registry_when_omitted(self):
        # 真实运行暴露的缺陷：CLI 缺省被转成 [] 而绕过继承，访问链被成员重置。
        with tempfile.TemporaryDirectory() as rt:
            r1 = teamctl.handoff_new(rt, "t-c", "a", "b", "goal", 3, visited=None, record=True)
            self.assertEqual(r1["handoff"]["visited_agents"], [])
            r2 = teamctl.handoff_new(rt, "t-c", "b", "c", "goal", 3, visited=None, record=True)
            # 未传 visited => 自动继承 + 追加 recipient，链不可被清空
            self.assertEqual(r2["handoff"]["visited_agents"], ["b"])
            tasks = teamctl._read_json(teamctl.paths(rt)["tasks"])
            self.assertEqual(tasks["t-c"]["visited"], ["b", "c"])
            # 闭环：c 把任务交回已接收过的 b 应被判 cycle（a 为发起者，未被判环）
            r3 = teamctl.handoff_new(rt, "t-c", "c", "b", "goal", 3, visited=None, record=True)
            self.assertEqual(r3["verdict"], "cycle")

    def test_split_visited_cli_semantics(self):
        self.assertIsNone(teamctl.split_visited(None))
        self.assertIsNone(teamctl.split_visited(""))
        self.assertEqual(teamctl.split_visited("a,b"), ["a", "b"])
        self.assertEqual(teamctl.split_visited(" dev , qa "), ["dev", "qa"])


class TestBus(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        teamctl.agent_new(self.root, "spec", role="spec", subscriptions=[{"topic": "planning"}])
        teamctl.agent_new(self.root, "dev", role="dev",
                          subscriptions=[{"topic": "planning", "event_types": ["task_assigned"]}])
        teamctl.agent_new(self.root, "qa", role="qa")

    def tearDown(self):
        self.tmp.cleanup()

    def test_direct_routing(self):
        teamctl.send(self.root, "spec", "task_assigned", recipient_id="dev",
                     payload={"task": "build x"})
        dev_msgs = teamctl.read(self.root, "dev")
        self.assertEqual(len(dev_msgs), 1)
        spec_msgs = teamctl.read(self.root, "spec")
        self.assertEqual(spec_msgs, [])

    def test_topic_subscription(self):
        teamctl.send(self.root, "spec", "note", topic="planning", payload={"idea": 1})
        dev = teamctl.read(self.root, "dev")  # 订阅了 planning/task_assigned
        self.assertEqual(dev, [])
        teamctl.send(self.root, "spec", "task_assigned", topic="planning", payload={"idea": 2})
        dev = teamctl.read(self.root, "dev")
        self.assertEqual(len(dev), 1)
        self.assertEqual(dev[0]["payload"]["idea"], 2)

    def test_agent_subscribe_idempotent_and_routes(self):
        # 追加订阅（幂等合并）；新主题新消息可读
        teamctl.agent_subscribe(self.root, "dev", "pool", ["status_update"])
        teamctl.agent_subscribe(self.root, "dev", "pool", ["status_update", "note"])
        card = teamctl._read_json(teamctl.paths(self.root)["agents"] / "dev" / "agent-card.json")
        subs = {s["topic"]: s.get("event_types") for s in card["subscriptions"]}
        self.assertEqual(subs["pool"], ["status_update", "note"])
        teamctl.send(self.root, "spec", "status_update", topic="pool", payload={"p": 1})
        teamctl.send(self.root, "spec", "note", topic="pool", payload={"p": 2})
        teamctl.send(self.root, "spec", "result", topic="pool", payload={"p": 3})
        msgs = teamctl.read(self.root, "dev")
        got = [m["type"] for m in msgs]
        self.assertEqual(got, ["status_update", "note"])  # result 未订阅 -> 不投递

    def test_broadcast(self):
        teamctl.send(self.root, "spec", "note", broadcast=True, payload={"all": True})
        for agent in ("spec", "dev", "qa"):
            self.assertEqual(len(teamctl.read(self.root, agent)), 1)

    def test_status_machine(self):
        teamctl.status_set(self.root, "qa", "running", "checking artifacts")
        st = teamctl.status_get(self.root, "qa")
        self.assertEqual(st["status"]["status"], "running")
        self.assertIn("checking artifacts", st["progress_tail"][-1])


class TestLock(unittest.TestCase):
    def test_optimistic_lock_conflict(self):
        with tempfile.TemporaryDirectory() as rt:
            f = "shared/plan.md"
            r1 = teamctl.lock_acquire(rt, f, "dev")
            self.assertTrue(r1["ok"])
            r2 = teamctl.lock_acquire(rt, f, "spec")  # 已被 dev 持锁 -> 冲突
            self.assertFalse(r2["ok"])
            r3 = teamctl.lock_release(rt, f, "dev")
            self.assertTrue(r3["ok"])
            r4 = teamctl.lock_acquire(rt, f, "spec")  # 释放后可重新获得
            self.assertTrue(r4["ok"])
            self.assertEqual(r4["lock"]["version"], 2)  # 版本号递增（CAS 语义）


class TestTrajectory(unittest.TestCase):
    def test_append_only_jsonl(self):
        with tempfile.TemporaryDirectory() as rt:
            teamctl.log_append(rt, "dev", "decision", {"choice": "use worktree"})
            teamctl.log_append(rt, "dev", "tool", {"tool": "write", "ok": True})
            rows = teamctl.log_read(rt, "dev")
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["event"]["choice"], "use worktree")


    def test_task_ops_view(self):
        with tempfile.TemporaryDirectory() as rt:
            teamctl.agent_new(rt, "spec", role="spec")
            teamctl.agent_new(rt, "dev", role="dev")
            teamctl.handoff_new(rt, "t-v", "spec", "dev", "view goal", 3, visited=None, record=True)
            rows = teamctl.task_list(rt)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["task_id"], "t-v")
            self.assertEqual(rows[0]["visited"], ["dev"])
            show = teamctl.task_show(rt, "t-v")
            self.assertEqual(show["goal"], "view goal")
            self.assertEqual(len(show["handoffs"]), 1)
            self.assertIsNone(teamctl.task_show(rt, "nope"))


    def test_fs_write_autolock_and_scope(self):
        with tempfile.TemporaryDirectory() as rt:
            teamctl.agent_new(rt, "dev", role="dev")
            r = teamctl.fs_write(rt, "dev", "shared/dev/note.md", "hello")
            self.assertTrue(r["ok"])
            self.assertEqual(r["lock_version"], 1)
            self.assertEqual(teamctl.fs_read(rt, "shared/dev/note.md")["content"], "hello")
            # 锁已释放（未卡锁）
            rep_locks = [teamctl._read_json(f) for f in (teamctl.paths(rt)["locks"]).glob("*.json")]
            self.assertTrue(all(not rec.get("locked_by") for rec in rep_locks))
            # 越界写被硬拒
            with self.assertRaises(teamctl.SchemaError):
                teamctl.fs_write(rt, "dev", "shared/qa/other.md", "x")

    def test_fs_write_conflict_no_write(self):
        with tempfile.TemporaryDirectory() as rt:
            teamctl.agent_new(rt, "dev", role="dev")
            teamctl.agent_new(rt, "qa", role="qa")
            teamctl.lock_acquire(rt, "shared/dev/plan.md", "qa")  # 他方持锁
            r = teamctl.fs_write(rt, "dev", "shared/dev/plan.md", "data")
            self.assertFalse(r["ok"])
            self.assertIn("locked by", r["reason"])
            self.assertFalse((pathlib.Path(rt) / "shared" / "dev" / "plan.md").exists())


class TestUsageMetering(unittest.TestCase):
    """D8/M8 token 计量（可插拔、估值标注、只增不改）。"""

    def test_estimate_heuristic(self):
        self.assertEqual(teamctl.estimate_tokens(""), 0)
        self.assertEqual(teamctl.estimate_tokens("abcd"), 1)
        self.assertGreater(teamctl.estimate_tokens("x" * 400), 90)

    def test_usage_record_and_summary(self):
        with tempfile.TemporaryDirectory() as rt:
            teamctl.agent_new(rt, "dev", role="dev")
            teamctl.agent_new(rt, "qa", role="qa")
            teamctl.usage_record(rt, "dev", 1, 100, source="estimate", op="fs_write", task_id="t-m")
            teamctl.usage_record(rt, "dev", 2, 50, source="estimate", op="handoff", task_id="t-m")
            teamctl.usage_record(rt, "qa", 1, 30, source="real:adapter-x", op="exec", task_id="t-m")
            s = teamctl.usage_summary(rt, task_id="t-m")
            self.assertEqual(s["records"], 3)
            self.assertEqual(s["total_est_tokens"], 180)
            self.assertEqual(s["by_agent"], {"dev": 150, "qa": 30})
            self.assertEqual(s["sources"], ["estimate", "real:adapter-x"])
            # 只增不改：再次读取行数不变
            self.assertEqual(len(teamctl._read_jsonl(teamctl.paths(rt)["usage"])), 3)


class TestQuota(unittest.TestCase):
    """M8 资源配额：预算池 + 并发上限。"""

    def test_quota_init_consume_status(self):
        with tempfile.TemporaryDirectory() as rt:
            q = teamctl.quota_init(rt, "t-long", "tokens", pool=1000, concurrency=2)
            self.assertEqual(q["pool"], 1000)
            r = teamctl.quota_consume(rt, "t-long", 250)
            self.assertTrue(r["ok"])
            self.assertEqual(r["remaining"], 750)
            st = teamctl.quota_status(rt, "t-long")
            self.assertEqual(st["spent"], 250)
            self.assertEqual(st["concurrency"], 2)
            self.assertIsNone(teamctl.quota_status(rt, "nope"))

    def test_quota_guardrails(self):
        with tempfile.TemporaryDirectory() as rt:
            teamctl.quota_init(rt, "t-q", "steps", pool=5)
            with self.assertRaises(teamctl.SchemaError):
                teamctl.quota_consume(rt, "t-unknown", 1)
            r = teamctl.quota_consume(rt, "t-q", 0)
            self.assertFalse(r["ok"])
            teamctl.quota_consume(rt, "t-q", 5)
            self.assertEqual(teamctl.quota_status(rt, "t-q")["remaining"], 0)


class TestStagingPromote(unittest.TestCase):
    """Ch9 待验证区 → 发布（守门角色 + 证据背书）。"""

    def _team(self, rt):
        teamctl.agent_new(rt, "dev", role="dev")
        teamctl.agent_new(rt, "qa", role="qa")
        teamctl.agent_new(rt, "ops", role="ops")

    def test_promote_requires_gatekeeper_and_evidence(self):
        with tempfile.TemporaryDirectory() as rt:
            self._team(rt)
            teamctl.fs_write(rt, "dev", "shared/dev/plan.md", "# plan")
            task = "t-st"
            # 非守门角色
            r1 = teamctl.fs_promote(rt, "dev", "shared/dev/plan.md", "plan.md", "dev", task)
            self.assertFalse(r1["ok"])
            self.assertIn("gatekeeper", r1["reason"])
            # 守门角色但无证据
            r2 = teamctl.fs_promote(rt, "dev", "shared/dev/plan.md", "plan.md", "qa", task)
            self.assertFalse(r2["ok"])
            self.assertIn("no evidence-backed", r2["reason"])
            self.assertFalse((pathlib.Path(rt) / "shared/deliverables/plan.md").exists())
            # 证据背书（method+evidence）→ 放行
            teamctl.send(rt, "qa", "review_result", topic="review", recipient_id="spec",
                         task_id=task,
                         payload={"verdict": "pass", "method": "exec tests",
                                  "evidence": "verify.out: PASS"})
            r3 = teamctl.fs_promote(rt, "dev", "shared/dev/plan.md", "plan.md", "qa", task)
            self.assertTrue(r3["ok"])
            self.assertTrue((pathlib.Path(rt) / "shared/deliverables/plan.md").exists())
            # staging 原件保留（只增不改）
            self.assertTrue((pathlib.Path(rt) / "shared/dev/plan.md").exists())

    def test_promote_scope(self):
        with tempfile.TemporaryDirectory() as rt:
            self._team(rt)
            teamctl.fs_write(rt, "dev", "shared/dev/plan.md", "# plan")
            with self.assertRaises(teamctl.SchemaError):
                teamctl.fs_promote(rt, "dev", "PLAN.md", "plan.md", "qa", "t-x")
            with self.assertRaises(teamctl.SchemaError):
                teamctl.fs_promote(rt, "dev", "shared/qa/other.md", "plan.md", "qa", "t-x")


class TestHandoffTokensUnits(unittest.TestCase):
    def test_tokens_budget_units(self):
        with tempfile.TemporaryDirectory() as rt:
            r = teamctl.handoff_new(rt, "t-tok", "spec", "dev", "goal",
                                    budget=2000, budget_units="tokens",
                                    visited=None, record=True)
            self.assertEqual(r["verdict"], "ok")
            self.assertEqual(r["handoff"]["budget_units"], "tokens")
            self.assertEqual(r["handoff"]["remaining_budget"], 2000)
            v, d = teamctl.check_handoff(r["handoff"])
            self.assertEqual(v, "ok")
            r0 = teamctl.handoff_new(rt, "t-tok0", "spec", "dev", "goal",
                                     budget=0, budget_units="tokens",
                                     visited=["spec"], record=False)
            self.assertEqual(r0["verdict"], "exhausted")


class TestMission(unittest.TestCase):
    """使命登记（可信根）+ 身份文件只读（成员不可自改角色/卡）。"""

    def test_mission_init_get(self):
        with tempfile.TemporaryDirectory() as rt:
            reg = teamctl.mission_init(rt, "A", "软件开发团队", ["spec", "dev", "qa"], revision=1)
            self.assertEqual(reg["mission"], "A")
            self.assertEqual(teamctl.mission_get(rt)["roles"], ["spec", "dev", "qa"])
            reg2 = teamctl.mission_init(rt, "B", "研究写作", ["writer", "editor"], revision=2)
            self.assertEqual(reg2["revision"], 2)  # 换挡 = revision+1（受控动态修改）
            with self.assertRaises(teamctl.SchemaError):
                teamctl.mission_init(rt, "C", "空", [])

    def test_identity_file_readonly(self):
        with tempfile.TemporaryDirectory() as rt:
            teamctl.agent_new(rt, "dev", role="dev")
            # 协议层 fs_write 拒写身份文件
            with self.assertRaises(teamctl.SchemaError):
                teamctl.fs_write(rt, "dev", "agents/dev/agent-card.json",
                                 '{"agent_id":"dev","role":"architect"}')
            # member 运行时 _check_write 同语义
            sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))
            from team import member  # noqa: E402
            m = member.MemberRuntime(rt, "dev", member.ScriptedLLM([]))
            with self.assertRaises(member.ToolError):
                m._check_write("agents/dev/agent-card.json")
            # 卡未被篡改
            card = teamctl._read_json(teamctl.paths(rt)["agents"] / "dev" / "agent-card.json")
            self.assertEqual(card["role"], "dev")
            # 私有 scratch 仍可写（只堵身份文件，不堵工作区）
            m._check_write("agents/dev/scratch/x.log")


if __name__ == "__main__":
    unittest.main(verbosity=2)
