# 团队用起来：网页部署运行（Roadmap S0–S5）

> 状态：**已实施（Round 13）**。S0–S5 全部落地为 `web/teamd.py`（纯标准库
> HTTP+SSE）+ `web/index.html`（单文件无构建控制台）+ `web/README.md`（部署/安全
> 文档），测试 61/61 通过。路线图从「先嵌入 DSH、后独立部署」调整为 **直接独立
> 部署 `teamd`**（原因见 §3），DSH 适配保留为可选后续。

## 1. 为什么需要网页层

当前团队能力（62/62 测试，Round 13 后）全部在 CLI 与网页双调用面：

| 已有能力 | 位置 | 使用方式 |
|---|---|---|
| 网页控制台（S0–S5） | `web/teamd.py` + `web/index.html` | `python3.10 web/teamd.py --root . --port 8090` → 浏览器打开 |
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

## 3. 实施路线（Round 13 定稿）：直接独立部署 `teamd`

原方案为「先嵌入 DSH（S0–S2），再独立部署（S5）」。实际跳过 DSH 嵌入、直接实现
独立 `teamd`，原因：

1. **协议层可插拔**：`teamctl.py`/`member.py` 本就是纯标准库的独立调用面，一个
   `ThreadingHTTPServer` + `web_snapshot`/`web_cmd` 白名单即可获得最小闭环，
   无需 Cordis/Slot 改造，符合「不引入数据库、零构建」的既有约束。
2. **真 LLM 成员独立可用**：S3 直接用 `OpenAICompatLLM`（OpenAI 兼容端点 →
   `MemberRuntime`，含真实 usage 计量与 `source_tag=real:openai-compat` 诚实标注），
   不依赖 DSH 的子代理机制，`teamd` 自身就是完整运行时。
3. **DSH 适配保留为可选**：把团队作为 DSH 能力（DSH 内嵌 teamd，或用 5 个 agent
   preset 当成员）仍可在不改协议层的前提下做一层适配，作为后续扩展（见 §6 待办）。

DSH 形态映射（§2 的表）仍然成立：`teamd` ↔ host 进程，控制台 ↔ Web GUI，
task ↔ Session，member ↔ 子代理，人工干预点 ↔ Approval。

## 4. 里程碑与验收（每步可演示、有测试）

### S0 只读控制台（先看得见）✅
- 面板：成员卡片（id/role/subscribe/status/usage/quota）、任务板（tasks.json）、消息流（按 topic）、handoff 链、冲突列表、审计 8 项结果、评测摘要。
- 验收：网页能看到当前工作区全部状态；数据与 CLI 一致（diff 校验）。
- 实现：`teamctl.web_snapshot()`（只读聚合）+ `GET /api/snapshot`；测试
  `test_web.py::test_snapshot_readonly`（零副作用）、`test_teamd.py::test_index_and_snapshot`
  （快照与 CLI 直调一致）。

### S1 网页控制（用得动）✅
- 按钮：创建任务、发送消息、更新成员状态、**promote 审批**（展示 evidence + 发起者 → 确认后调 `fs_promote`）、运行审计、运行安全探针。
- 验收：网页操作产生的 JSONL/文件与命令行的效果一致；审计 `exit 0`。
- 实现：`POST /api/command` → `teamctl.web_cmd()` 白名单（task_new/send/status_set/
  promote_check/promote/audit/probe）；测试 `test_teamd.py::test_commands`（含 promote
  证据门禁放行/拦截）、`test_web.py::test_audit_failure_reflected`。

### S2 成员执行（跑得起来）✅
- 「运行一次成员」：选择成员 + 任务 → host 端调用 `MemberRuntime`（先 ScriptedLLM 演示闭环，后 LLMBackend/DSH 子代理），进度经推送通道实时上屏。
- 验收：网页发起一个完整任务（spec→architect→dev→qa→ops），观察消息流推进、配额扣减、promote 事件出现。
- 实现：`POST /api/run kind=demo` → `_run_demo()`（子进程 m8_demo，工作区=临时目录，
  证据写 `eval/run/<date>-web-demo-NN/`）+ 作业队列 + SSE（`/api/events`）；
  测试 `test_teamd.py::test_run_demo_job`，证据 `eval/run/2026-09-18-web-demo-01/`
  （recap.json：5 成员 done、promote True、配额剩余 7165.0、27 条用量记录）。

