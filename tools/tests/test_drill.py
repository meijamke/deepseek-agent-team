#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""drill.py 回归：五类注入在临时工作区上必须被守卫探测且可恢复。

运行：python3.10 tools/tests/test_drill.py
"""
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import drill  # noqa: E402
import teamctl  # noqa: E402


def _setup(root):
    teamctl.mission_init(root, "A", "软件开发团队", ["spec", "dev", "qa"])
    teamctl.agent_new(root, "spec", role="spec")
    teamctl.agent_new(root, "dev", role="dev", capabilities=["coding", "test"])
    teamctl.agent_new(root, "qa", role="qa", capabilities=["review", "verify"])
    art = pathlib.Path(root) / "shared" / "dev" / "ping.py"
    art.parent.mkdir(parents=True, exist_ok=True)
    art.write_text("def ping():\n    return 'pong'\n", encoding="utf-8")


class TestDrill(unittest.TestCase):
    def test_all_five_cases_detect_and_recover(self):
        with tempfile.TemporaryDirectory() as rt:
            _setup(rt)
            cases = [
                {"name": "F1-lock-stuck", "case": drill.drill_f1_stuck_lock},
                {"name": "F2-pass-without-evidence", "case": drill.drill_f2_pass_without_evidence},
                {"name": "F3-homogeneous", "case": drill.drill_f3_homogeneous},
                {"name": "F4-chain-reset", "case": drill.drill_f4_chain_reset},
                {"name": "F5-budget-exhausted", "case": drill.drill_f5_budget_exhausted},
                {"name": "F6-member-crash", "case": drill.drill_f6_member_crash},
            ]
            for c in cases:
                r = drill.run_drill(c, rt)
                self.assertTrue(r["detected"], "%s not detected: %s" % (c["name"], r["bad_findings"]))
                self.assertTrue(r["recovered"], "%s not recovered" % c["name"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
