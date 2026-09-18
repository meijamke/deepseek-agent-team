#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""team-audit 测试：健康工作区全 pass；各类破坏被对应检查捕获。

运行：python3.10 tools/tests/test_audit.py
"""
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import audit  # noqa: E402
import teamctl  # noqa: E402


def _healthy(root):
    teamctl.mission_init(root, "A", "软件开发团队", ["spec", "dev", "qa"])
    teamctl.agent_new(root, "spec", role="spec")
    teamctl.agent_new(root, "dev", role="dev", capabilities=["coding", "test"])
    teamctl.agent_new(root, "qa", role="qa", capabilities=["review", "verify"])
    h1 = teamctl.handoff_new(root, "t1", "spec", "dev", "impl", 6, visited=None, record=True)
    art = pathlib.Path(root) / "shared" / "dev" / "out.py"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text("def ping():\n    return 'pong'\n", encoding="utf-8")
    h2 = teamctl.handoff_new(root, "t1", "dev", "qa", "verify", 4,
                             artifact_refs=["shared/dev/out.py"], visited=None, record=True)
    teamctl.send(root, "dev", "result", recipient_id="spec", task_id="t1",
                 payload={"artifact": "shared/dev/out.py", "selfcheck": "ok"})
    teamctl.send(root, "qa", "review_result", recipient_id="spec", task_id="t1",
                 payload={"status": "pass", "artifact": "shared/dev/out.py",
                          "method": "execution", "evidence": "REVIEW_PASS: pong"})
    teamctl.log_append(root, "qa", "verdict", {"review": "pass"})
    return {"h1": h1, "h2": h2}


class TestAuditBaseline(unittest.TestCase):
    def test_healthy_passes(self):
        with tempfile.TemporaryDirectory() as rt:
            _healthy(rt)
            rep = audit.audit(rt)
            self.assertTrue(rep["passed"], json.dumps(rep, ensure_ascii=False, indent=2))
            names = {c["name"] for c in rep["checks"]}
            self.assertEqual(names, {"agents_registered", "card_role_known", "stale_running",
                                     "handoff_chain", "envelope_valid", "evidence_gated",
                                     "locks_released", "card_diversity"})

    def test_diversity_warn_not_fail(self):
        with tempfile.TemporaryDirectory() as rt:
            _healthy(rt)
            # 把 spec 与 dev 改成完全同构（同质趋同：共因失效风险）；
            # role 仍留在使命登记内（dev），只制造「画像完全一致」→ 仅 warn
            import json as _json
            for aid in ("spec", "dev"):
                cp = pathlib.Path(teamctl.paths(rt)["agents"]) / aid / "agent-card.json"
                card = teamctl._read_json(cp)
                card["role"] = "dev"
                card["capabilities"] = ["coding"]
                card["tools"] = []
                cp.write_text(_json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
            rep = audit.audit(rt)
            self.assertTrue(rep["passed"])  # warn 不判失败
            ch = next(c for c in rep["checks"] if c["name"] == "card_diversity")
            self.assertEqual(ch["status"], "warn")
            self.assertTrue(any("identical" in f for f in ch["findings"]))

    def test_broken_visited_chain_detected(self):
        with tempfile.TemporaryDirectory() as rt:
            _healthy(rt)
            # 模拟 CLI 缺陷：dev→qa 的 visited 被清空（按 created_at 取最新包）
            hp = pathlib.Path(teamctl.paths(rt)["handoffs"])
            hs = []
            for f in hp.glob("*.json"):
                hs.append((teamctl._read_json(f).get("created_at", ""), f))
            old = sorted(hs)[-1][1]
            h = teamctl._read_json(old)
            h["visited_agents"] = []
            old.write_text(json.dumps(h, ensure_ascii=False, indent=2), encoding="utf-8")
            rep = audit.audit(rt)
            ch = next(c for c in rep["checks"] if c["name"] == "handoff_chain")
            self.assertEqual(ch["status"], "fail")
            self.assertTrue(any("chain reset" in f for f in ch["findings"]))

    def test_stuck_lock_detected(self):
        with tempfile.TemporaryDirectory() as rt:
            _healthy(rt)
            teamctl.lock_acquire(rt, "shared/plan.md", "dev")  # 不释放 -> 卡锁
            rep = audit.audit(rt)
            ch = next(c for c in rep["checks"] if c["name"] == "locks_released")
            self.assertEqual(ch["status"], "fail")
            self.assertTrue(any("stuck lock" in f for f in ch["findings"]))

    def test_review_without_evidence_detected(self):
        with tempfile.TemporaryDirectory() as rt:
            _healthy(rt)
            # 直接篡改：放行却无 method/evidence（级联放大/假成功）
            teamctl.send(rt, "qa", "review_result", recipient_id="spec", task_id="t1",
                         payload={"status": "pass", "artifact": "shared/dev/out.py"})
            rep = audit.audit(rt)
            ch = next(c for c in rep["checks"] if c["name"] == "evidence_gated")
            self.assertEqual(ch["status"], "fail")
            self.assertTrue(any("without method/evidence" in f for f in ch["findings"]))

    def test_missing_artifact_detected(self):
        with tempfile.TemporaryDirectory() as rt:
            _healthy(rt)
            (pathlib.Path(rt) / "shared" / "dev" / "out.py").unlink()
            rep = audit.audit(rt)
            ch = next(c for c in rep["checks"] if c["name"] == "evidence_gated")
            self.assertEqual(ch["status"], "fail")
            self.assertTrue(any("missing" in f for f in ch["findings"]))

    def test_mission_registry_missing_fails(self):
        with tempfile.TemporaryDirectory() as rt:
            teamctl.agent_new(rt, "spec", role="spec")
            rep = audit.audit(rt)
            ch = next(c for c in rep["checks"] if c["name"] == "card_role_known")
            self.assertEqual(ch["status"], "fail")
            self.assertTrue(any("mission registry missing" in f for f in ch["findings"]))

    def test_self_role_change_detected(self):
        with tempfile.TemporaryDirectory() as rt:
            _healthy(rt)
            # 模拟（被我们堵死前的）自改卡：dev 把 role 改成架构师
            cp = pathlib.Path(teamctl.paths(rt)["agents"]) / "dev" / "agent-card.json"
            card = teamctl._read_json(cp)
            card["role"] = "architect"
            cp.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
            rep = audit.audit(rt)
            ch = next(c for c in rep["checks"] if c["name"] == "card_role_known")
            self.assertEqual(ch["status"], "fail")
            self.assertTrue(any("not in mission" in f for f in ch["findings"]))

    def test_mission_switch_dry_run(self):
        """使命换挡演练（规程第 2-3 步在沙盒工作区）：登记 v2 + 新角色卡 → 审计一致通过；
        旧使命成员残留 → card_role_known FAIL（换挡必须整体迁移，不允许半新半旧）。"""
        with tempfile.TemporaryDirectory() as rt:
            # 沙盒：使命 B（研究写作）v2
            teamctl.mission_init(rt, "B", "研究写作", ["writer", "editor", "reviewer"], revision=2)
            teamctl.agent_new(rt, "writer", role="writer")
            teamctl.agent_new(rt, "editor", role="editor")
            teamctl.agent_new(rt, "reviewer", role="reviewer")
            rep = audit.audit(rt)
            ch = next(c for c in rep["checks"] if c["name"] == "card_role_known")
            self.assertEqual(ch["status"], "pass")
            # 旧使命成员残留（同步失败）→ 拦截
            teamctl.agent_new(rt, "dev", role="dev")
            rep2 = audit.audit(rt)
            ch2 = next(c for c in rep2["checks"] if c["name"] == "card_role_known")
            self.assertEqual(ch2["status"], "fail")
            self.assertTrue(any("dev" in f for f in ch2["findings"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
