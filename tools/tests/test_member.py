#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""member 运行时测试：去中心化协作剧本、写权限边界、并发冲突、超时兜底。

运行：python3.10 tools/tests/test_member.py
"""
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import teamctl  # noqa: E402
from team import member  # noqa: E402


def setup_team(root):
    teamctl.agent_new(root, "spec", role="spec",
                      subscriptions=[{"topic": "planning", "event_types": ["task_assigned"]}])
    teamctl.agent_new(root, "dev", role="dev",
                      subscriptions=[{"topic": "tasks", "event_types": ["task_assigned"]}])
    teamctl.agent_new(root, "qa", role="qa",
                      subscriptions=[{"topic": "review", "event_types": ["review_request", "review_result"]}])


class TestDecentralizedScenario(unittest.TestCase):
    """spec → dev → qa 的去中心化手递手协作（无 Manager）。"""

    def test_full_chain(self):
        with tempfile.TemporaryDirectory() as rt:
            setup_team(rt)
            spec = member.MemberRuntime(rt, "spec", member.ScriptedLLM([
                {"op": "status", "status": "running", "progress": "clarifying"},
                {"op": "bus_send", "type": "task_assigned", "recipient": "dev",
                 "payload": {"task": "implement ping"}, "task_id": "t-ping"},
                {"op": "handoff", "recipient": "dev", "goal": "implement ping",
                 "task_id": "t-ping", "budget": 5},
                {"op": "done", "progress": "spec handed off"},
            ]))
            dev = member.MemberRuntime(rt, "dev", member.ScriptedLLM([
                {"op": "status", "status": "running"},
                {"op": "bus_read", "tail": 3},
                {"op": "fs_write", "path": "shared/dev/ping.py",
                 "content": 'def ping():\n    return "pong"\n'},
                {"op": "handoff", "recipient": "qa", "goal": "verify ping",
                 "task_id": "t-ping", "budget": 3,
                 "artifacts": ["shared/dev/ping.py"]},
                {"op": "bus_send", "type": "review_request", "recipient": "qa",
                 "payload": {"artifact": "shared/dev/ping.py"}, "task_id": "t-ping"},
                {"op": "done", "progress": "dev complete"},
            ]))
            qa = member.MemberRuntime(rt, "qa", member.ScriptedLLM([
                {"op": "status", "status": "running"},
                {"op": "fs_read", "path": "shared/dev/ping.py"},
                {"op": "log", "kind": "verdict",
                 "event": {"verdict": "pass", "evidence": "artifact read ok"}},
                {"op": "bus_send", "type": "review_result", "recipient": "spec",
                 "payload": {"verdict": "pass", "artifact": "shared/dev/ping.py",
                             "evidence_ref": "system/logs/qa.jsonl"}, "task_id": "t-ping"},
                {"op": "done", "progress": "verified"},
            ]))

            for m in (spec, dev, qa):
                s = m.run()
                self.assertEqual(s["final"], "done", s)

            # 产物落盘
            artifact = pathlib.Path(rt) / "shared/dev/ping.py"
            self.assertTrue(artifact.exists())
            self.assertIn("pong", artifact.read_text(encoding="utf-8"))

            # 控制平面：qa 收到 review_request 且发出 review_result=pass
            qa_inbox = teamctl.read(rt, "qa")
            self.assertIn("review_request", [m["type"] for m in qa_inbox])
            spec_inbox = teamctl.read(rt, "spec")
            review = [m for m in spec_inbox if m["type"] == "review_result"]
            self.assertEqual(review[0]["payload"]["verdict"], "pass")

            # handoff 链记录（去中心化：dev 直接移交给 qa，无需经过 spec）
            tasks = teamctl._read_json(teamctl.paths(rt)["tasks"])
            self.assertEqual(tasks["t-ping"]["visited"], ["dev", "qa"])
            handoffs = list((pathlib.Path(rt) / "system/state/handoffs").glob("*.json"))
            self.assertEqual(len(handoffs), 2)

            # 轨迹与状态
            qa_logs = teamctl.log_read(rt, "qa")
            self.assertEqual(qa_logs[-1]["event"]["verdict"], "pass")
            for agent in ("spec", "dev", "qa"):
                self.assertEqual(teamctl.status_get(rt, agent)["status"]["status"], "done")

    def test_write_scope_denied(self):
        with tempfile.TemporaryDirectory() as rt:
            setup_team(rt)
            m = member.MemberRuntime(rt, "dev", member.ScriptedLLM([]))
            with self.assertRaises(member.ToolError):
                m._check_write("shared/qa/secret.md")   # 越权写他人命名空间
            with self.assertRaises(member.ToolError):
                m._check_write("PLAN.md")               # 越权写根目录
            with self.assertRaises(member.ToolError):
                m._check_write("agents/dev/agent-card.json")  # 身份文件只读（角色不可自改）
            m._check_write("shared/dev/ok.md")          # 本成员命名空间可写
            m._check_write("agents/dev/scratch/x.log")  # 私有工作区可写

    def test_concurrent_write_conflict(self):
        with tempfile.TemporaryDirectory() as rt:
            setup_team(rt)
            teamctl.lock_acquire(rt, "shared/dev/ping.py", "qa")  # qa 先持锁
            m = member.MemberRuntime(rt, "dev", member.ScriptedLLM([]))
            with self.assertRaises(member.ToolError):
                m._execute({"op": "fs_write", "path": "shared/dev/ping.py",
                            "content": "x = 1\n"})

    def test_max_steps_timeout(self):
        with tempfile.TemporaryDirectory() as rt:
            setup_team(rt)

            class NoopLLM(member.LLMBackend):
                def act(self, context):
                    return {"op": "bus_read", "tail": 2}

            s = member.run_member(rt, "spec", NoopLLM(), max_steps=3)
            self.assertEqual(s["final"], "failed:max_steps")
            self.assertEqual(teamctl.status_get(rt, "spec")["status"]["status"], "failed")


class TestContextAssembly(unittest.TestCase):
    def test_progressive_disclosure(self):
        with tempfile.TemporaryDirectory() as rt:
            setup_team(rt)
            (pathlib.Path(rt) / "skills/glossary").mkdir(parents=True, exist_ok=True)
            (pathlib.Path(rt) / "skills/glossary/SKILL.md").write_text("# glossary\n", encoding="utf-8")
            teamctl.send(rt, "spec", "task_assigned", recipient_id="dev",
                         payload={"task": "ping"}, task_id="t-1")
            m = member.MemberRuntime(rt, "dev", member.ScriptedLLM([]))
            ctx = m._context()
            self.assertEqual(ctx["identity"]["role"], "dev")
            self.assertIn("glossary", ctx["skills_index"])       # 索引而非全文
            self.assertEqual(ctx["pending_messages"][0]["task_id"], "t-1")


class TestTokenMeterAndQuota(unittest.TestCase):
    """可插拔 token 计量（每步登记 usage.jsonl）+ 预算池配额门（M8）。"""

    def test_step_usage_recorded(self):
        with tempfile.TemporaryDirectory() as rt:
            setup_team(rt)
            m = member.MemberRuntime(rt, "dev", member.ScriptedLLM([
                {"op": "status", "status": "running"},
                {"op": "bus_read", "tail": 2},
                {"op": "done"},
            ], est_tokens=42), task_id="t-usage")
            s = m.run()
            self.assertEqual(s["final"], "done")
            self.assertEqual(s["est_tokens_total"], 126)  # 3 步 × 42
            rows = teamctl._read_jsonl(teamctl.paths(rt)["usage"])
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(r["est_tokens"] == 42 for r in rows))
            self.assertTrue(all(r["source"] == "estimate" for r in rows))
            self.assertTrue(all(r["task_id"] == "t-usage" for r in rows))
            summ = teamctl.usage_summary(rt, task_id="t-usage")
            self.assertEqual(summ["total_est_tokens"], 126)

    def test_budget_pool_gate(self):
        with tempfile.TemporaryDirectory() as rt:
            setup_team(rt)
            teamctl.quota_init(rt, "t-pool", "tokens", pool=50)
            s = member.run_member(rt, "dev", member.ScriptedLLM([
                {"op": "status", "status": "running"},
                {"op": "done"},
            ], est_tokens=100), task_id="t-pool", budget_pool_task="t-pool")
            # 100 > 50：第 2 步开始时即被配额门拦下（未执行 done）
            self.assertEqual(s["final"], "failed:quota")
            self.assertEqual(teamctl.status_get(rt, "dev")["status"]["status"], "failed")

    def test_exec_op_returns_code_and_output(self):
        with tempfile.TemporaryDirectory() as rt:
            setup_team(rt)
            teamctl.fs_write(rt, "dev", "shared/dev/demo.py", "print('HELLO_EXEC')\n")
            m = member.MemberRuntime(rt, "qa", member.ScriptedLLM([]))
            obs = m._execute({"op": "exec", "cmd": ["python3.10", "shared/dev/demo.py"]})
            self.assertEqual(obs["code"], 0)
            self.assertIn("HELLO_EXEC", obs["stdout"])
            with self.assertRaises(member.ToolError):
                m._execute({"op": "exec", "cmd": []})


if __name__ == "__main__":
    unittest.main(verbosity=2)
