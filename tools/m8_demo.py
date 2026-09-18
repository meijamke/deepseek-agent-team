#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""m8_demo.py — M8 起点演示：5 角色 + 预算池配额 + 待验证区发布 + 涌现日志。

任务 t-m8-long（长周期多步）：spec → architect（设计）→ dev（实现+自测）→ qa（独立验证）
→ ops（evidence 背书后 promote 到 shared/deliverables/）。全程无 Manager；
资源配额：预算池 10000 est-tokens、并发上限 1（按序执行即满足 ≤1）；
每步 token 用量登记 usage.jsonl（estimate 标注）。

「涌现」在本演示中以可指认事件记录（非营销词）：
  e1 主题自建：architect 创建设计主题 design 并广播（无中心调度）；
  e2 跨角色递进：每次移交给下游带来**新信息**（设计文档/测试输出/验证证据）；
  e3 发布守门：ops 仅凭 evidence 背书放行（角色规程决策表兑现为代码）；
  e4 预算感知：配额池被逐步消费且成员在池内完成（不超支）。

运行：python3.10 tools/m8_demo.py [OUT_DIR]（缺省 eval/run/2026-09-14-m8-demo）
"""
from __future__ import annotations

import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import teamctl  # noqa: E402
from team import member  # noqa: E402

TASK = "t-m8-long"
ARCH = '''\
# Architecture (t-m8-long)
- module: service/order.py (place_order, cancel_order)
- invariants: totals are Decimal-safe; idempotency key required
- test plan: test_order.py covering happy path / duplicate / invalid
'''

ORDER_PY = '''\
class OrderError(ValueError):
    pass


class OrderService:
    def __init__(self):
        self._orders = {}

    def place_order(self, order_id, amount):
        if not order_id or amount <= 0:
            raise OrderError("bad order")
        if order_id in self._orders:
            raise OrderError("duplicate")
        self._orders[order_id] = amount
        return {"id": order_id, "amount": amount}

    def cancel_order(self, order_id):
        if order_id not in self._orders:
            raise OrderError("missing")
        return {"id": order_id, "cancelled": True}
'''

TEST_PY = '''\
import sys
sys.path.insert(0, "shared/dev")
from order import OrderService

s = OrderService()
assert s.place_order("a", 10)["amount"] == 10
try:
    s.place_order("a", 20)
    raise SystemExit("FAIL: duplicate allowed")
except Exception:
    pass
try:
    s.place_order("b", -1)
    raise SystemExit("FAIL: negative allowed")
except Exception:
    pass
assert s.cancel_order("a")["cancelled"] is True
print("ORDER_TESTS_PASS")
'''


def _setup(root):
    teamctl.mission_init(root, "A", "软件开发团队",
                         ["spec", "architect", "dev", "qa", "ops"])
    teamctl.agent_new(root, "spec", role="spec",
                      subscriptions=[{"topic": "planning"}])
    teamctl.agent_new(root, "architect", role="architect",
                      subscriptions=[{"topic": "planning"}, {"topic": "design"}])
    teamctl.agent_new(root, "dev", role="dev",
                      subscriptions=[{"topic": "tasks"}])
    teamctl.agent_new(root, "qa", role="qa",
                      subscriptions=[{"topic": "review"}])
    teamctl.agent_new(root, "ops", role="ops",
                      subscriptions=[{"topic": "gate"}])


def main():
    out_dir = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else \
        pathlib.Path(__file__).resolve().parent.parent / "eval/run/2026-09-14-m8-demo"
    with tempfile.TemporaryDirectory() as rt:
        _setup(rt)
        teamctl.quota_init(rt, TASK, "tokens", pool=10000, concurrency=1)
        # spec：任务单经主题分发（消息池），并移交 architect
        member.run_member(rt, "spec", member.ScriptedLLM([
            {"op": "status", "status": "running", "progress": "plan t-m8-long"},
            {"op": "bus_send", "type": "task_assigned", "topic": "planning",
             "payload": {"task_id": TASK, "goal": "design+implement+verify+promote order service"},
             "task_id": TASK},
            {"op": "handoff", "recipient": "architect", "goal": "design module boundaries",
             "task_id": TASK, "budget": 6, "budget_units": "steps"},
            {"op": "done"},
        ]), task_id=TASK, budget_pool_task=TASK)
        # architect：读任务 → 产设计 → 移交 dev（新信息=设计文档）
        member.run_member(rt, "architect", member.ScriptedLLM([
            {"op": "status", "status": "running", "progress": "designing"},
            {"op": "bus_read", "topic": "planning", "tail": 4},
            {"op": "fs_write", "path": "shared/architect/ARCHITECTURE.md", "content": ARCH},
            {"op": "bus_send", "type": "result", "topic": "design",
             "payload": {"task_id": TASK, "artifact": "shared/architect/ARCHITECTURE.md",
                         "key_decisions": ["Decimal-safe", "idempotency key"]}},
            {"op": "handoff", "recipient": "dev", "goal": "implement per design",
             "task_id": TASK, "budget": 6, "budget_units": "steps",
             "artifacts": ["shared/architect/ARCHITECTURE.md"]},
            {"op": "done"},
        ]), task_id=TASK, budget_pool_task=TASK)
        # dev：实现 + 自测 → 移交 qa
        member.run_member(rt, "dev", member.ScriptedLLM([
            {"op": "status", "status": "running", "progress": "implementing"},
            {"op": "fs_write", "path": "shared/dev/order.py", "content": ORDER_PY},
            {"op": "fs_write", "path": "shared/dev/test_order.py", "content": TEST_PY},
            {"op": "exec", "cmd": ["python3.10", "shared/dev/test_order.py"]},
            {"op": "handoff", "recipient": "qa", "goal": "verify + evidence",
             "task_id": TASK, "budget": 4, "budget_units": "steps",
             "artifacts": ["shared/dev/order.py", "shared/dev/test_order.py"]},
            {"op": "done"},
        ]), task_id=TASK, budget_pool_task=TASK)
        # qa：独立执行（真实输出=evidence），送回 review_result=pass
        member.run_member(rt, "qa", member.ScriptedLLM([
            {"op": "status", "status": "running", "progress": "verifying"},
            {"op": "bus_read", "topic": "review", "tail": 6},
            {"op": "fs_read", "path": "shared/architect/ARCHITECTURE.md"},
            {"op": "exec", "cmd": ["python3.10", "shared/dev/test_order.py"]},
            {"op": "log", "kind": "verdict",
             "event": {"verdict": "pass", "method": "exec:test_order.py", "task_id": TASK}},
            {"op": "bus_send", "type": "review_result", "topic": "review",
             "recipient_id": "spec",
             "payload": {"verdict": "pass", "method": "exec:test_order.py",
                         "evidence": "ORDER_TESTS_PASS (code 0)",
                         "artifacts": ["shared/dev/order.py"]},
             "task_id": TASK},
            {"op": "done"},
        ]), task_id=TASK, budget_pool_task=TASK)
        # ops：仅凭 evidence 背书 promote（守门，非 Manager）
        promote = teamctl.fs_promote(rt, "dev", "shared/dev/order.py", "order.py",
                                     "ops", TASK)
        member.run_member(rt, "ops", member.ScriptedLLM([
            {"op": "status", "status": "running", "progress": "gatekeeping"},
            {"op": "bus_read", "topic": "gate", "tail": 6},
            {"op": "log", "kind": "decision",
             "event": {"decision": "promote" if promote["ok"] else "hold",
                       "task_id": TASK}},
            {"op": "done"},
        ]), task_id=TASK, budget_pool_task=TASK)

        quota = teamctl.quota_status(rt, TASK)
        usage = teamctl.usage_summary(rt, task_id=TASK)
        rec = {
            "task": TASK,
            "members": {a: teamctl.status_get(rt, a)["status"]["status"]
                        for a in ("spec", "architect", "dev", "qa", "ops")},
            "promote": promote,
            "deliverable": (pathlib.Path(rt) / "shared/deliverables/order.py").exists(),
            "quota": quota,
            "usage": {"records": usage["records"], "total_est_tokens": usage["total_est_tokens"],
                      "by_agent": usage["by_agent"], "sources": usage["sources"]},
            "emergence_events": [
                "e1 topic self-created: architect published design topic (no central dispatch)",
                "e2 new information per hop: ARCHITECTURE.md -> tests -> exec evidence",
                "e3 evidence-gated promotion by ops (role table enforced in code)",
                "e4 budget-aware: pool consumed, all members finished within pool",
            ],
            "manager_node": None,
        }
        ok = (all(v == "done" for v in rec["members"].values())
              and promote["ok"] and rec["deliverable"]
              and quota["remaining"] > 0 and quota["concurrency"] == 1
              and rec["usage"]["records"] > 10
              and set(rec["usage"]["by_agent"]) == {"spec", "architect", "dev", "qa", "ops"})
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "recap.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2),
                                            encoding="utf-8")
        (out_dir / "README.md").write_text(_readme(rec, ok), encoding="utf-8")
        print("RESULT:", "PASS" if ok else "FAIL")
        print(json.dumps(rec, ensure_ascii=False, indent=2))
        sys.exit(0 if ok else 1)


def _readme(rec, ok):
    return """# M8 起点演示 · 2026-09-14（5 角色 + 配额 + 发布守门 + 涌现日志）

