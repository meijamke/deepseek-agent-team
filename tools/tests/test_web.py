#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""web_snapshot 数据契约测试（S0）：结构完整性、零副作用（只读）、审计联动。

运行：python3.10 tools/tests/test_web.py
"""
import pathlib
import re
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
            for k in ("generated_at", "root", "workspace_root", "teams", "mission", "agents",
                      "tasks", "messages", "handoffs", "conflicts", "usage", "quotas", "logs",
                      "audit", "eval_runs", "deliverables", "attention"):
                self.assertIn(k, s)
            self.assertEqual(s["workspace_root"], str(pathlib.Path(td).resolve()))
            self.assertEqual(s["teams"]["active"], "default")
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

    def test_attention_and_route(self):
        """#5180 实践点：attention 持续对象（需人工关注）+ 领域路由建议（无 Manager 仅建议）。"""
        with tempfile.TemporaryDirectory() as td:
            teamctl.mission_init(td, "A", "T", ["spec", "dev", "qa"])
            teamctl.agent_new(td, "spec", role="spec")
            teamctl.agent_new(td, "dev", role="dev")
            teamctl.agent_new(td, "qa", role="qa")
            # 干净工作区：无待关注
            s = teamctl.web_snapshot(td)
            self.assertEqual(s["attention"], [])
            # 成员 needs_input → attention 出现（高优先级、零副作用）
            teamctl.status_set(td, "dev", "needs_input", progress="需要人工确认")
            s2 = teamctl.web_snapshot(td)
            items = s2["attention"]
            self.assertEqual(len([i for i in items if i["kind"] == "agent" and i["subject"] == "dev"]), 1)
            self.assertEqual(items[0]["level"], "high")
            self.assertIn("需要人工介入", items[0]["reason"])
            # 路由建议：关键词命中 + 确定性
            r = teamctl.route_suggest(td, "实现订单模块并补充单元测试")
            self.assertIn("dev", r["matched"])
            self.assertTrue(r["suggested_chain"])
            self.assertIn("无 Manager", r["note"])
            r2 = teamctl.route_suggest(td, "部署到生产环境并监控")
            self.assertIn("ops", r2["matched"])
            # 无命中 → 默认流水线（仍不建议强制）
            r3 = teamctl.route_suggest(td, "随机目标xyz")
            self.assertEqual(r3["suggested_chain"], ["spec", "architect", "dev", "qa", "ops"])
            self.assertEqual(r3["matched"], {})

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
            self.assertTrue(dr["audit_ok"])
            self.assertEqual(dr["failing_checks"], [])
            self.assertEqual(dr["mission"]["mission"], "B")
            # 真实工作区不受影响
            self.assertEqual(teamctl.mission_get(td)["revision"], 1)
            # 沙盒演练：不兼容角色表 → 审计把关（card_role_known fail）
            dr2 = teamctl.web_cmd(td, "mission_switch_dry",
                                  {"title": "研究写作", "roles": ["writer", "editor"]})["result"]
            self.assertFalse(dr2["audit"]["passed"])
            self.assertFalse(dr2["audit_ok"])
            self.assertIn("card_role_known", dr2["failing_checks"])
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
            self.assertTrue(res["audit_ok"])
            self.assertEqual(res["failing_checks"], [])
            roles_md = pathlib.Path(td, "docs", "roles.md").read_text(encoding="utf-8")
            self.assertIn("使命变更", roles_md)
            snap = teamctl.web_snapshot(td)
            self.assertEqual(snap["mission"]["revision"], 2)
            self.assertEqual(snap["mission_history"][-1]["mission"], "A")