### S3 真实 LLM 成员（像 DSH 一样）✅（以 OpenAI 兼容端点实现）
- 每角色一个 DSH agent preset（读取 `agents/<id>/agent-card.json` 的 role/tools/skills/subscriptions 注入系统提示），成员通过受限 tool 访问工作区（复用 `_check_write`/`_check_fs_scope` 边界）。
- 验收：5 角色在 DSH 中作为子代理完成与协议层兼容的往返；交接链/visited chain 正常；失败模式（重复消息、锁竞争、卡死）被协议层捕获。
- 实际实现：`member.OpenAICompatLLM(base_url, api_key, model)`（OpenAI 兼容
  `/chat/completions`）→ `_run_llm_member()` → `MemberRuntime`，计量用响应
  `usage.total_tokens` 且 `source_tag="real:openai-compat"`（诚实标注，不冒充估算）；
  `POST /api/run kind=llm` 异步执行，`api_key` 只进 worker 内存、不落盘不出现在
  `/api/jobs`（S5 断言）。**DSH 5 preset 适配为可选后续**（协议层兼容，见 §6）。
- 测试：`test_llm.py` × 3（真实后端计量 15tokens×3、端点不可达 loud failure、
  经 teamd 作业全链路 + jobs 不泄露 key）。

### S4 使命与安全（可控可演进）✅
- 网页入口：使命注册表只读展示、切换流程（快照→草案→三层验证→审计→沙箱→确认，复用 R11 实现）；一键安全探针/评测面板。
- 验收：网页完成的使命切换与 CLI 流程等价；安全集 3/3、评分与 REPO 记录一致。
- 实现：快照含 `mission/mission_history/usage/audit/eval_runs`；命令
  `mission_switch_dry`（沙盒 copytree + 审计，零副作用）/ `mission_apply`
  （registry revision+1 + mission-history.jsonl + roles.md 追加，`by='operator'`）；
  测试 `test_web.py::test_mission_dry_run_sandbox`、`test_mission_apply`。

### S5 独立部署（可选）✅
- `teamd`：stdlib HTTP + SSE + 静态页；`--root` 指定工作区；`--host/--port`；无状态 worker 由协议层保证（乐观锁）。
- 验收：脱离 DSH 启动 teamd，网页上重放 S1–S2 验收；多实例并发下锁校验不破坏。
- 实现：`serve(root, host, port, message_tail, log_tail, token)`；`--token` 命令鉴权、
  安全响应头（CSP `default-src 'none'` + nosniff + DENY + no-referrer）、
  `api_key` 作业脱敏、部署/多实例/生产文档 `web/README.md`；测试
  `test_teamd.py::test_security_headers`、多实例并发由既有 `test_parallel.py` 覆盖。

## 5. 技术选型与不变量

- **协议层不动**：网页只是 `teamctl.py`/`member.py` 的另一个调用面；所有写操作仍经 `_check_fs_scope`/`_check_write`/CAS 锁约束，绝不让网页绕过协议。
- **host=唯一可信写者**：浏览器只发命令，不直接写文件；host 校验身份/scope。
- **推送**：先 SSE（stdlib 可做），事件源 = 追加的 JSONL inotify/轮询尾指针；不引入数据库。
- **安全**：promote/使命变更/运行成员 = 人工确认项（对齐 Ch9 信任锚点——人类是唯一可修改系统边界的角色）。
- **兼容**：`python3.10`，仅标准库（延续 teamctl 风格）；前端单文件无构建。

## 6. 待办（按序）

- [x] S0 只读控制台（数据契约：`teamctl` 增 `web_snapshot` 只读命令，聚合成员/任务/消息尾/配额/审计）
- [x] S1 控制命令（`web_cmd` 白名单，HTTP→protocol 校验→执行→返回结果+审计）
- [x] S2 成员执行接入（`kind=demo` 完整任务链：ScriptedLLM 闭环 + 作业队列 + SSE）
- [x] S3 真实 LLM 成员（`OpenAICompatLLM` 接入 `MemberRuntime`，真实 usage 计量；DSH 5 preset 为可选后续）
- [x] S4 使命/安全/评测面板（mission 展示 + switch_dry/apply + probe/audit 面板）
- [x] S5 `teamd` 独立部署（`--root/--host/--port/--token` + 安全头 + 部署文档）
- [ ] （可选）DSH 适配：5 角色 agent preset 作为成员（不改协议层，仅加适配层）
- [ ] （可选）读取端点鉴权（如反向代理 Basic Auth）与 WebSocket 推送替代轮询+SSE
