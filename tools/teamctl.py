#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
teamctl — 多 Agent 去中心化团队的协议层参考实现（控制平面 + 数据平面）。

依据《AI Agents in Depth》第 10 章：
  - 消息信封（总线/点对点）：统一信封 -> 可靠路由、可追溯
  - Handoff 移交包（去中心化模式）：visited_agents 环检测、remaining_budget 预算衰减、
    accepted_facts / artifact_refs（接口清晰：传引用不传全文）
  - 虚拟文件系统四区域：scratch(私有) / shared(共享) / skills(内置只读) / mounts(外部)
  - 乐观锁：共享区并发冲突防护（同一文件版本号 CAS）
  - 轨迹持久化：system/logs/<agent>.jsonl（JSONL 追加，只增不改）

仅依赖 Python 标准库。主命令入口见 __main__。
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import pathlib

# ---------------------------------------------------------------- 常量与路径

ENVELOPE_TYPES = [
    "task_assigned", "status_update", "result", "info_collected",
    "review_request", "review_result", "terminate", "terminate_ack",
    "query", "error", "note",
]

AGENT_STATUS = ["idle", "running", "needs_input", "done", "failed"]

BUDGET_UNITS = ["steps", "tokens", "calls"]


def paths(root):
    root = pathlib.Path(root).resolve()
    return {
        "root": root,
        "agents": root / "agents",
        "shared": root / "shared",
        "skills": root / "skills",
        "messages": root / "system" / "messages",
        "state": root / "system" / "state",
        "logs": root / "system" / "logs",
        "locks": root / "system" / "state" / "locks",
        "handoffs": root / "system" / "state" / "handoffs",
        "tasks": root / "system" / "state" / "tasks.json",
        "conflicts": root / "system" / "state" / "conflicts",
        "usage": root / "system" / "state" / "usage.jsonl",
        "quotas": root / "system" / "state" / "quotas.json",
    }


def ensure(root):
    p = paths(root)
    for d in (p["agents"], p["shared"], p["skills"], p["messages"],
              p["state"], p["logs"], p["handoffs"], p["conflicts"]):
        d.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------- 轻量 Schema 校验

class SchemaError(ValueError):
    pass


def _type_ok(value, t):
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    if t == "string":
        return isinstance(value, str)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if t == "boolean":
        return isinstance(value, bool)
    return True


def validate_schema(obj, schema, where="<root>"):
    """对本书自有的三种协议 Schema 做最小化校验（required/type/enum/const/
    minimum/pattern/items/anyOf/not）。够用且零依赖。"""
    if "required" in schema:
        for k in schema["required"]:
            if k not in obj:
                raise SchemaError("%s: missing required field '%s'" % (where, k))
    for k, subs in schema.get("properties", {}).items():
        if k not in obj:
            continue
        validate_schema(obj[k], subs, "%s.%s" % (where, k))
    if "type" in schema and not _type_ok(obj, schema["type"]):
        raise SchemaError("%s: expected type %s, got %s" % (where, schema["type"], type(obj).__name__))
    if "enum" in schema and obj not in schema["enum"]:
        raise SchemaError("%s: value %r not in enum %s" % (where, obj, schema["enum"]))
    if "const" in schema and obj != schema["const"]:
        raise SchemaError("%s: expected const %r" % (where, schema["const"]))
    if isinstance(obj, (int, float)) and not isinstance(obj, bool):
        if "minimum" in schema and obj < schema["minimum"]:
            raise SchemaError("%s: %r < minimum %r" % (where, obj, schema["minimum"]))
    if "pattern" in schema and isinstance(obj, str) and not re.match(schema["pattern"], obj):
        raise SchemaError("%s: %r does not match pattern" % (where, obj))
    if isinstance(obj, list) and "items" in schema:
        for i, item in enumerate(obj):
            validate_schema(item, schema["items"], "%s[%d]" % (where, i))
    if "anyOf" in schema:
        ok = False
        errors = []
        for i, subs in enumerate(schema["anyOf"]):
            try:
                validate_schema(obj, subs, "%s.anyOf[%d]" % (where, i))
                ok = True
                break
            except SchemaError as e:
                errors.append(str(e))
        if not ok:
            raise SchemaError("%s: no anyOf branch matched (%s)" % (where, "; ".join(errors)))
    if "not" in schema:
        matched = False
        try:
            validate_schema(obj, schema["not"], where)
            matched = True
        except SchemaError:
            pass
        if matched:
            raise SchemaError("%s: must not match 'not' schema" % where)
    return True


def load_schema(name):
    here = pathlib.Path(__file__).resolve().parent.parent / "docs" / "protocols"
    with open(here / name, encoding="utf-8") as f:
        return json.load(f)


def validate_envelope(env):
    return validate_schema(env, load_schema("message-envelope.schema.json"))


def validate_handoff(h):
    return validate_schema(h, load_schema("handoff.schema.json"))


def validate_card(card):
    return validate_schema(card, load_schema("agent-card.schema.json"))


# ---------------------------------------------------------------- 通用工具

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def new_id():
    return uuid.uuid4().hex[:16]


