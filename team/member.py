#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
team/member.py — 成员运行时：ReAct 循环 + 上下文装配 + 协议工具节点（M1 内核参考实现）。

定位（重要）：
  - 真实成员将由 DSH 子 Agent 承载，操作手册见 docs/member-manual.md；
  - 本模块是可插拔 LLM 后端的 **协议一致性验证器**：证明「成员行为约定 + 协议层」
    能够自洽运行——上下文装配（渐进式披露）、工具边界（写权限）、handoff 约定、
    停止条件、状态机、轨迹记录，全部按《AI Agents in Depth》Ch1/Ch2/Ch10 设计。

仅依赖标准库 + 同目录 teamctl（协议层）。
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))

import teamctl  # noqa: E402


class ToolError(Exception):
    pass


# ---------------------------------------------------------------- 行动（Action）类型

OPS = ["status", "bus_send", "bus_read", "fs_write", "fs_read", "fs_list",
       "handoff", "lock", "log", "exec", "done", "fail"]


def _require(op, action, keys):
    for k in keys:
        if k not in action:
            raise ToolError("op %s requires '%s'" % (op, k))


# ---------------------------------------------------------------- LLM 后端接口

class LLMBackend:
    """接口：act(context) -> action(dict)。context 为只读装配结果。
    可选 implement estimate(context, action) -> int：由真实后端上报 token 用量
    （DSH 子 Agent 适配器可映射 tokenMeter）；缺省走协议层启发式估算（estimate 标注）。"""

    source_tag = "estimate"  # 计量来源：estimate | real:<adapter>（不冒充真实值）

    def act(self, context):  # pragma: no cover - 接口
        raise NotImplementedError

    def estimate(self, context, action):  # pragma: no cover - 可选
        raise NotImplementedError


class ScriptedLLM(LLMBackend):
    """确定性后端：按剧本依次弹出动作；用于测试/演示。"""

    def __init__(self, actions, name="scripted", est_tokens=None):
        self.actions = list(actions)
        self.name = name
        self.seen_contexts = []
        self.est_tokens = est_tokens  # 可选：每步固定估算（测试真实计量路径）

    def act(self, context):
        self.seen_contexts.append(context)
        if not self.actions:
            raise ToolError("%s: script exhausted (no more actions)" % self.name)
        return self.actions.pop(0)

    def estimate(self, context, action):
        if self.est_tokens is not None:
            return int(self.est_tokens)
        return teamctl.estimate_tokens(str(context) + str(action))


