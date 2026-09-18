#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""team-audit —— 控制平面守卫（M3 · Ch10 失败模式的可检查不变量）。

每个检查对应 Ch10 的一类失败模式，从工作区当前状态**只读**地给出 pass/fail/warn：
  - agents_*        : 成员注册/状态机（拜占庭故障检测的基线）
  - handoff_*       : 访问链一致性 + 预算（环/级联, 失败模式二/五）
  - envelope_*      : 信封合法 + 收发双方注册（接口定义清晰, 14 模式·系统设计缺陷）
  - evidence_*      : 证据门禁（无证据不放行 · 失败模式二「级联放大」/ 任务验证缺失）
  - locks_*         : 锁全部释放（失败模式一「并发冲突」）
  - stale_running   : 崩溃故障（状态= running 但长时间无心跳）

输出：JSON 报告 + 退出码（0=无 fail；1=存在 fail）。--strict 时 warn 也计失败。

用法：python3.10 tools/audit.py [--root <workspace>] [--max-stale-hours 2] [--strict]
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import teamctl  # noqa: E402

AGENT_STATUS = {"idle", "running", "needs_input", "done", "failed"}


def _load_msgs(p):
    rows = []
    for f in sorted(p["messages"].glob("*.jsonl")):
        for m in teamctl._read_jsonl(f):
            rows.append((f.name, m))
    return rows


def _artifact_candidates(h=None, msg=None):
    """收集应存在的产物路径引用。"""
    out = []
    if h:
        out.extend(h.get("artifact_refs", []))
    if msg:
        payload = msg.get("payload") or {}
        for k in ("artifact", "artifact_path", "file", "path"):
            v = payload.get(k)
            if isinstance(v, str) and v:
                out.append(v)
    return out


def check_agents(root):
    p = teamctl.paths(root)
    findings = []
    cards = list(p["agents"].glob("*/agent-card.json"))
    for card_p in cards:
        aid = card_p.parent.name
        try:
            card = teamctl._read_json(card_p, {})
            teamctl.validate_card(card)
        except teamctl.SchemaError as e:
            findings.append("card %s: %s" % (aid, e))
        status_p = p["agents"] / aid / "status.json"
        st = teamctl._read_json(status_p, {})
        if st.get("status") not in AGENT_STATUS:
            findings.append("status %s: unexpected %r" % (aid, st.get("status")))
    if not cards:
        findings.append("no agents registered")
    return findings


def check_stale(root, max_stale_hours):
    p = teamctl.paths(root)
    findings = []
    for status_p in p["agents"].glob("*/status.json"):
        st = teamctl._read_json(status_p, {})
        if st.get("status") == "running" and st.get("updated_at"):
            ts = st["updated_at"]
            try:
                from datetime import datetime, timezone
                updated = datetime.fromisoformat(ts)
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
                age_h = (datetime.now(timezone.utc) - updated).total_seconds() / 3600.0
                if age_h > max_stale_hours:
                    findings.append("%s running but stale %.1fh" % (status_p.parent.name, age_h))
            except ValueError:
                findings.append("%s bad timestamp %r" % (status_p.parent.name, ts))
    return findings


def check_handoffs(root):
    """访问链一致性 + 最新包 verdict（环/预算）+ 注册表对齐。"""
    p = teamctl.paths(root)
    findings = []
    by_task = {}
    for hp in sorted(p["handoffs"].glob("*.json")):
        h = teamctl._read_json(hp, {})
        by_task.setdefault(h.get("task_id", "?"), []).append((hp, h))
    for task, items in by_task.items():
        items.sort(key=lambda t: t[1].get("created_at", ""))
        prev = None
        for i, (hp, h) in enumerate(items):
            try:
                teamctl.validate_handoff(h)
            except teamctl.SchemaError as e:
                findings.append("%s: schema %s" % (hp.name, e))
                continue
            if i > 0 and prev is not None:
                expect = list(prev[1].get("visited_agents", [])) + [prev[1]["recipient_id"]]
                if h.get("visited_agents") != expect:
                    findings.append(
                        "%s: visited chain reset/broken expected=%s got=%s"
                        % (hp.name, expect, h.get("visited_agents")))
            prev = (hp, h)
        # 注册表对齐 + 最新包 verdict
        reg = teamctl._read_json(p["tasks"], {}).get(task, {})
        if items:
            latest = items[-1][1]
            expect_reg = list(latest.get("visited_agents", [])) + [latest["recipient_id"]]
            if reg.get("visited") and reg["visited"] != expect_reg:
                findings.append(
                    "task %s: registry visited %s != handoff chain %s"
                    % (task, reg.get("visited"), expect_reg))
            verdict, detail = teamctl.check_handoff(latest)
            if verdict != "ok":
                findings.append("task %s latest handoff verdict=%s (%s)" % (task, verdict, detail))
        elif reg:
            findings.append("task %s: registry exists but no handoff" % task)
    return findings


def check_envelopes(root):
    p = teamctl.paths(root)
    findings = []
    registered = {c["agent_id"] for c in teamctl.agent_list(root)}
    for fname, m in _load_msgs(p):
        where = "%s#%s" % (fname, m.get("id", "?"))
        try:
            teamctl.validate_envelope(m)
        except teamctl.SchemaError as e:
            findings.append("%s: invalid envelope %s" % (where, e))
            continue
        if m["sender_id"] not in registered:
            findings.append("%s: sender %s not registered" % (where, m["sender_id"]))
        rec = m.get("recipient_id")
        if rec and rec not in registered:
            findings.append("%s: recipient %s not registered" % (where, rec))
    return findings


