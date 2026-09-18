#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""web_snapshot 数据契约测试（S0）：结构完整性、零副作用（只读）、审计联动。

运行：python3.10 tools/tests/test_web.py
"""
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import teamctl  # noqa: E402


def _setup_ws(root):
    teamctl.mission_init(root, "A", "软件开发团队", ["spec", "dev", "qa", "ops"])
    teamctl.agent_new(root, "spec", role="spec", subscriptions=[{"topic": "planning", "event_types": ["task_assigned"]}])
    teamctl.agent_new(root, "dev", role="dev")
    teamctl.agent_new(root, "qa", role="qa")
    teamctl.agent_new(root, "ops", role="ops")
    teamctl.send(root, "spec", "task_assigned", recipient_id="dev",
                 payload={"task": "hello"}, task_id="t1")
    teamctl.handoff_new(root, "t1", "spec", "dev", "hello world", 5, visited=["spec"])
    teamctl.usage_record(root, "dev", 1, 128, source="estimate", op="run", task_id="t1")
    teamctl.quota_init(root, "t1", "tokens", 1000, concurrency=2)
    teamctl.quota_consume(root, "t1", 128)
    teamctl.fs_write(root, "dev", "shared/dev/out.md", "# hi")
    teamctl.send(root, "qa", "review_result", topic="review", task_id="t1",
                 payload={"verdict": "pass", "method": "verify", "evidence": "assert ok"})
    teamctl.fs_promote(root, "dev", "shared/dev/out.md", "out.md", by="qa", task_id="t1")


class TestWebSnapshot(unittest.TestCase):
    def test_structure_and_content(self):
        with tempfile.TemporaryDirectory() as td:
            _setup_ws(td)
            s = teamctl.web_snapshot(td)
            for k in ("generated_at", "root", "mission", "agents", "tasks", "messages",
                      "handoffs", "conflicts", "usage", "quotas", "logs", "audit",
                      "eval_runs", "deliverables"):
                self.assertIn(k, s)
            self.assertEqual(s["mission"]["mission"], "A")
            by_id = {a["agent_id"]: a for a in s["agents"]}
            self.assertEqual(sorted(by_id), ["dev", "ops", "qa", "spec"])
            self.assertEqual(by_id["spec"]["role"], "spec")
            # 消息/任务/移交/配额/用量/交付物贯通
            self.assertTrue(any(m["type"] == "task_assigned" for m in s["messages"]))
            self.assertTrue(any(m["type"] == "review_result" for m in s["messages"]))
            self.assertEqual(s["tasks"][0]["task_id"], "t1")
            self.assertEqual(s["tasks"][0]["visited"], ["spec", "dev"])
            self.assertEqual(s["tasks"][0]["handoff_count"], 1)
            self.assertEqual(s["quotas"]["t1"]["spent"], 128)
            self.assertEqual(s["usage"]["total_est_tokens"], 128)
            self.assertEqual(s["deliverables"], ["shared/deliverables/out.md"])
            self.assertTrue(s["audit"]["passed"], s["audit"]["summary"])

    def test_readonly_no_side_effects(self):
        with tempfile.TemporaryDirectory() as td:
            _setup_ws(td)
            def file_count():
                return sum(1 for f in pathlib.Path(td, "system").rglob("*") if f.is_file())
            before = file_count()
            s1 = teamctl.web_snapshot(td)
            s2 = teamctl.web_snapshot(td)
            after = file_count()
            self.assertEqual(before, after)  # 快照零写入
            s1.pop("generated_at"); s2.pop("generated_at")
            self.assertEqual(s1, s2)  # 幂等（生成时间除外）

    def test_audit_failure_reflected(self):
        with tempfile.TemporaryDirectory() as td:
            teamctl.mission_init(td, "A", "T", ["spec", "dev"])
            teamctl.agent_new(td, "hacker", role="intruder")  # 角色不在登记表
            s = teamctl.web_snapshot(td)
            names = {c["name"]: c["status"] for c in s["audit"]["checks"]}
            self.assertEqual(names["card_role_known"], "fail")
            self.assertFalse(s["audit"]["passed"])


class TestMissionSwitchWeb(unittest.TestCase):
    def _ws(self, td):
        teamctl.mission_init(td, "A", "软件开发团队", ["spec", "dev"])
        teamctl.agent_new(td, "spec", role="spec")
        teamctl.agent_new(td, "dev", role="dev")

    def test_dry_run_sandbox(self):
        with tempfile.TemporaryDirectory() as td:
            self._ws(td)
            # 沙盒演练：新使命 + 当前卡片兼容 → 通过
            dr = teamctl.web_cmd(td, "mission_switch_dry",
                                 {"title": "研究写作", "roles": ["spec", "dev"],
                                  "mission": "B"})["result"]
            self.assertEqual(dr["suggested_revision"], 2)
            self.assertTrue(dr["audit"]["passed"], dr["audit"]["summary"])
            self.assertEqual(dr["mission"]["mission"], "B")
            # 真实工作区不受影响
            self.assertEqual(teamctl.mission_get(td)["revision"], 1)
            # 沙盒演练：不兼容角色表 → 审计把关（card_role_known fail）
            dr2 = teamctl.web_cmd(td, "mission_switch_dry",
                                  {"title": "研究写作", "roles": ["writer", "editor"]})["result"]
            self.assertFalse(dr2["audit"]["passed"])
            names = {c["name"]: c["status"] for c in dr2["audit"]["checks"]}
            self.assertEqual(names["card_role_known"], "fail")

    def test_apply_updates_registry_and_docs(self):
        with tempfile.TemporaryDirectory() as td:
            self._ws(td)
            r = teamctl.web_cmd(td, "mission_apply",
                                {"title": "软件开发团队 v2", "roles": ["spec", "dev"],
                                 "mission": "A", "by": "operator"})
            self.assertTrue(r["ok"], r)
            res = r["result"]
            self.assertEqual(res["registry"]["revision"], 2)
            self.assertEqual(len(res["history"]), 1)
            self.assertTrue(res["audit"]["passed"])
            roles_md = pathlib.Path(td, "docs", "roles.md").read_text(encoding="utf-8")
            self.assertIn("使命变更", roles_md)
            snap = teamctl.web_snapshot(td)
            self.assertEqual(snap["mission"]["revision"], 2)
            self.assertEqual(snap["mission_history"][-1]["mission"], "A")


if __name__ == "__main__":
    unittest.main(verbosity=2)