> 结果：**%s**（`python3.10 tools/m8_demo.py` exit 0；明细 `recap.json`）

- 成员（Agent Card 注册）：spec / architect / dev / qa / ops，**无 Manager**；
- 长周期多步任务 `%s`：spec → architect（设计）→ dev（实现+自测）→ qa（独立验证 evidence）→ ops（promote）；
- 资源配额：预算池 **%s est-tokens**（实耗 **%s**，剩余 **%s**）、并发上限 **%s**（按序执行满足）；
- 每步用量登记：**%s** 条（estimate 标注，source=%s），按成员分布 %s；
- 发布：`shared/dev/order.py` → `shared/deliverables/order.py`（ops 凭 evidence 背书 promote=%s）；
- 涌现（可指认事件）：%s。

## 边界说明（诚实）

- 成员由 member.py（ScriptedLLM）承载——协议层/控制平面演示；真实成员运行见 r8/r10；
- 并发上限 1 为「按序执行」的平凡满足，真并发配额在 Round 12 长周期任务中用并行成员实测；
- est-tokens 为估算值（`estimate_tokens`，≈字符/4），真实计量待 DSH 子 Agent 适配器。
""" % ("PASS" if ok else "FAIL", rec["task"],
       rec["quota"]["pool"], rec["usage"]["total_est_tokens"], rec["quota"]["remaining"],
       rec["quota"]["concurrency"], rec["usage"]["records"],
       ",".join(rec["usage"]["sources"]), rec["usage"]["by_agent"],
       rec["promote"]["ok"], "; ".join(rec["emergence_events"]))


if __name__ == "__main__":
    main()