def check_evidence(root):
    p = teamctl.paths(root)
    findings = []
    # 1) 引用的产物必须存在
    for hp in p["handoffs"].glob("*.json"):
        h = teamctl._read_json(hp, {})
        for ref in _artifact_candidates(h=h):
            if not (p["root"] / ref).exists():
                findings.append("handoff %s: artifact_ref missing: %s" % (hp.name, ref))
    for fname, m in _load_msgs(p):
        for ref in _artifact_candidates(msg=m):
            if not (p["root"] / ref).exists():
                findings.append("%s: payload artifact missing: %s" % (fname, ref))
        # 2) 审核放行必须有证据（无证据放行 = 级联放大/假成功）
        if m.get("type") == "review_result" and (m.get("payload") or {}).get("status") == "pass":
            pl = m["payload"]
            if not (pl.get("method") and str(pl.get("evidence", "")).strip()):
                findings.append("%s: review_result pass without method/evidence" % fname)
    return findings


def check_locks(root):
    p = teamctl.paths(root)
    findings = []
    for lp in p["locks"].glob("*.json"):
        rec = teamctl._read_json(lp, {})
        if rec.get("locked_by"):
            findings.append("stuck lock: %s held by %s" % (rec.get("file"), rec["locked_by"]))
    return findings


def check_card_roles(root):
    """使命一致性：成员卡 role 必须 ∈ 当前使命登记（system/state/mission.json 角色表）。
    登记缺失 = 使命未声明（fail）；角色越界 = 角色被自改/漂移（fail）。
    这是「使命受控动态修改」的审计闸：换挡必须由运行时把登记表 revision+1，
    成员侧（fs_write/member）对 agent-card.json 只读（见 _check_fs_scope）。"""
    p = teamctl.paths(root)
    findings = []
    reg = teamctl._read_json(p["quotas"].parent / "mission.json")
    if reg is None:
        return ["mission registry missing: system/state/mission.json (roles unverified)"]
    roles = set(reg.get("roles", []))
    for card_p in p["agents"].glob("*/agent-card.json"):
        card = teamctl._read_json(card_p, {})
        role = card.get("role")
        if role not in roles:
            findings.append("agent %s: role %r not in mission %s roles %s"
                            % (card.get("agent_id", card_p.parent.name), role,
                               reg.get("mission"), sorted(roles)))
    return findings


def check_diversity(root):
    """同质趋同（F3）：role/capabilities/tools 完全相同的成员 = 共因失效风险。
    warn 级：只能提示，不能判失败（多样性部分由使命/角色集决定）。"""
    p = teamctl.paths(root)
    sig = {}
    for card_p in p["agents"].glob("*/agent-card.json"):
        card = teamctl._read_json(card_p, {})
        key = (str(card.get("role", "")),
               tuple(sorted(card.get("capabilities", []))),
               tuple(sorted(card.get("tools", []))))
        sig.setdefault(key, []).append(card.get("agent_id", card_p.parent.name))
    return ["role/capabilities/tools identical -> 共因失效风险: %s" % ",".join(v)
            for v in sig.values() if len(v) > 1]


def audit(root, max_stale_hours=2.0):
    # (名称, 标题, 检查函数, 模式) —— 模式 warn 的检查不计入 passed 失败
    checks = [
        ("agents_registered", "成员注册/状态机合法", check_agents, "fail"),
        ("card_role_known", "使命一致性：成员角色 ∈ 任务登记角色表", check_card_roles, "fail"),
        ("stale_running", "崩溃故障：running 长时间无心跳", lambda r: check_stale(r, max_stale_hours), "fail"),
        ("handoff_chain", "访问链一致性/预算/注册表对齐", check_handoffs, "fail"),
        ("envelope_valid", "信封合法且收发双方注册", check_envelopes, "fail"),
        ("evidence_gated", "产物引用存在 + 放行必须带证据", check_evidence, "fail"),
        ("locks_released", "共享区锁全部释放", check_locks, "fail"),
        ("card_diversity", "同质趋同：成员画像应相互区分", check_diversity, "warn"),
    ]
    result = {"root": str(pathlib.Path(root).resolve()), "checks": [], "passed": True, "fail": 0, "warn": 0}
    for name, title, fn, mode in checks:
        try:
            findings = fn(root) or []
        except Exception as e:  # noqa: BLE001 —— 审计不能因单项崩溃
            findings = ["audit error: %s: %s" % (type(e).__name__, e)]
        if findings:
            status = "fail" if mode == "fail" else "warn"
        else:
            status = "pass"
        if status == "fail":
            result["fail"] += 1
            result["passed"] = False
        elif status == "warn":
            result["warn"] += 1
        result["checks"].append({"name": name, "title": title, "status": status, "findings": findings})
    result["summary"] = "%d check groups, %d failing, %d warning" % (len(checks), result["fail"], result["warn"])
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(prog="team-audit", description="控制平面只读守卫（M3）")
    ap.add_argument("--root", default=None)
    ap.add_argument("--max-stale-hours", type=float, default=2.0)
    args = ap.parse_args(argv)
    root = args.root or str(pathlib.Path(__file__).resolve().parent.parent)
    rep = audit(root, args.max_stale_hours)
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0 if rep["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