def _write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _read_json(path, default=None):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _read_jsonl(path):
    if not path.exists():
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _append_jsonl(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- Agent 注册（Agent Card）

def agent_new(root, agent_id, name=None, role=None, description=None,
              capabilities=None, tools=None, skills=None, subscriptions=None,
              modalities=None):
    p = ensure(root)
    if not re.match(r"^[a-z][a-z0-9-]*$", agent_id):
        raise SchemaError("agent_id must match [a-z][a-z0-9-]*")
    card = {
        "card_version": 1,
        "agent_id": agent_id,
        "name": name or agent_id,
        "role": role or "general",
        "description": description or "",
        "capabilities": capabilities or [],
        "input_modalities": modalities or ["text", "file"],
        "output_modalities": modalities or ["text", "file"],
        "tools": tools or [],
        "skills": skills or [],
        "subscriptions": subscriptions or [],
        "workspace": "agents/%s/" % agent_id,
        "created_at": now(),
        "updated_at": now(),
    }
    validate_card(card)
    scratch = p["agents"] / agent_id / "scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    _write_json(p["agents"] / agent_id / "agent-card.json", card)
    _write_json(p["agents"] / agent_id / "status.json",
                {"agent_id": agent_id, "status": "idle", "updated_at": now()})
    (p["agents"] / agent_id / "progress.md").touch(exist_ok=True)
    return card


def agent_list(root):
    p = ensure(root)
    out = []
    for d in sorted((p["agents"]).glob("*/agent-card.json")):
        out.append(_read_json(d))
    return out


def agent_subscribe(root, agent_id, topic, event_types=None):
    """为成员追加主题订阅（幂等：同主题合并 event_types，空=全部类型）。"""
    p = ensure(root)
    cp = p["agents"] / agent_id / "agent-card.json"
    card = _read_json(cp, {})
    if not card.get("agent_id"):
        raise SchemaError("no such agent %r" % agent_id)
    subs = card.setdefault("subscriptions", [])
    for s in subs:
        if s.get("topic") == topic:
            if event_types:
                s.setdefault("event_types", [])
                for t in event_types:
                    if t not in s["event_types"]:
                        s["event_types"].append(t)
            break
    else:
        subs.append({"topic": topic, "event_types": event_types or []})
    card["updated_at"] = now()
    validate_card(card)
    _write_json(cp, card)
    return card


# ---------------------------------------------------------------- 消息总线（控制平面）

def send(root, sender_id, msg_type, recipient_id=None, topic=None, broadcast=False,
         payload=None, task_id=None, correlation_id=None, id_=None):
    p = ensure(root)
    env = {
        "envelope_version": 1,
        "id": id_ or new_id(),
        "ts": now(),
        "sender_id": sender_id,
        "type": msg_type,
        "payload": payload or {},
    }
    if recipient_id:
        env["recipient_id"] = recipient_id
    if topic:
        env["topic"] = topic
    if broadcast:
        env["broadcast"] = True
    if task_id:
        env["task_id"] = task_id
    if correlation_id:
        env["correlation_id"] = correlation_id
    validate_envelope(env)
    # 路由：点对点一律落入 direct 主题；广播落入 broadcast 主题；其余按 topic
    bus_topic = topic or ("broadcast" if broadcast else "direct")
    _append_jsonl(p["messages"] / (bus_topic + ".jsonl"), env)
    return env


def read(root, agent_id, topic=None, tail=None, after_id=None):
    """读取该 Agent 可见的消息：点对点收件 / 广播 / 订阅主题（含事件类型过滤）。"""
    p = ensure(root)
    card = _read_json(p["agents"] / agent_id / "agent-card.json", {})
    subs = {s["topic"]: set(s.get("event_types", [])) for s in card.get("subscriptions", [])}
    rows = []
    for f in sorted(p["messages"].glob("*.jsonl")):
        for m in _read_jsonl(f):
            if after_id and m.get("id") == after_id:
                after_id = None
                continue
            if topic and m.get("topic") != topic and not (m.get("recipient_id") == agent_id):
                continue
            recipient = m.get("recipient_id")
            if recipient and recipient != agent_id:
                continue
            if m.get("broadcast") is True:
                rows.append(m)
                continue
            mtopic = m.get("topic")
            if mtopic in subs:
                types = subs[mtopic]
                if not types or m.get("type") in types:
                    rows.append(m)
                    continue
            if recipient == agent_id:
                rows.append(m)
    rows.sort(key=lambda m: m.get("ts", ""))
    if tail:
        rows = rows[-tail:]
    return rows


# ---------------------------------------------------------------- 状态（进度文件 + 状态机）

def status_set(root, agent_id, status, progress=None):
    p = ensure(root)
    if status not in AGENT_STATUS:
        raise SchemaError("status must be one of %s" % AGENT_STATUS)
    path = p["agents"] / agent_id / "status.json"
    st = _read_json(path, {"agent_id": agent_id})
    st.update({"agent_id": agent_id, "status": status, "updated_at": now()})
    _write_json(path, st)
    if progress is not None:
        with open(p["agents"] / agent_id / "progress.md", "a", encoding="utf-8") as f:
            f.write("- %s [%s] %s\n" % (now(), status, progress))
    return st


def status_get(root, agent_id):
    p = ensure(root)
    st = _read_json(p["agents"] / agent_id / "status.json")
    prog = p["agents"] / agent_id / "progress.md"
    return {"status": st, "progress_tail": prog.read_text(encoding="utf-8").strip().splitlines()[-5:] if prog.exists() else []}


# ---------------------------------------------------------------- Handoff（去中心化移交）

def check_handoff(h):
    """纯函数：返回 (verdict, detail)。
    verdict ∈ ok | cycle | exhausted；不允许任一 Agent 自行删除预算/访问链。"""
    validate_handoff(h)
    if h["recipient_id"] in h["visited_agents"]:
        return ("cycle", "recipient %s already visited" % h["recipient_id"])
    if h["remaining_budget"] <= 0:
        return ("exhausted", "remaining_budget <= 0: stop_and_escalate")
    return ("ok", "")


def split_visited(s):
    """解析 --visited：None/空串 => None（= 继承任务注册表访问链；铁律 3：成员不得重置）。
    显式逗号列表 => 列表（仅任务创建者/运行时使用）。"""
    if s is None:
        return None
    s = s.strip()
    if not s:
        return None
    return [a.strip() for a in s.split(",") if a.strip()]


def handoff_new(root, task_id, sender_id, recipient_id, goal, budget,
                constraints=None, facts=None, artifact_refs=None,
                budget_units="steps", visited=None, record=True):
    p = ensure(root)
    h = {
        "handoff_version": 1,
        "task_id": task_id,
        "sender_id": sender_id,
        "recipient_id": recipient_id,
        "goal": goal,
        "constraints": constraints or [],
        "accepted_facts": facts or [],
        "artifact_refs": artifact_refs or [],
        "remaining_budget": budget,
        "budget_units": budget_units,
        "visited_agents": list(visited) if visited is not None
        else list(_read_json(p["tasks"], {}).get(task_id, {}).get("visited", [])),
        "created_at": now(),
    }
    verdict, detail = check_handoff(h)
    path = p["handoffs"] / ("%s-%s.json" % (task_id, new_id()))
    _write_json(path, h)
    if record and verdict == "ok":
        tasks = _read_json(p["tasks"], {})
        t = tasks.setdefault(task_id, {"task_id": task_id, "goal": goal, "visited": [], "updated_at": now()})
        t["visited"] = list(h["visited_agents"]) + [recipient_id]
        t["updated_at"] = now()
        _write_json(p["tasks"], tasks)
    return {"handoff": h, "verdict": verdict, "detail": detail, "path": str(path)}


# ---------------------------------------------------------------- 乐观锁（共享区并发防护）

def _lock_path(p, file_path):
    key = hashlib.sha256(str(file_path).encode("utf-8")).hexdigest()[:32]
    return p["locks"] / (key + ".json")


def lock_acquire(root, file_path, agent_id):
    p = ensure(root)
    lp = _lock_path(p, file_path)
    cur = _read_json(lp)
    if cur and cur.get("locked_by"):
        return {"ok": False, "reason": "already locked by %s (version %s)" % (cur.get("locked_by"), cur.get("version"))}
    rec = {"file": str(file_path), "version": (cur or {}).get("version", 0) + 1,
           "locked_by": agent_id, "ts": now()}
    _write_json(lp, rec)
    return {"ok": True, "lock": rec}


def lock_release(root, file_path, agent_id=None):
    p = ensure(root)
    lp = _lock_path(p, file_path)
    cur = _read_json(lp)
    if not cur:
        return {"ok": False, "reason": "no lock"}
    if agent_id and cur.get("locked_by") != agent_id:
        return {"ok": False, "reason": "owned by %s" % cur.get("locked_by")}
    _write_json(lp, {"file": cur["file"], "version": cur["version"], "locked_by": None, "ts": now()})
    return {"ok": True, "version": cur["version"]}


def lock_status(root, file_path):
    p = ensure(root)
    return _read_json(_lock_path(p, file_path))


# ---------------------------------------------------------------- 轨迹持久化（只增不改）

def log_append(root, agent_id, kind, event):
    p = ensure(root)
    if kind not in ("step", "tool", "decision", "message", "verdict"):
        raise SchemaError("kind must be step/tool/decision/message/verdict")
    rec = {"ts": now(), "agent_id": agent_id, "kind": kind, "event": event}
    _append_jsonl(p["logs"] / (agent_id + ".jsonl"), rec)
    return rec


def log_read(root, agent_id, tail=None):
    p = ensure(root)
    rows = _read_jsonl(p["logs"] / (agent_id + ".jsonl"))
    return rows[-tail:] if tail else rows


# ---------------------------------------------------------------- 任务注册表（ops 视图）

def task_list(root):
    p = ensure(root)
    tasks = _read_json(p["tasks"], {})
    rows = [{"task_id": t["task_id"], "goal": t.get("goal", ""),
             "visited": t.get("visited", []), "updated_at": t.get("updated_at", "")}
            for t in tasks.values()]
    rows.sort(key=lambda r: r["updated_at"])
    return rows


def task_show(root, task_id):
    p = ensure(root)
    tasks = _read_json(p["tasks"], {})
    if task_id not in tasks:
        return None
    t = tasks[task_id]
    hs = [{"path": str(f), "sender": h.get("sender_id"), "recipient": h.get("recipient_id"),
           "goal": h.get("goal", ""), "visited": h.get("visited_agents", []),
           "remaining_budget": h.get("remaining_budget"),
           "created_at": h.get("created_at", "")}
          for f in p["handoffs"].glob("*%s*.json" % task_id)
          for h in [_read_json(f, {})] if h.get("task_id") == task_id]
    hs.sort(key=lambda h: h["created_at"])
    return {"task_id": t["task_id"], "goal": t.get("goal", ""), "visited": t.get("visited", []),
            "updated_at": t.get("updated_at", ""), "handoffs": hs}


# ---------------------------------------------------------------- 受锁文件写入（M7：锁纪律工具化）

def mission_init(root, mission, title, roles, revision=1):
    """使命登记（可信根 one-liner：与 roles.md 配套的机器可读版本）。
    只有运行时/使命所有者调用；成员写范围无法触达 system/state/（见 _check_fs_scope），
    audit.card_role_known 以本文件为角色白名单 —— mission 换挡 = revision+1。"""
    p = ensure(root)
    if not isinstance(roles, list) or not roles:
        raise SchemaError("roles must be a non-empty list")
    reg = {"mission": mission, "title": title, "roles": list(roles),
           "revision": int(revision), "frozen_at": now()}
    _write_json(p["quotas"].parent / "mission.json", reg)
    return reg


def mission_get(root):
    return _read_json(ensure(root)["quotas"].parent / "mission.json")


def _check_fs_scope(root, agent_id, path):
    """与 team/member.py 同语义的写范围硬边界：agents/<id>/ 或 shared/<id>/。
    例外（可信根）：身份文件 agent-card.json 任何成员都不可写（角色/能力/订阅由运行时登记）。"""
    p = pathlib.Path(root).resolve()
    target = (p / path).resolve()
    if not str(target).startswith(str(p)):
        raise SchemaError("path escapes root: %s" % path)
    allowed = [p / "agents" / agent_id, p / "shared" / agent_id]
    if not any(str(target).startswith(str(a)) for a in allowed):
        raise SchemaError("write denied for %s (allowed: agents/%s/ or shared/%s/)" % (path, agent_id, agent_id))
    if target.name == "agent-card.json":
        raise SchemaError("write denied for identity file agent-card.json (mission/role is registered by runtime)")
    return target


def fs_write(root, agent_id, path, content):
    """共享区受锁写入：范围检查 → lock acquire（失败则不写）→ 写 → release。
    返回 {ok,...}；锁冲突时返回 {ok:False, reason}（不落盘）。"""
    _check_fs_scope(root, agent_id, path)
    lr = lock_acquire(root, path, agent_id)
    if not lr["ok"]:
        return lr
    try:
        target = pathlib.Path(root).resolve() / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    finally:
        lock_release(root, path, agent_id)
    return {"ok": True, "path": path, "lock_version": lr["lock"]["version"]}


def fs_read(root, path):
    p = pathlib.Path(root).resolve()
    target = (p / path).resolve()
    if not str(target).startswith(str(p)):
        raise SchemaError("path escapes root: %s" % path)
    return {"path": path, "content": target.read_text(encoding="utf-8"), "exists": target.exists()}


# ---------------------------------------------------------------- Token 计量（可插拔账务层）
#
# 诚实边界：本团队参考运行时（member.py）使用确定性 ScriptedLLM，不产生真实 LLM token。
# DSH 侧确有 tokenMeter 服务（measure(session)/estimateMessage），但它面向 DSH Session 对象、
# 只能由 Host 内插件调用，Python 协议层无法接入；因此此处实现「单位一致、来源可标注」的
# 可插拔计量器：任何后端（ScriptedLLM / 未来 DSH 子 Agent 适配器）按统一接口登记用量，
# source 标注为 estimate / real:<adapter>，绝不冒充真实 token。

def estimate_tokens(text):
    """启发式估算：ASCII 约 4 字符/token（保守取 max(1, len//4)）。仅用于预算会计，非真实用量。"""
    if not text:
        return 0
    return max(1, len(str(text)) // 4)


def usage_record(root, agent_id, step, est_tokens, source="estimate",
                 op=None, task_id=None, meta=None):
    """按步登记 token 用量（JSONL 追加，只增不改）。source ∈ estimate | real:<adapter>。"""
    p = ensure(root)
    rec = {
        "ts": now(),
        "agent_id": agent_id,
        "step": step,
        "est_tokens": int(est_tokens),
        "source": source,
        "op": op or None,
        "task_id": task_id,
    }
    if meta:
        rec["meta"] = meta
    _append_jsonl(p["usage"], rec)
    return rec


def usage_summary(root, task_id=None, agent_id=None):
    """汇总：总估算量与按成员分布（供 cost.json / D8 取证；为估算值，source 标注可查）。"""
    p = ensure(root)
    rows = _read_jsonl(p["usage"])
    if task_id:
        rows = [r for r in rows if r.get("task_id") == task_id]
    if agent_id:
        rows = [r for r in rows if r.get("agent_id") == agent_id]
    by_agent = {}
    for r in rows:
        a = r.get("agent_id", "?")
        by_agent[a] = by_agent.get(a, 0) + int(r.get("est_tokens", 0))
    return {
        "records": len(rows),
        "total_est_tokens": sum(int(r.get("est_tokens", 0)) for r in rows),
        "by_agent": by_agent,
        "sources": sorted({r.get("source") for r in rows}),
        "tail": rows[-5:],
    }


# ---------------------------------------------------------------- 资源配额（M8：预算池 + 并发上限）

def quota_init(root, task_id, budget_units, pool, concurrency=None):
    """为任务初始化资源配额（预算池）。pool=总预算（按 budget_units 计量）；并发上限可选。"""
    p = ensure(root)
    quotas = _read_json(p["quotas"], {})
    q = quotas.setdefault(task_id, {"task_id": task_id, "updated_at": now()})
    q.update({"budget_units": budget_units, "pool": float(pool),
              "spent": float(q.get("spent", 0)), "updated_at": now()})
    if concurrency is not None:
        q["concurrency"] = int(concurrency)
    _write_json(p["quotas"], quotas)
    return q


def quota_consume(root, task_id, amount):
    """消费预算池（单进程读改写；多进程由乐观锁/运行时串行化，M8 长周期任务由驱动方串行调用）。
    返回 {ok, remaining, spent, pool}；amount<=0 时拒绝。"""
    p = ensure(root)
    quotas = _read_json(p["quotas"], {})
    q = quotas.get(task_id)
    if q is None:
        raise SchemaError("no quota for task %r" % task_id)
    amount = float(amount)
    if amount <= 0:
        return {"ok": False, "reason": "amount must be > 0"}
    q["spent"] = float(q.get("spent", 0)) + amount
    q["updated_at"] = now()
    _write_json(p["quotas"], quotas)
    return {"ok": True, "spent": q["spent"], "pool": q["pool"],
            "remaining": max(0.0, q["pool"] - q["spent"])}


def quota_status(root, task_id):
    p = ensure(root)
    q = _read_json(p["quotas"], {}).get(task_id)
    if q is None:
        return None
    return {"task_id": q["task_id"], "budget_units": q.get("budget_units"),
            "pool": q.get("pool"), "spent": q.get("spent", 0),
            "remaining": max(0.0, q.get("pool", 0) - q.get("spent", 0)),
            "concurrency": q.get("concurrency"), "updated_at": q.get("updated_at")}


# ---------------------------------------------------------------- 网页快照（S0：只读聚合，零副作用）
#
# web_snapshot 是「网页控制台」的唯一只读数据契约：仪表盘只消费本函数输出；
# 它不写任何文件（审计/探针也以只读方式调用），保证网页只是协议层的调用面。

def _jsonl_tail_by_topic(p, limit):
    out = []
    for f in sorted(p["messages"].glob("*.jsonl")):
        rows = _read_jsonl(f)
        for m in rows[-limit:]:
            out.append({"topic": f.stem, "id": m.get("id"), "ts": m.get("ts"),
                        "sender_id": m.get("sender_id"), "type": m.get("type"),
                        "recipient_id": m.get("recipient_id"),
                        "task_id": m.get("task_id"),
                        "broadcast": m.get("broadcast", False),
                        "payload": m.get("payload", {})})
    out.sort(key=lambda m: (m.get("ts", ""), m.get("id", "")))
    return out[-50:]


def _audit_report(root):
    """只读调用 tools/audit.py 的 audit()；模块名注册进 sys.modules 避免重复加载。
    audit.py 自己会 import teamctl —— 在本模块作为 __main__（CLI）或作为模块（测试）运行时均兼容。"""
    import importlib.util
    import sys as _sys
    mod_name = "teamctl_audit_lazy"
    mod = _sys.modules.get(mod_name)
    if mod is None:
        here = pathlib.Path(__file__).resolve().parent
        spec = importlib.util.spec_from_file_location(mod_name, str(here / "audit.py"))
        mod = importlib.util.module_from_spec(spec)
        _sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
    return mod.audit(root)


def web_snapshot(root, message_tail=10, log_tail=5):
    """只读聚合快照：成员/任务/消息/移交/配额/用量/冲突/审计/使命/评测/交付物。

    - 只做读操作；审计通过 audit.audit()（亦是只读）计算。
    - 返回结构为 JSON 序列化对象（无 pathlib/内部对象），可直接 HTTP 输出。
    """
    p = ensure(root)
    agents = []
    for card in agent_list(root):
        aid = card.get("agent_id")
        st = status_get(root, aid) if aid else {"status": {}, "progress_tail": []}
        us = usage_summary(root, agent_id=aid)
        agents.append({
            "agent_id": aid, "name": card.get("name"), "role": card.get("role"),
            "description": card.get("description"),
            "tools": card.get("tools", []), "skills": card.get("skills", []),
            "subscriptions": card.get("subscriptions", []),
            "status": st["status"].get("status"), "updated_at": st["status"].get("updated_at"),
            "progress_tail": st["progress_tail"],
            "usage_total_tokens": us["total_est_tokens"], "usage_records": us["records"],
        })
    tasks = []
    for t in task_list(root):
        q = quota_status(root, t["task_id"])
        hs = [h for h in (task_show(root, t["task_id"]) or {}).get("handoffs", [])]
        tasks.append({"task_id": t["task_id"], "goal": t["goal"], "visited": t["visited"],
                      "updated_at": t["updated_at"], "quota": q, "handoff_count": len(hs),
                      "handoffs": hs[-3:]})
    handoffs = []
    for f in sorted(p["handoffs"].glob("*.json"), key=lambda x: x.stat().st_mtime)[-10:]:
        h = _read_json(f, {})
        handoffs.append({"file": f.name, "task_id": h.get("task_id"),
                         "sender_id": h.get("sender_id"), "recipient_id": h.get("recipient_id"),
                         "goal": h.get("goal", ""), "visited_agents": h.get("visited_agents", []),
                         "remaining_budget": h.get("remaining_budget"),
                         "budget_units": h.get("budget_units"), "created_at": h.get("created_at")})
    handoffs.reverse()
    conflicts = []
    conflicts_dir = p["state"] / "conflicts"
    if conflicts_dir.exists():
        for f in sorted(conflicts_dir.iterdir()):
            if f.is_file():
                conflicts.append(f.name)
    eval_runs = []
    evdir = p["root"] / "eval" / "run"
    if evdir.exists():
        for d in sorted(evdir.iterdir()):
            if d.is_dir():
                readme = d / "README.md"
                first_line = ""
                if readme.exists():
                    with open(readme, encoding="utf-8") as fh:
                        first_line = fh.readline().strip()
                eval_runs.append({"name": d.name, "summary": first_line, "mtime": d.stat().st_mtime})
    deliverables = []
    dd = p["root"] / "shared" / "deliverables"
    if dd.exists():
        for f in sorted(dd.rglob("*")):
            if f.is_file():
                deliverables.append(str(f.relative_to(p["root"])))
    logs = {}
    for f in sorted(p["logs"].glob("*.jsonl")):
        rows = _read_jsonl(f)
        logs[f.stem] = rows[-log_tail:]
    return {
        "generated_at": now(),
        "root": str(p["root"]),
        "mission": mission_get(root),
        "mission_history": _mission_history(root),
        "agents": agents,
        "tasks": tasks,
        "messages": _jsonl_tail_by_topic(p, message_tail),
        "handoffs": handoffs,
        "conflicts": conflicts,
        "usage": usage_summary(root),
        "quotas": {t["task_id"]: t["quota"] for t in tasks if t["quota"]},
        "logs": logs,
        "audit": _audit_report(root),
        "eval_runs": eval_runs,
        "deliverables": deliverables,
    }


# ---------------------------------------------------------------- 网页命令层（S1：人类操作员的受控调用面）
#
# web_cmd 是网页「控制按钮」的唯一入口：动作白名单 + 参数校验 + 复用既有协议函数。
# 所有写操作仍受协议层约束（_check_fs_scope / evidence 门禁 / 锁 / 状态机），
# 浏览器永不直接触碰文件系统。

def task_register(root, task_id, goal, by=None):
    """任务注册表登记（ops 视图）：任务由运行时/操作员建立，成员按需协作。"""
    p = ensure(root)
    tasks = _read_json(p["tasks"], {})
    if task_id in tasks:
        return {"ok": False, "reason": "task %r already registered" % task_id}
    tasks[task_id] = {"task_id": task_id, "goal": goal, "visited": [],
                      "updated_at": now(), "created_by": by}
    _write_json(p["tasks"], tasks)
    return {"ok": True, "task_id": task_id, "goal": goal}


def _run_probe(root):
    """运行安全探针（tools/probe_safety.py；探针自带临时工作区，仅临时目录可写）。
    root 参数保留为占位（当前探针为确定性自包含，不依赖工作区）。"""
    here = pathlib.Path(__file__).resolve().parent
    try:
        cp = subprocess.run([sys.executable, str(here / "probe_safety.py")],
                            capture_output=True, text=True, timeout=180)
        tail = (cp.stdout or "").splitlines()[-6:]
        return {"ok": cp.returncode == 0, "exit_code": cp.returncode,
                "tail": tail, "cmd": "probe_safety"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "exit_code": None, "tail": ["probe error: %s: %s" % (type(e).__name__, e)]}


def _run_demo(root):
    """S2：网页发起完整任务 —— 运行 m8_demo（5 角色 spec→architect→dev→qa→ops 全链）。
    演示在临时工作区完成，证据（recap.json/README.md）写入 eval/run/（仓库内只增不改）。"""
    here = pathlib.Path(__file__).resolve().parent
    p = ensure(root)
    stamp = now().replace(":", "").replace("+", "-")[:19]
    n = 0
    while True:
        n += 1
        cand = p["root"] / "eval" / "run" / ("%s-web-demo-%02d" % (stamp[:10], n))
        if not cand.exists():
            break
    try:
        cp = subprocess.run([sys.executable, str(here / "m8_demo.py"), str(cand)],
                            capture_output=True, text=True, timeout=300)
        ok = cp.returncode == 0
        return {"ok": ok, "exit_code": cp.returncode, "out_dir": str(cand),
                "tail": (cp.stdout or "").splitlines()[-8:],
                "stderr_tail": (cp.stderr or "").splitlines()[-3:]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "exit_code": None, "out_dir": str(cand),
                "tail": ["demo error: %s: %s" % (type(e).__name__, e)]}


def _member_mod():
    """延迟加载 team/member.py（复用已加载模块；member.py 自己会导入 teamctl）。"""
    import importlib.util
    mod_name = "teamctl_member_lazy"
    mod = sys.modules.get(mod_name)
    if mod is None:
        here = pathlib.Path(__file__).resolve().parent.parent
        spec = importlib.util.spec_from_file_location(mod_name, str(here / "team" / "member.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
    return mod


def _run_llm_member(root, params):
    """S3：以 OpenAI 兼容后端运行一个真实成员（同步执行；调用方（teamd）用作业线程包住）。"""
    mm = _member_mod()
    agent = params.get("agent")
    if not agent or not params.get("base_url") or not params.get("model"):
        raise ValueError("run_llm needs agent/base_url/model (api_key optional for local endpoints)")
    llm = mm.OpenAICompatLLM(params["base_url"], params.get("api_key", ""), params["model"],
                             temperature=float(params.get("temperature", 0.2)))
    summary = mm.run_member(root, agent, llm,
                            max_steps=int(params.get("max_steps", 8)),
                            task_id=params.get("task"),
                            budget_pool_task=params.get("budget_pool"))
    return {"summary": summary, "backend": llm.source_tag}


def _mission_history(root):
    p = ensure(root)
    return _read_jsonl(p["quotas"].parent / "mission-history.jsonl")[-10:]


def mission_switch_dry(root, params):
    """使命换挡·沙盒演练（roles.md 规程第 2–3 步在沙盒执行）：
    当前工作区拷贝上登记 v(N+1) + 审计；不接触真实工作区任何文件。"""
    cur = mission_get(root) or {}
    mission = params.get("mission", cur.get("mission", "A"))
    title = params.get("title", "")
    roles = params.get("roles") or []
    if not roles:
        raise ValueError("mission_switch_dry needs roles (comma list or list)")
    rev = int(cur.get("revision", 0)) + 1
    with tempfile.TemporaryDirectory() as tmpdir:
        sandbox = pathlib.Path(tmpdir) / "ws"
        shutil.copytree(pathlib.Path(root).resolve(), sandbox,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git",
                                                      "eval", "node_modules"))
        reg = mission_init(str(sandbox), mission, title, roles, revision=rev)
        rep = _audit_report(str(sandbox))
    return {"suggested_revision": rev, "mission": reg, "audit": rep}


def mission_apply(root, params):
    """人工确认后执行换挡（信任锚点=人）：registry revision+1 → 历史 JSONL（只增）→ roles.md 追加版本章节。
    成员卡片不自动迁移（audit.card_role_known 给出结果，需按规程换卡后重新审计）。"""
    p = ensure(root)
    cur = mission_get(root) or {}
    mission = params.get("mission", cur.get("mission", "A"))
    title = params.get("title", cur.get("title", ""))
    roles = params.get("roles") or []
    if not roles:
        raise ValueError("mission_apply needs roles")
    rev = int(cur.get("revision", 1)) + 1
    reg = mission_init(root, mission, title, roles, revision=rev)
    _append_jsonl(p["quotas"].parent / "mission-history.jsonl",
                  {"ts": now(), "revision": rev, "mission": mission, "title": title,
                   "roles": list(roles), "applied_by": params.get("by", "operator")})
    md = p["root"] / "docs" / "roles.md"
    if not md.exists():
        md.parent.mkdir(parents=True, exist_ok=True)
        md.write_text("# 角色（roles.md）\n\n（由 teamd mission_apply 首次生成）\n", encoding="utf-8")
    with open(md, "a", encoding="utf-8") as f:
        f.write("\n\n## 使命变更 %s（web 换挡，rev %d）\n\n" % (now()[:10], rev))
        f.write("- mission: `%s`；title: %s；roles: %s\n" % (mission, title, ",".join(roles)))
        f.write("- 依据使命变更规程（快照 → 草案 → 三层验证 → 安全/审计 → 沙箱 → 人工确认）；"
                "成员卡片须按新角色表整体迁移后重新审计。\n")
    return {"registry": reg, "history": _mission_history(root), "audit": _audit_report(root)}


def web_cmd(root, action, params=None):
    """受控命令层。返回 {"ok": bool, "result": ...} 或 {"ok": False, "error": ...}。
    仅动作白名单可执行；promote 先 dry-run (promote_check) 由人工确认证据后再执行。"""
    params = params or {}
    try:
        if action == "snapshot":
            return {"ok": True, "result": web_snapshot(root)}
        if action == "task_new":
            tid = params.get("task_id"); goal = params.get("goal", "")
            if not tid or not goal:
                raise ValueError("task_new needs task_id and goal")
            return {"ok": True, "result": task_register(root, tid, goal, params.get("by"))}
        if action == "send":
            sender = params.get("sender"); mtype = params.get("type")
            if not sender or not mtype:
                raise ValueError("send needs sender and type")
            payload = params.get("payload", {})
            if isinstance(payload, str):
                payload = json.loads(payload)
            rec = send(root, sender, mtype, params.get("recipient"), params.get("topic"),
                       bool(params.get("broadcast")), payload, params.get("task"),
                       params.get("correlation"))
            return {"ok": True, "result": {"id": rec["id"], "ts": rec["ts"]}}
        if action == "status_set":
            if not params.get("agent") or not params.get("status"):
                raise ValueError("status_set needs agent and status")
            return {"ok": True, "result": status_set(root, params["agent"], params["status"], params.get("progress"))}
        if action == "promote_check":
            ev = _evidence_pass_for_task(root, params.get("task", ""))
            card = _read_json(ensure(root)["agents"] / (params.get("by") or "?") / "agent-card.json", {})
            return {"ok": True, "result": {
                "evidence": ev, "promoter_role": card.get("role"),
                "gate_ok": bool(ev) and card.get("role") in ("qa", "ops")}}
        if action == "promote":
            if not all(params.get(k) for k in ("agent", "path", "target", "by", "task")):
                raise ValueError("promote needs agent/path/target/by/task")
            return {"ok": True, "result": fs_promote(root, params["agent"], params["path"],
                                                     params["target"], params["by"], params["task"])}
        if action == "audit":
            return {"ok": True, "result": _audit_report(root)}
        if action == "probe":
            return {"ok": True, "result": _run_probe(root)}
        if action == "run_demo":
            return {"ok": True, "result": _run_demo(root)}
        if action == "run_llm":
            return {"ok": True, "result": _run_llm_member(root, params)}
        if action == "mission_switch_dry":
            return {"ok": True, "result": mission_switch_dry(root, params)}
        if action == "mission_apply":
            return {"ok": True, "result": mission_apply(root, params)}
        return {"ok": False, "error": "unknown action %r (whitelist: %s)"
                % (action, "snapshot/task_new/send/status_set/promote_check/promote/audit/probe/"
                           "run_demo/run_llm/mission_switch_dry/mission_apply")}
    except (SchemaError, ValueError, KeyError, json.JSONDecodeError, FileNotFoundError) as e:
        return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}


# ---------------------------------------------------------------- 待验证区 → 发布（Ch9 安全边界）

def _evidence_pass_for_task(root, task_id):
    """扫描消息：是否存在 task_id 的 review_result=pass 且携带 method+evidence（独立验证证据）。"""
    p = ensure(root)
    for f in sorted(p["messages"].glob("*.jsonl")):
        for m in _read_jsonl(f):
            if m.get("type") != "review_result" or m.get("task_id") != task_id:
                continue
            pl = m.get("payload") or {}
            if pl.get("verdict") == "pass" and pl.get("method") and pl.get("evidence"):
                return m
    return None


def fs_promote(root, agent_id, path, target, by, task_id):
    """待验证区 → 发布：仅 qa/ops（守门角色，非 Manager）可在存在对应任务的
    evidence 背书（review_result=pass + method + evidence）后，将 shared/<agent>/<path>
    复制进 shared/deliverables/<target>。演进区文件保留（只增不改）。"""
    p = pathlib.Path(root).resolve()
    src = (p / path).resolve()
    dst = (p / ("shared/deliverables/" + target)).resolve()
    if not str(src).startswith(str(p / "shared" / agent_id)):
        raise SchemaError("promote source must be under shared/%s/ (staging)" % agent_id)
    if not str(dst).startswith(str(p / "shared/deliverables")):
        raise SchemaError("promote target must be under shared/deliverables/")
    card = _read_json(ensure(root)["agents"] / by / "agent-card.json", {})
    if card.get("role") not in ("qa", "ops"):
        return {"ok": False, "reason": "promoter %s role=%s not gatekeeper (qa/ops)" % (by, card.get("role"))}
    if not src.exists():
        raise SchemaError("staging source not found: %s" % path)
    ev = _evidence_pass_for_task(root, task_id)
    if ev is None:
        return {"ok": False, "reason": "no evidence-backed review_result=pass for task %s" % task_id}
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return {"ok": True, "from": path, "to": "shared/deliverables/" + target,
            "evidence_envelope": ev["id"], "promoted_by": by}


# ---------------------------------------------------------------- CLI

def _cli():
    ap = argparse.ArgumentParser(prog="teamctl", description="多 Agent 去中心化团队协议层工具")
    ap.add_argument("--root", default=None, help="工作区根目录（默认：本文件上两级）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def sp(name, help_):
        s = sub.add_parser(name, help=help_)
        return s

    s = sp("agent", "注册/列出成员（Agent Card）")
    ss = s.add_subparsers(dest="sub", required=True)
    a = ss.add_parser("new")
    a.add_argument("--id", required=True)
    a.add_argument("--name")
    a.add_argument("--role", default="general")
    a.add_argument("--description")
    a.add_argument("--capabilities", nargs="*", default=[])
    a.add_argument("--tools", nargs="*", default=[])
    a.add_argument("--skills", nargs="*", default=[])
    a.add_argument("--subscriptions", default="[]", help='订阅 JSON，如 \'[{"topic":"planning","event_types":["task_assigned"]}]\'')
    b = ss.add_parser("list")
    a = ss.add_parser("subscribe")
    a.add_argument("--id", required=True)
    a.add_argument("--topic", required=True)
    a.add_argument("--events", default="", help="逗号分隔事件类型；缺省=主题全部类型")

    s = sp("send", "发送消息信封（总线/点对点/广播）")
    s.add_argument("--sender", required=True)
    s.add_argument("--type", required=True, choices=ENVELOPE_TYPES)
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--recipient")
    g.add_argument("--topic")
    g.add_argument("--broadcast", action="store_true")
    s.add_argument("--payload", default="{}")
    s.add_argument("--task")
    s.add_argument("--correlation")

    s = sp("read", "读取某成员可见消息")
    s.add_argument("--from", dest="agent_id", required=True)
    s.add_argument("--topic")
    s.add_argument("--tail", type=int)
    s.add_argument("--after")

    s = sp("status", "状态机读写")
    ss = s.add_subparsers(dest="sub", required=True)
    a = ss.add_parser("set")
    a.add_argument("--agent", required=True)
    a.add_argument("--status", required=True, choices=AGENT_STATUS)
    a.add_argument("--progress")
    b = ss.add_parser("get")
    b.add_argument("--agent", required=True)

    s = sp("handoff", "去中心化移交包")
    ss = s.add_subparsers(dest="sub", required=True)
    a = ss.add_parser("new")
    a.add_argument("--task", required=True)
    a.add_argument("--sender", required=True)
    a.add_argument("--recipient", required=True)
    a.add_argument("--goal", required=True)
    a.add_argument("--budget", type=float, required=True)
    a.add_argument("--constraint", action="append", default=[])
    a.add_argument("--fact", action="append", default=[])
    a.add_argument("--artifact", action="append", default=[])
    a.add_argument("--visited", default=None)
    a.add_argument("--no-record", action="store_true")
    b = ss.add_parser("check")
    b.add_argument("--package", required=True)

    s = sp("lock", "共享区乐观锁")
    ss = s.add_subparsers(dest="sub", required=True)
    a = ss.add_parser("acquire")
    a.add_argument("--file", required=True)
    a.add_argument("--agent", required=True)
    b = ss.add_parser("release")
    b.add_argument("--file", required=True)
    b.add_argument("--agent")
    c = ss.add_parser("status")
    c.add_argument("--file", required=True)

    s = sp("log", "轨迹持久化（JSONL，只增不改）")
    ss = s.add_subparsers(dest="sub", required=True)
    a = ss.add_parser("append")
    a.add_argument("--agent", required=True)
    a.add_argument("--kind", required=True, choices=["step", "tool", "decision", "message", "verdict"])
    a.add_argument("--event", default="{}")
    b = ss.add_parser("read")
    b.add_argument("--agent", required=True)
    b.add_argument("--tail", type=int)

    s = sp("task", "任务注册表 ops 视图（只读）")
    ss = s.add_subparsers(dest="sub", required=True)
    ss.add_parser("list")
    a = ss.add_parser("show")
    a.add_argument("--task", required=True)

    s = sp("fs", "受锁文件读写（共享区自动加锁 / 范围硬检查）")
    ss = s.add_subparsers(dest="sub", required=True)
    a = ss.add_parser("write")
    a.add_argument("--path", required=True)
    a.add_argument("--content", required=True)
    a.add_argument("--agent", required=True)
    b = ss.add_parser("promote")
    b.add_argument("--path", required=True, help="staging 源（shared/<agent>/...）")
    b.add_argument("--target", required=True, help="发布目标（相对 shared/deliverables/）")
    b.add_argument("--agent", required=True, help="staging 源所属成员（shared/<agent>/ 的所有者）")
    b.add_argument("--by", required=True, help="守门角色 qa/ops")
    b.add_argument("--task", required=True, help="需要对应任务的 evidence 背书")
    b = ss.add_parser("read")
    b.add_argument("--path", required=True)

    s = sp("usage", "token 用量登记/汇总（可插拔计量；估值为 estimate 标注）")
    ss = s.add_subparsers(dest="sub", required=True)
    a = ss.add_parser("record")
    a.add_argument("--agent", required=True)
    a.add_argument("--step", type=int, required=True)
    a.add_argument("--tokens", type=int, required=True)
    a.add_argument("--source", default="estimate")
    a.add_argument("--op")
    a.add_argument("--task")
    b = ss.add_parser("report")
    b.add_argument("--task")
    b.add_argument("--agent")

    s = sp("quota", "资源配额（预算池/并发上限）")
    ss = s.add_subparsers(dest="sub", required=True)
    a = ss.add_parser("init")
    a.add_argument("--task", required=True)
    a.add_argument("--units", default="tokens", choices=BUDGET_UNITS)
    a.add_argument("--pool", type=float, required=True)
    a.add_argument("--concurrency", type=int)
    b = ss.add_parser("consume")
    b.add_argument("--task", required=True)
    b.add_argument("--amount", type=float, required=True)
    c = ss.add_parser("status")
    c.add_argument("--task", required=True)

    s = sp("mission", "使命登记（可信根；与 roles.md 配套，换挡=revision+1）")
    ss = s.add_subparsers(dest="sub", required=True)
    a = ss.add_parser("init")
    a.add_argument("--mission", required=True)
    a.add_argument("--title", required=True)
    a.add_argument("--revision", type=int, default=1)
    a.add_argument("--roles", nargs="*", required=True)
    b = ss.add_parser("get")

    s = sp("web", "网页控制台数据契约（S0+：snapshot 只读；命令类见 web command）")
    ss = s.add_subparsers(dest="sub", required=True)
    a = ss.add_parser("snapshot", help="只读聚合快照（零副作用）")
    a.add_argument("--message-tail", type=int, default=10)
    a.add_argument("--log-tail", type=int, default=5)
    c = ss.add_parser("command", help="受控命令（白名单动作，参数 JSON）")
    c.add_argument("--action", required=True)
    c.add_argument("--params", default="{}", help="JSON 参数对象")

    args = ap.parse_args()
    root = args.root or (pathlib.Path(__file__).resolve().parent.parent)
    try:
        if args.cmd == "agent":
            if args.sub == "new":
                print(json.dumps(agent_new(root, args.id, args.name, args.role,
                                           args.description, args.capabilities, args.tools,
                                           args.skills, json.loads(args.subscriptions)), ensure_ascii=False, indent=2))
            elif args.sub == "subscribe":
                evs = [e for e in args.events.split(",") if e]
                print(json.dumps(agent_subscribe(root, args.id, args.topic, evs),
                                 ensure_ascii=False, indent=2))
            else:
                print(json.dumps(agent_list(root), ensure_ascii=False, indent=2))
        elif args.cmd == "send":
            print(json.dumps(send(root, args.sender, args.type, args.recipient, args.topic,
                                  args.broadcast, json.loads(args.payload), args.task,
                                  args.correlation), ensure_ascii=False))
        elif args.cmd == "read":
            print(json.dumps(read(root, args.agent_id, args.topic, args.tail, args.after),
                             ensure_ascii=False, indent=2))
        elif args.cmd == "status":
            if args.sub == "set":
                print(json.dumps(status_set(root, args.agent, args.status, args.progress),
                                 ensure_ascii=False))
            else:
                print(json.dumps(status_get(root, args.agent), ensure_ascii=False, indent=2))
        elif args.cmd == "handoff":
            if args.sub == "new":
                facts = [json.loads(f) for f in args.fact]
                visited = split_visited(args.visited)
                r = handoff_new(root, args.task, args.sender, args.recipient, args.goal,
                                args.budget, args.constraint, facts, args.artifact,
                                visited=visited, record=not args.no_record)
                print(json.dumps(r, ensure_ascii=False, indent=2))
            else:
                h = _read_json(pathlib.Path(args.package))
                verdict, detail = check_handoff(h)
                print(json.dumps({"verdict": verdict, "detail": detail}, ensure_ascii=False))
        elif args.cmd == "lock":
            if args.sub == "acquire":
                print(json.dumps(lock_acquire(root, args.file, args.agent), ensure_ascii=False))
            elif args.sub == "release":
                print(json.dumps(lock_release(root, args.file, args.agent), ensure_ascii=False))
            else:
                print(json.dumps(lock_status(root, args.file), ensure_ascii=False))
        elif args.cmd == "log":
            if args.sub == "append":
                print(json.dumps(log_append(root, args.agent, args.kind, json.loads(args.event)),
                                 ensure_ascii=False))
            else:
                print(json.dumps(log_read(root, args.agent, args.tail), ensure_ascii=False,
                                 indent=2))
        elif args.cmd == "task":
            if args.sub == "show":
                r = task_show(root, args.task)
                if r is None:
                    print("ERROR: no such task %r" % args.task, file=sys.stderr)
                    sys.exit(2)
                print(json.dumps(r, ensure_ascii=False, indent=2))
            else:
                print(json.dumps(task_list(root), ensure_ascii=False, indent=2))
        elif args.cmd == "fs":
            if args.sub == "write":
                print(json.dumps(fs_write(root, args.agent, args.path, args.content),
                                 ensure_ascii=False))
            elif args.sub == "promote":
                print(json.dumps(fs_promote(root, args.agent, args.path, args.target,
                                            args.by, args.task), ensure_ascii=False))
            else:
                print(json.dumps(fs_read(root, args.path), ensure_ascii=False, indent=2))
        elif args.cmd == "usage":
            if args.sub == "record":
                print(json.dumps(usage_record(root, args.agent, args.step, args.tokens,
                                              args.source, args.op, args.task),
                                 ensure_ascii=False))
            else:
                print(json.dumps(usage_summary(root, args.task, args.agent),
                                 ensure_ascii=False, indent=2))
        elif args.cmd == "quota":
            if args.sub == "init":
                print(json.dumps(quota_init(root, args.task, args.units, args.pool,
                                            args.concurrency), ensure_ascii=False))
            elif args.sub == "consume":
                print(json.dumps(quota_consume(root, args.task, args.amount), ensure_ascii=False))
            else:
                r = quota_status(root, args.task)
                if r is None:
                    print("ERROR: no quota for task %r" % args.task, file=sys.stderr)
                    sys.exit(2)
                print(json.dumps(r, ensure_ascii=False, indent=2))
        elif args.cmd == "mission":
            if args.sub == "init":
                print(json.dumps(mission_init(root, args.mission, args.title,
                                              args.roles, args.revision),
                                 ensure_ascii=False, indent=2))
            else:
                r = mission_get(root)
                if r is None:
                    print("ERROR: mission not registered (system/state/mission.json)",
                          file=sys.stderr)
                    sys.exit(2)
                print(json.dumps(r, ensure_ascii=False, indent=2))
        elif args.cmd == "web":
            if args.sub == "snapshot":
                print(json.dumps(web_snapshot(root, args.message_tail, args.log_tail),
                                 ensure_ascii=False, indent=2))
            else:
                print(json.dumps(web_cmd(root, args.action, json.loads(args.params)),
                                 ensure_ascii=False, indent=2))
    except (SchemaError, ValueError, KeyError, json.JSONDecodeError, FileNotFoundError) as e:
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    _cli()
