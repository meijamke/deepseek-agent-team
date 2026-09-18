# 团队用起来：网页部署运行（Roadmap S0–S5）

> 状态：设计稿（Round 12）。目标：把「多 Agent 去中心化团队」从 CLI 协议层升级为
> **可在网页上部署、运行、观察、干预** 的团队运行时，形态参照 DeepSeek Harness
> （常驻 host 进程 + 浏览器控制台 + 审批/日志/审计）。

## 1. 为什么需要网页层

当前团队能力（已 49/49 测试）全部在命令行：

| 已有能力 | 位置 | 使用方式 |
|---|---|---|
| 协议层（信封/锁/消息总线/task/quota/usage） | `tools/teamctl.py` | `python3.10 tools/teamctl.py --root . <cmd>` |
| 成员运行时（ReAct + ScriptedLLM/LLMBackend） | `team/member.py` | `python3.10 tools/member.py ...` |
| 审计（8 项检查） | `tools/audit.py` | exit code 0/1 |
| 安全探针（3 项） | `tools/probe_safety.py` | exit code 0/1 |
| 评测（边界/保留/安全集、D1/D8 对比） | `eval/`, `tools/d1_compare.py` | 手工运行 |
| 使命注册/切换 | `teamctl mission *` + `tools/audit.py` | 手工运行 |

网页层解决的核心问题：**观察成本**（现在看一次运行要 tail JSONL）、**发起成本**（任务、消息、审批都要手敲命令）、
**干预成本**（promote/使命变更/审计没有可视化入口）、**可复现性**（没有「一键跑一个完整任务」的入口）。

## 2. 参照 DeepSeek Harness 的形态映射

| DSH 概念 | 团队对应物 | 说明 |
|---|---|---|
| Host 进程（Node + Cordis 注册表） | `teamd` 宿主（或 DSH 内嵌宿主） | 持有工作区、protocol 服务、成员调度 |
| Web GUI（Run 卡片、日志、审批弹窗） | 团队控制台 | 成员卡片/消息流/任务板/审批 |
| 会话/Session | 一次任务运行（task） | 一个 task = 一次团队协作 |
| 子代理/agent preset | 团队成员 | 每角色一个 preset，读写工作区（受限工具） |
| Tools/Events/Services | `teamctl` JSON 方法 + 协议事件 | 网页按钮 → host 封装 → 协议层 |
| 审批（Approval） | 人工干预点 | promote 证据审批、使命变更确认 |
| 审计/日志 | `audit.py` + `system/logs/` | 控制台一键运行 |

## 3. 推荐路线：先嵌入 DSH（S0–S2），再独立部署（S5）

**为什么先嵌入 DSH**：DSH 在本机已运行（Web GUI `http://127.0.0.1:3081`），具备
host/Client 通道、Slot UI、审批、日志与模型路由；团队协议层只需要一个
**Host 插件（JSON 方法封装 teamctl）+ Client 插件（控制台 Slot）** 即可获得
「网页上部署运行」的最小闭环，无需重造 UI 骨架。成员执行层（真实 LLM）可直接复用
DSH 子代理机制（每个角色一个 agent preset），保持「无 Manager、消息总线、共享工作区」不变。

**为什么保留独立部署作为 S5**：若未来需要多团队并行、跨机运行、或对外开放，再把
`teamctl` 本体抽成 `teamd`（stdlib HTTP/WebSocket 服务 + 静态页面），协议层不变。

## 4. 里程碑与验收（每步可演示、有测试）

### S0 只读控制台（先看得见）
- 面板：成员卡片（id/role/subscribe/status/usage/quota）、任务板（tasks.json）、消息流（按 topic）、handoff 链、冲突列表、审计 8 项结果、评测摘要。
- 验收：网页能看到当前工作区全部状态；数据与 CLI 一致（diff 校验）。

### S1 网页控制（用得动）
- 按钮：创建任务、发送消息、更新成员状态、**promote 审批**（展示 evidence + 发起者 → 确认后调 `fs_promote`）、运行审计、运行安全探针。
- 验收：网页操作产生的 JSONL/文件与命令行的效果一致；审计 `exit 0`。

### S2 成员执行（跑得起来）
- 「运行一次成员」：选择成员 + 任务 → host 端调用 `MemberRuntime`（先 ScriptedLLM 演示闭环，后 LLMBackend/DSH 子代理），进度经推送通道实时上屏。
- 验收：网页发起一个完整任务（spec→architect→dev→qa→ops），观察消息流推进、配额扣减、promote 事件出现。

### S3 真实 LLM 成员（像 DSH 一样）
- 每角色一个 DSH agent preset（读取 `agents/<id>/agent-card.json` 的 role/tools/skills/subscriptions 注入系统提示），成员通过受限 tool 访问工作区（复用 `_check_write`/`_check_fs_scope` 边界）。
- 验收：5 角色在 DSH 中作为子代理完成与协议层兼容的往返；交接链/visited chain 正常；失败模式（重复消息、锁竞争、卡死）被协议层捕获。

### S4 使命与安全（可控可演进）
- 网页入口：使命注册表只读展示、切换流程（快照→草案→三层验证→审计→沙箱→确认，复用 R11 实现）；一键安全探针/评测面板。
- 验收：网页完成的使命切换与 CLI 流程等价；安全集 3/3、评分与 REPO 记录一致。

### S5 独立部署（可选）
- `teamd`：stdlib HTTP + SSE + 静态页；`--root` 指定工作区；`--host/--port`；无状态 worker 由协议层保证（乐观锁）。
- 验收：脱离 DSH 启动 teamd，网页上重放 S1–S2 验收；多实例并发下锁校验不破坏。

## 5. 技术选型与不变量

- **协议层不动**：网页只是 `teamctl.py`/`member.py` 的另一个调用面；所有写操作仍经 `_check_fs_scope`/`_check_write`/CAS 锁约束，绝不让网页绕过协议。
- **host=唯一可信写者**：浏览器只发命令，不直接写文件；host 校验身份/scope。
- **推送**：先 SSE（stdlib 可做），事件源 = 追加的 JSONL inotify/轮询尾指针；不引入数据库。
- **安全**：promote/使命变更/运行成员 = 人工确认项（对齐 Ch9 信任锚点——人类是唯一可修改系统边界的角色）。
- **兼容**：`python3.10`，仅标准库（延续 teamctl 风格）；前端单文件无构建。

## 6. 待办（按序）

- [ ] S0 只读控制台（数据契约：`teamctl` 增 `web_snapshot` 只读命令，聚合成员/任务/消息尾/配额/审计）
- [ ] S1 控制命令（`web_run_command`，HTTP→protocol 校验→执行→返回结果+审计）
- [ ] S2 成员执行接入（ScriptedLLM → LLMBackend/DSH 子代理）
- [ ] S3 5 个角色 DSH preset + 受限工作区工具
- [ ] S4 使命/安全/评测面板
- [ ] S5 `teamd` 独立部署（按需）