class OpenAICompatLLM(LLMBackend):
    """真实 LLM 后端：OpenAI 兼容 Chat Completions 协议（DeepSeek/vLLM/任一兼容端点）。

    - act(context)：系统提示词给出「动作空间 + 铁律」，返回单个 action JSON（剥除代码围栏）；
    - estimate：优先用响应中的 usage（prompt+completion，真实计量），失败则回退启发式估算；
    - source_tag = real:openai-compat（计量诚实标注，不冒充其他后端）。
    """

    source_tag = "real:openai-compat"

    ACTION_SCHEMA_HINT = (
        "你必须只输出一个 JSON 对象（不要代码围栏/解释），op ∈ "
        + "|".join(OPS)
        + "。常用字段：status/progress、type/topic/recipient/broadcast/payload/task_id、"
        "path/content、cmd、recipient/goal/budget/budget_units/artifacts、kind/event。"
    )

    def __init__(self, base_url, api_key, model, temperature=0.2, timeout=90):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.last_usage = None

    def _system_prompt(self):
        return (
            "你是多 Agent 去中心化团队的一名成员。团队无中心 Manager；"
            "你通过共享工作区（agents/<你>/ 私有、shared/<你>/ 命名空间）与消息总线协作；"
            "身份文件 agent-card.json 不可写；共享区写入先 lock 且冲突即停止；"
            "预算来自移交包（剩余预算<=0 时应 op=fail 或尽快 done）；"
            "任务单经 messages 主题分发；交付物经 qa/ops 证据门禁 promote。\n"
            + self.ACTION_SCHEMA_HINT
        )

    def act(self, context):
        body = {
            "model": self.model,
            "temperature": self.temperature,
            "messages": [
                {"role": "system", "content": self._system_prompt()},
                {"role": "user", "content": "context:\n"
                 + json.dumps(context, ensure_ascii=False, indent=2)
                 + "\n\n请依据 context 输出下一个 action JSON。"},
            ],
        }
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                resp = json.loads(r.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise ToolError("LLM endpoint unreachable: %s" % e)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            raise ToolError("LLM endpoint HTTP %s: %s" % (e.code, detail))
        try:
            content = resp["choices"][0]["message"]["content"]
            self.last_usage = resp.get("usage")
            content = content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            return json.loads(content)
        except (KeyError, IndexError, ValueError) as e:
            raise ToolError("LLM response not parseable: %s (content=%r)"
                            % (e, str(content)[:200] if "content" in locals() else ""))

    def estimate(self, context, action):
        if isinstance(self.last_usage, dict) and self.last_usage.get("total_tokens"):
            return int(self.last_usage["total_tokens"])
        return teamctl.estimate_tokens(str(context) + str(action))


# ---------------------------------------------------------------- 成员运行时

class MemberRuntime:
    def __init__(self, root, agent_id, llm, max_steps=8, task_id=None, budget_pool_task=None):
        self.root = pathlib.Path(root).resolve()
        self.agent_id = agent_id
        self.llm = llm
        self.max_steps = max_steps
        self.task_id = task_id
        self.budget_pool_task = budget_pool_task  # M8：预算池配额门（可选）
        self.p = teamctl.paths(root)
        self._last_seen_id = "<start>"
        self.history = []  # [(action, observation)]
        self.est_tokens_total = 0

    # ---------- 工具执行（= 成员可用的动作空间；硬边界在此，不依赖模型自觉） ----------

    def _resolve(self, path):
        p = (self.root / path).resolve()
        if not str(p).startswith(str(self.root)):
            raise ToolError("path escapes root: %s" % path)
        return p

    def _check_write(self, path):
        """写权限边界：私有 scratch 或 本成员共享命名空间；其余不可写。
        （对应全书「权限级差异走 Harness 门」，不靠提示词约束。）
        例外：身份文件 agent-card.json 不可写（角色/使命由运行时登记，成员不可自改）。"""
        p = self._resolve(path)
        allowed = [
            self.p["agents"] / self.agent_id,
            self.p["shared"] / self.agent_id,
        ]
        if not any(str(p).startswith(str(a)) for a in allowed):
            raise ToolError("write denied for %s (allowed: scratch / shared/%s/)" % (path, self.agent_id))
        if p.name == "agent-card.json":
            raise ToolError("write denied for identity file agent-card.json (role is registered by runtime)")
        return p

    def _execute(self, action):
        op = action.get("op")
        if op not in OPS:
            raise ToolError("unknown op: %r" % op)

        if op == "status":
            teamctl.status_set(self.root, self.agent_id, action["status"],
                               progress=action.get("progress"))
            return {"status": action["status"]}

        if op == "bus_send":
            _require(op, action, ["type"])
            env = teamctl.send(
                self.root, self.agent_id, action["type"],
                recipient_id=action.get("recipient"),
                topic=action.get("topic"),
                broadcast=bool(action.get("broadcast")),
                payload=action.get("payload") or {},
                task_id=action.get("task_id"),
                correlation_id=action.get("correlation"),
            )
            return {"envelope_id": env["id"], "routed_to": env.get("recipient_id") or env.get("topic") or "broadcast"}

        if op == "bus_read":
            msgs = teamctl.read(self.root, self.agent_id, topic=action.get("topic"), tail=action.get("tail"))
            return {"count": len(msgs), "messages": msgs[-3:]}

        if op == "fs_write":
            _require(op, action, ["path", "content"])
            p = self._check_write(action["path"])
            locked = False
            if str(p).startswith(str(self.p["shared"])):
                r = teamctl.lock_acquire(self.root, action["path"], self.agent_id)
                if not r["ok"]:
                    raise ToolError("concurrent write conflict: %s" % r["reason"])
                locked = True
            try:
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(action["content"], encoding="utf-8")
            finally:
                if locked:
                    teamctl.lock_release(self.root, action["path"], self.agent_id)
            return {"path": action["path"], "bytes": len(action["content"].encode("utf-8"))}

        if op == "fs_read":
            _require(op, action, ["path"])
            p = self._resolve(action["path"])
            if not p.exists():
                raise ToolError("not found: %s" % action["path"])
            return {"path": action["path"], "content": p.read_text(encoding="utf-8")[:4000]}

        if op == "fs_list":
            _require(op, action, ["path"])
            p = self._resolve(action["path"])
            entries = sorted(str(x.relative_to(self.root)) for x in p.iterdir()) if p.exists() else []
            return {"path": action["path"], "entries": entries[:50]}

        if op == "handoff":
            _require(op, action, ["recipient", "goal"])
            r = teamctl.handoff_new(
                self.root,
                task_id=action.get("task_id") or ("t-" + self.agent_id),
                sender_id=self.agent_id,
                recipient_id=action["recipient"],
                goal=action["goal"],
                budget=float(action.get("budget", 3)),
                constraints=action.get("constraints") or [],
                facts=action.get("facts") or [],
                artifact_refs=action.get("artifacts") or [],
                budget_units=action.get("budget_units", "steps"),
                visited=action.get("visited"),
            )
            return {"verdict": r["verdict"], "detail": r["detail"], "package": r["path"]}

        if op == "lock":
            _require(op, action, ["op2", "file"])
            if action["op2"] == "acquire":
                return teamctl.lock_acquire(self.root, action["file"], self.agent_id)
            if action["op2"] == "release":
                return teamctl.lock_release(self.root, action["file"], self.agent_id)
            raise ToolError("lock op2 must be acquire/release")

        if op == "log":
            _require(op, action, ["kind", "event"])
            return teamctl.log_append(self.root, self.agent_id, action["kind"],
                                      action["event"] if isinstance(action["event"], dict) else {"note": action["event"]})

        if op == "exec":
            """执行验证命令（qa 独立验证工具）：在成员工作区根目录运行，返回退出码与输出。
            只用于验证/测试执行；产物写入仍受 _check_write 门禁。"""
            _require(op, action, ["cmd"])
            cmd = action["cmd"]
            if not isinstance(cmd, list) or not cmd:
                raise ToolError("exec cmd must be a non-empty list")
            r = subprocess.run(
                [str(c) for c in cmd], cwd=str(self.root),
                capture_output=True, text=True,
                timeout=float(action.get("timeout", 60)),
            )
            return {"cmd": cmd, "code": r.returncode,
                    "stdout": r.stdout[-2000:], "stderr": r.stderr[-2000:]}

        if op == "done":
            teamctl.status_set(self.root, self.agent_id, "done",
                               progress=action.get("progress", "task complete"))
            return {"final": "done"}

        if op == "fail":
            teamctl.status_set(self.root, self.agent_id, "failed",
                               progress=action.get("progress", "failed"))
            return {"final": "failed"}

    # ---------- 上下文装配（渐进式披露：索引/轻量摘要，不灌全文） ----------

    def _context(self):
        card = teamctl._read_json(self.p["agents"] / self.agent_id / "agent-card.json", {})
        msgs = teamctl.read(self.root, self.agent_id, tail=8)
        skills_idx = []
        skills_dir = self.p["skills"]
        if skills_dir.exists():
            for d in sorted(skills_dir.iterdir()):
                if (d / "SKILL.md").exists():
                    skills_idx.append(d.name)
        logs_tail = teamctl.log_read(self.root, self.agent_id, tail=4)
        st = teamctl.status_get(self.root, self.agent_id)
        return {
            "identity": {"agent_id": card.get("agent_id"), "role": card.get("role"),
                         "capabilities": card.get("capabilities", [])},
            "status": st["status"].get("status"),
            "pending_messages": [{"type": m.get("type"), "sender": m.get("sender_id"),
                                  "payload": m.get("payload"), "task_id": m.get("task_id")} for m in msgs],
            "skills_index": skills_idx,
            "recent_log": logs_tail[-2:] if logs_tail else [],
            "budget_note": "预算由移交包携带；执行前先读 handoffs/ 目录最新包",
        }

    # ---------- ReAct 循环 ----------

    def _meter_step(self, context, action, step):
        """可插拔 token 计量：优先真实后端（LLMBackend.estimate 覆写），否则启发式估算；
        一律登记 usage.jsonl（source=estimate / real:<backend>），不冒充真实值。"""
        try:
            est = int(self.llm.estimate(context, action))
        except (NotImplementedError, AttributeError, TypeError):
            est = teamctl.estimate_tokens(str(context) + str(action))
        source = getattr(self.llm, "source_tag", None) or "estimate"
        rec = teamctl.usage_record(self.root, self.agent_id, step, est,
                                   source=source, op=action.get("op"), task_id=self.task_id)
        self.est_tokens_total += est
        self._last_est = est
        return rec

    def run(self):
        teamctl.status_set(self.root, self.agent_id, "running",
                           progress="member loop started")
        summary = {"agent_id": self.agent_id, "steps": 0, "final": None,
                   "observations": [], "est_tokens_total": 0}
        self._last_est = 0
        for step in range(1, self.max_steps + 1):
            if self.budget_pool_task:
                q = teamctl.quota_status(self.root, self.budget_pool_task)
                if q is not None and q["remaining"] <= 0:
                    teamctl.status_set(self.root, self.agent_id, "failed",
                                       progress="budget pool exhausted: stopping")
                    summary["final"] = "failed:quota"
                    return summary
            ctx = self._context()
            action = self.llm.act(ctx)
            if not isinstance(action, dict) or "op" not in action:
                raise ToolError("LLM returned invalid action: %r" % (action,))
            self._meter_step(ctx, action, step)
            observation = self._execute(action)
            self.history.append((action, observation))
            summary["steps"] += 1
            summary["observations"].append(observation)
            if self.task_id and self.budget_pool_task:
                teamctl.quota_consume(self.root, self.budget_pool_task, self._last_est)
            if observation.get("final") in ("done", "failed"):
                summary["final"] = observation["final"]
                summary["est_tokens_total"] = self.est_tokens_total
                return summary
        # 未在 max_steps 内到达终止条件 -> 显式失败（模拟生产中的超时兜底）
        teamctl.status_set(self.root, self.agent_id, "failed",
                           progress="max_steps exceeded: stopping")
        summary["final"] = "failed:max_steps"
        summary["est_tokens_total"] = self.est_tokens_total
        return summary


def run_member(root, agent_id, llm, max_steps=8, task_id=None, budget_pool_task=None):
    return MemberRuntime(root, agent_id, llm, max_steps=max_steps,
                         task_id=task_id, budget_pool_task=budget_pool_task).run()


def _cli():
    """S3：真实 LLM 成员命令行入口（OpenAI 兼容端点）。
    例：python3.10 team/member.py --root . --agent dev --task t1 --budget-pool t1 \
        --base-url https://api.deepseek.com/v1 --api-key $KEY --model deepseek-chat
    """
    import argparse
    ap = argparse.ArgumentParser(prog="member", description="成员运行时（真实 LLM 后端）")
    ap.add_argument("--root", default=None, help="工作区根目录")
    ap.add_argument("--agent", required=True)
    ap.add_argument("--task")
    ap.add_argument("--budget-pool")
    ap.add_argument("--max-steps", type=int, default=8)
    ap.add_argument("--base-url", required=True, help="OpenAI 兼容端点根（如 https://api.deepseek.com/v1）")
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--temperature", type=float, default=0.2)
    args = ap.parse_args()
    root = args.root or str(pathlib.Path(__file__).resolve().parent.parent)
    llm = OpenAICompatLLM(args.base_url, args.api_key, args.model, temperature=args.temperature)
    summary = run_member(root, args.agent, llm, max_steps=args.max_steps,
                         task_id=args.task, budget_pool_task=args.budget_pool)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("final") == "done" else 1


if __name__ == "__main__":
    sys.exit(_cli())