class TestTeams(unittest.TestCase):
    """多团队工作区：模板/自定义创建、自动激活、切换、隔离与校验（网页/CLI 共用）。"""

    def _default_ws(self, td):
        teamctl.mission_init(td, "A", "默认团队", ["spec", "dev", "qa"])
        for r in ("spec", "dev", "qa"):
            teamctl.agent_new(td, r, role=r)

    def test_templates_and_initial_registry(self):
        with tempfile.TemporaryDirectory() as td:
            self._default_ws(td)
            s = teamctl.web_snapshot(td)
            self.assertEqual(s["teams"]["active"], "default")
            self.assertEqual(s["teams"]["teams"], [])
            tpl = {t["id"]: t for t in teamctl.team_templates()}
            self.assertEqual(tpl["software"]["roles"],
                             ["spec", "architect", "dev", "qa", "ops"])
            self.assertIn("documentation", tpl)
            self.assertIn("research", tpl)
            self.assertIn("general", tpl)

    def test_create_template_autocreate_and_switch(self):
        with tempfile.TemporaryDirectory() as td:
            self._default_ws(td)
            r = teamctl.web_cmd(td, "team_create", {"template": "documentation"})
            self.assertTrue(r["ok"], r)
            res = r["result"]
            tid = res["team"]["team_id"]
            self.assertEqual(tid, "documentation")  # 模板 id 作团队 id
            self.assertEqual(res["team"]["roles"],
                             ["writer", "editor", "reviewer", "publisher"])
            self.assertEqual(res["active"], tid)     # 创建后自动激活
            troot = teamctl.team_effective_root(td)
            self.assertEqual(str(pathlib.Path(troot)).endswith("teams/" + tid), True)
            self.assertEqual(teamctl.mission_get(troot)["mission"], tid)  # 使命=团队
            self.assertEqual(sorted(a["agent_id"] for a in teamctl.agent_list(troot)),
                             ["editor", "publisher", "reviewer", "writer"])
            # 默认团队工作区不受影响（隔离）
            self.assertEqual(teamctl.mission_get(td)["mission"], "A")
            # 快照（teamd 语义：团队根 + 工作区根）携带团队注册表
            snap = teamctl.web_snapshot(troot, workspace_root=td)
            self.assertEqual(snap["teams"]["active"], tid)
            self.assertEqual(snap["workspace_root"], str(pathlib.Path(td).resolve()))
            self.assertEqual(snap["mission"]["mission"], tid)
            # 切回默认
            r2 = teamctl.web_cmd(td, "team_switch", {"team": "default"})
            self.assertTrue(r2["ok"], r2)
            self.assertEqual(r2["result"]["active"], "default")
            self.assertEqual(teamctl.team_effective_root(td), str(pathlib.Path(td).resolve()))
            self.assertEqual(teamctl.mission_get(td)["mission"], "A")
            # 再切回子团队
            self.assertTrue(teamctl.web_cmd(td, "team_switch", {"team": tid})["ok"])
            self.assertEqual(teamctl.mission_get(teamctl.team_effective_root(td))["mission"], tid)

    def test_custom_roles_and_validation(self):
        with tempfile.TemporaryDirectory() as td:
            r = teamctl.web_cmd(td, "team_create", {"template": "custom",
                                                    "roles": ["writer", "editor:内容编辑",
                                                              "reviewer", "writer"]})
            self.assertFalse(r["ok"])  # 重复角色被拒
            r = teamctl.web_cmd(td, "team_create", {"template": "custom",
                                                    "roles": ["writer", "editor:内容编辑",
                                                              "reviewer"]})
            self.assertTrue(r["ok"], r)
            tid = r["result"]["team"]["team_id"]
            self.assertTrue(re.match(r"^[a-z][a-z0-9-]*$", tid))
            troot = teamctl.team_effective_root(td)
            cards = {a["agent_id"]: a for a in teamctl.agent_list(troot)}
            self.assertEqual(cards["editor"]["name"], "内容编辑")
            # 显式 id 冲突 / 保留 id / 未知模板 / 非法角色 id
            self.assertFalse(teamctl.web_cmd(td, "team_create",
                                             {"team_id": tid, "roles": ["x"]})["ok"])
            self.assertFalse(teamctl.web_cmd(td, "team_create",
                                             {"team_id": "default", "roles": ["x"]})["ok"])
            self.assertFalse(teamctl.web_cmd(td, "team_create",
                                             {"template": "nope", "roles": ["x"]})["ok"])
            self.assertFalse(teamctl.web_cmd(td, "team_create",
                                             {"roles": ["Bad Role"]})["ok"])
            # 切换不存在的团队被拒
            self.assertFalse(teamctl.web_cmd(td, "team_switch", {"team": "ghost"})["ok"])

    def test_ensure_console_bootstrap_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            # 免初始化：未登记使命 → 默认团队（software 模板 5 角色 + 成员卡）
            b1 = teamctl.ensure_console(td)
            self.assertTrue(b1["bootstrapped"], b1)
            self.assertEqual(b1["mission"]["mission"], "default")
            self.assertEqual(b1["mission"]["roles"], ["spec", "architect", "dev", "qa", "ops"])
            self.assertEqual(len(b1["agents"]), 5)
            self.assertEqual(b1["registry"]["active"], "default")
            # 幂等：再调不重复建成员、不覆盖
            b2 = teamctl.ensure_console(td)
            self.assertFalse(b2["bootstrapped"])
            self.assertEqual(len(b2["agents"]), 5)
            self.assertEqual(len(teamctl.agent_list(td)), 5)
            # 已有其他使命 → 不引导、不覆盖
            with tempfile.TemporaryDirectory() as td2:
                teamctl.mission_init(td2, "A", "现有使命", ["spec", "dev"])
                b3 = teamctl.ensure_console(td2)
                self.assertFalse(b3["bootstrapped"])
                self.assertEqual(b3["mission"]["mission"], "A")
                self.assertEqual(teamctl.agent_list(td2), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
