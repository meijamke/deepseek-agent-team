# 协议规范 · 多 Agent 去中心化团队

> 依据《AI Agents in Depth》第 10 章：多 Agent 系统 = 数据平面（虚拟文件系统）+ 控制平面（消息、状态、终止、调度）。
> 目标架构：**去中心化模式**（无中心 Manager；对等成员通过 handoff 自主移交 + 消息池/总线通信）。

## 1. 三个协议对象

| 文件 | 用途 | 书本依据 |
|---|---|---|
| `message-envelope.schema.json` | 消息信封：发送者/目标/类型/负载/关联 ID，统一路由与可追溯 | Ch10「消息传递：统一信封」 |
| `handoff.schema.json` | 去中心化移交包：goal/constraints/accepted_facts/artifact_refs/预算/访问链 | Ch10「去中心化模式 · OpenAI Swarm 最小协议」 |
| `agent-card.schema.json` | 成员名片：能力/模态/工具/技能/订阅；解决能力发现 | Ch10「A2A 协议 · Agent Card」 |

### 消息信封（Envelope）

```json
{ "envelope_version": 1, "id": "ab12cd34ef56", "ts": "2026-09-14T10:00:00+00:00",
  "sender_id": "spec", "recipient_id": "dev",
  "type": "task_assigned", "task_id": "t-001", "payload": {"task": "implement ping"} }
```

路由三选一（互斥）：`recipient_id`（点对点）/ `topic`（消息池订阅）/ `broadcast`（广播）。
事件类型：`task_assigned · status_update · result · info_collected · review_request ·
review_result · terminate · terminate_ack · query · error · note`。

### 移交包（Handoff）— 去中心化的心脏

```python
handoff = {
  task_id, sender_id, recipient_id, goal, constraints[],
  accepted_facts[{fact, source}], artifact_refs[],      # 传引用，不传全文
  remaining_budget, budget_units, visited_agents[], visited_created_at
}
if recipient in visited_agents:      reject("cycle")            # 环检测
elif remaining_budget <= 0:          stop_and_escalate()        # 预算衰减
else:                                append(recipient, visited); run_local_agent()
```

**规则**：预算与访问链由运行时（`teamctl`/registry）保留，任何 Agent 无权删除；
`artifact_refs` 是路径字符串，接收方按需读取（接口清晰原则）。

### 成员名片（Agent Card）

每个成员 `agents/<id>/agent-card.json` 声明 role、capabilities、input/output modalities、
tools、skills、subscriptions（订阅的 topic + event_types）。跨组织时可发布为 A2A Agent Card。

## 2. 控制平面原语（`tools/teamctl.py`）

| 原语 | CLI | 相当于 |
|---|---|---|
| 注册/发现 | `agent new / agent list` | A2A 能力发现；OS `ps` |
| 发消息 | `send --sender X --type ... (--recipient/--topic/--broadcast)` | 消息总线 publish |
| 读消息 | `read --from X [--topic] [--tail N]` | 按订阅/收件人路由 |
| 状态机 | `status set/get --agent X` | `progress.md` 约定进度文件 |
| 移交 | `handoff new/check` | 对等接力 + 环/预算保护 |
| 乐观锁 | `lock acquire/release/status` | 共享区并发冲突 CAS |
| 轨迹 | `log append/read --agent X` | 轨迹持久化（JSONL，只增不改） |

## 3. 三条铁律（书本 Ch1/Ch10 设计模式，写进协议的原因）

1. **只增不改**：消息、轨迹、进度一律追加；可变结论（摘要/索引/经验）离线重建。
2. **传引用不传思考**：移交只给 `accepted_facts` + `artifact_refs`，不暴露私有轨迹/思维链。
3. **模型不得自证完成**：`result` 消息可声称完成，但只有持有**独立证据**（执行/渲染/工具验证）的
   审核者发出 `review_result: pass` 后才算完成（提议者-审核者范式）。
