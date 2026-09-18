#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""team-drill —— M5 故障注入演练（Ch10 六类失败模式 → 注入 → 探测 → 恢复）。

每个演练 = 在某工作区副本上：注入故障 → audit 必须抓到对应检查失败 → 撤销注入 →
audit 必须恢复为无 fail。产物（每场注入前后的审计报告 + README）写入
<root>/eval/run/<date>-drill-m5/，用于向人类证明「守卫在实战中抓真漏」。

用法：
  python3.10 tools/drill.py --root <workspace>            # 副本上跑全部演练
  python3.10 tools/drill.py --root <workspace> --live     # 追加一场真工作区卡锁演练（自恢复）
"""
import argparse
import datetime
import json
import os
import pathlib
import shutil
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import audit  # noqa: E402
import teamctl  # noqa: E402


# ---------------------------------------------------------------- 演练用例（注入 + 撤销）

def _latest_handoff(ws, task=None):
    p = teamctl.paths(ws)
    hs = []
    for f in p["handoffs"].glob("*.json"):
        h = teamctl._read_json(f, {})
        if task and h.get("task_id") != task:
            continue
        hs.append((h.get("created_at", ""), f, h))
    return sorted(hs)[-1] if hs else None


def drill_f1_stuck_lock(ws):
    """并发冲突：卡锁（获取后不释放 → 后到者被拒/审计报卡锁）。"""
    return {"inject": lambda: teamctl.lock_acquire(ws, "shared/probe-drill.md", "dev"),
            "undo": lambda: teamctl.lock_release(ws, "shared/probe-drill.md", "dev"),
            "expect_check": "locks_released"}


def drill_f2_pass_without_evidence(ws):
    """级联放大/假成功：审核放行却无 method/evidence（拜占庭式错误结论）。"""
    env = {"envelope_version": 1, "id": "drill0001", "ts": teamctl.now(),
           "sender_id": "qa", "recipient_id": "spec", "type": "review_result",
           "payload": {"task_id": "t-ping", "status": "pass",
                       "artifact": "shared/dev/ping.py"}, "task_id": "t-ping"}
    p = teamctl.paths(ws)

    def undo():
        rows = teamctl._read_jsonl(p["messages"] / "direct.jsonl")
        rows = [r for r in rows if r.get("id") != "drill0001"]
        (p["messages"] / "direct.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")

    return {"inject": lambda: teamctl._append_jsonl(p["messages"] / "direct.jsonl", env),
            "undo": undo, "expect_check": "evidence_gated"}


def drill_f3_homogeneous(ws):
    """同质趋同：两个成员画像完全同构（capabilities/role/tools 相同）。warn 级。"""
    p = teamctl.paths(ws)
    saved = {}

    def inject():
        for aid in ("spec", "dev"):
            cp = p["agents"] / aid / "agent-card.json"
            saved[aid] = cp.read_text(encoding="utf-8")
            card = teamctl._read_json(cp)
            card.update({"role": "general", "capabilities": ["coding"], "tools": []})
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")

    def undo():
        for aid, text in saved.items():
            (p["agents"] / aid / "agent-card.json").write_text(text, encoding="utf-8")

    return {"inject": inject, "undo": undo, "expect_check": "card_diversity", "expect_status": "warn"}


def drill_f4_chain_reset(ws):
    """互相扯皮/访问链被重置：dev→qa 移交包 visited 被清空（Round 4 历史缺陷复现）。"""
    # 在副本上新建一条链并注入重置
    teamctl.handoff_new(ws, "t-drill", "spec", "dev", "impl", 5, visited=None, record=True)
    r = teamctl.handoff_new(ws, "t-drill", "dev", "qa", "verify", 3,
                            artifact_refs=["shared/dev/ping.py"], visited=None, record=True)

    def inject():
        hp = pathlib.Path(r["path"])
        h = teamctl._read_json(hp)
        h["visited_agents"] = []
        hp.write_text(json.dumps(h, ensure_ascii=False, indent=2), encoding="utf-8")
        # 注册表同步成错误值（模拟 CLI bug 的完整后果）
        tp = teamctl.paths(ws)["tasks"]
        tasks = teamctl._read_json(tp, {})
        tasks["t-drill"]["visited"] = ["qa"]
        tp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")

    def undo():
        hp = pathlib.Path(r["path"])
        h = teamctl._read_json(hp)
        h["visited_agents"] = ["dev"]
        h["runtime_corrected"] = True
        h["runtime_correction"] = "drill undo"
        hp.write_text(json.dumps(h, ensure_ascii=False, indent=2), encoding="utf-8")
        tp = teamctl.paths(ws)["tasks"]
        tasks = teamctl._read_json(tp, {})
        tasks["t-drill"]["visited"] = ["dev", "qa"]
        tp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"inject": inject, "undo": undo, "expect_check": "handoff_chain"}


def drill_f6_member_crash(ws):
    """崩溃故障：成员状态停在 running 且陈旧（无心跳）——无 Manager 体系下其他成员应不受影响。"""
    p = teamctl.paths(ws)
    saved = {}

    def inject():
        import datetime
        for aid in ("dev",):
            sp = p["agents"] / aid / "status.json"
            saved[aid] = sp.read_text(encoding="utf-8")
            st = teamctl._read_json(sp, {})
            st["status"] = "running"
            st["updated_at"] = (datetime.datetime.now(datetime.timezone.utc)
                                - datetime.timedelta(hours=3)).isoformat()
            sp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")

    def undo():
        for aid, text in saved.items():
            (p["agents"] / aid / "status.json").write_text(text, encoding="utf-8")

    return {"inject": inject, "undo": undo, "expect_check": "stale_running"}


def drill_f5_budget_exhausted(ws):
    """循环失控：预算耗尽仍继续移交（remaining_budget=0 的包）。"""
    p = teamctl.paths(ws)
    h = {"handoff_version": 1, "task_id": "t-drill2", "sender_id": "qa", "recipient_id": "spec",
         "goal": "should not proceed", "constraints": [], "accepted_facts": [],
         "artifact_refs": [], "remaining_budget": 0.0, "budget_units": "steps",
         "visited_agents": ["dev", "qa"], "created_at": teamctl.now()}

    def inject():
        teamctl._write_json(p["handoffs"] / ("t-drill2-%s.json" % teamctl.new_id()), h)

    def undo():
        for f in p["handoffs"].glob("t-drill2-*.json"):
            f.unlink()

    return {"inject": inject, "undo": undo, "expect_check": "handoff_chain"}


# ---------------------------------------------------------------- 驱动器

def _check(rep, name):
    for c in rep["checks"]:
        if c["name"] == name:
            return c
    return None


def run_drill(spec, ws):
    name = spec["name"]
    inj = spec["case"](ws)
    bad_payload = inj["inject"]()
    rep_bad = audit.audit(ws)
    exp_check = inj["expect_check"]
    ch = _check(rep_bad, exp_check)
    expect_status = inj.get("expect_status", "fail")
    detected = ch is not None and ch["status"] == expect_status
    inj["undo"]()
    rep_good = audit.audit(ws)
    ok = {"name": name, "detected": detected, "expected_check": exp_check,
          "expected_status": expect_status,
          "inject_result": bad_payload, "bad_status": ch["status"] if ch else None,
          "bad_findings": ch["findings"] if ch else [],
          "recovered": rep_good["passed"], "bad_rep": rep_bad, "good_rep": rep_good}
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(prog="team-drill", description="M5 故障注入演练")
    ap.add_argument("--root", default=None)
    ap.add_argument("--live", action="store_true", help="额外在真实工作区做一场自恢复演练")
    args = ap.parse_args(argv)
    root = pathlib.Path(args.root or pathlib.Path(__file__).resolve().parent.parent).resolve()

    specs = [
        {"name": "F1-lock-stuck", "case": drill_f1_stuck_lock},
        {"name": "F2-pass-without-evidence", "case": drill_f2_pass_without_evidence},
        {"name": "F3-homogeneous", "case": drill_f3_homogeneous},
        {"name": "F4-chain-reset", "case": drill_f4_chain_reset},
        {"name": "F5-budget-exhausted", "case": drill_f5_budget_exhausted},
        {"name": "F6-member-crash", "case": drill_f6_member_crash},
    ]

    results = []
    for spec in specs:
        tmp = tempfile.mkdtemp(prefix="drill-")
        ws = pathlib.Path(tmp) / "ws"
        shutil.copytree(str(root), str(ws), symlinks=True)
        try:
            results.append(run_drill(spec, ws))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    if args.live:
        results.append(run_drill({"name": "LIVE-F1-lock-stuck", "case": drill_f1_stuck_lock}, str(root)))

    date = datetime.date.today().isoformat()
    out_dir = root / "eval" / "run" / (date + "-drill-m5")
    out_dir.mkdir(parents=True, exist_ok=True)
    for r in results:
        (out_dir / (r["name"] + ".json")).write_text(
            json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {"date": date, "drills": results,
              "summary": {"total": len(results),
                          "detected": sum(1 for r in results if r["detected"]),
                          "recovered": sum(1 for r in results if r["recovered"])}}
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    all_ok = all(r["detected"] and r["recovered"] for r in results)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
