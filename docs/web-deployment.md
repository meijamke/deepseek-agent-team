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

## 7. 来自 DSH discussion #5180 的实践点（Round 14 实跑后提炼落地）

> 来源：[deepseek-harness discussion #5180](https://github.com/deepseek-ai/deepseek-harness/discussions/5180)
> 「App Plugin for DeepSeek Harness：一种同时面向人和 Agent 的插件形态」+ 社区回复
> （YiHe：问题自动路由到领域包）。核心主张：**权威状态 = 有严格 Schema 的领域对象**、
> **Agent 走封闭 action（业务语义+权限边界）**、**effect 需 revision 相关性校验（迟到结果拒绝）**、
> **人与 Agent 共用同一 validator**、**长任务状态作为持续对象呈现（preparing/running/attention/completed/failed）**。

| #5180 实践点 | 本项目对应 | 状态 |
|---|---|---|
| 权威状态不是聊天文本/流式输出，而是有 Schema 的对象 | 信封/移交/成员卡均 JSON Schema 校验；进度 JSONL 只作展示流，权威状态 = status 文件 + 发布物（promote 后） | 已有 |
| Agent 只能调用封闭 action（不允许 DOM 级自动化） | `web_cmd` 白名单 + member OPS 集合 + `_check_fs_scope`/`_check_write` | 已有 |
| effect 相关性：client/request/sequence/base revision 全部匹配才接受，迟到结果拒绝 | 乐观锁 CAS（expected_version + `_check_write` 版本校验）；被拒的过期写进入 `system/state/conflicts/` | 已有（Round 14 起在 attention 中置顶展示） |
| 人与 Agent 用同一套 validator | CLI 与网页均调用同一 teamctl 函数（等价性有测试：snapshot CLI=HTTP；web 命令=CLI 效果） | 已有 |
| 长任务需要人介入时，把状态作为**持续对象**呈现，并给出 **attention** 状态 | **新增 `attention_items()`**：status=needs_input/failed、陈旧 running（无心跳超阈值）、并发冲突、审计未通过、配额耗尽 → 收敛为决策清单，随 `web_snapshot.attention` 下发；网页新增「需关注」面板 + 头部徽标（high 标红） | ✅ Round 14 |
| 领域路由：问题自动路由到领域包（YiHe） | **新增 `route_suggest(goal)`**：关键词→角色命中→参考协作链；保持**无 Manager**——只给建议不强制（返回值注明）；`web_cmd` 白名单 + 网页「路由建议」卡片 | ✅ Round 14 |
| 人工确认前必须看到审计/验证后果 | `mission_switch_dry/apply` 结果新增 `audit_ok` + `failing_checks`（沙盒/真实审计后果），网页命令日志显示「审计通过/未通过[…]」 | ✅ Round 14 |
| 受控 effect/artifact 协议（staging→发布，只增不改） | `fs_promote` 门禁（qa/ops + evidence 背书 + staging 保留） | 已有 |
| App identity / 独立窗口 / 桌面生命周期 | 本项目形态 = 独立 `teamd` 进程 + 单页控制台（浏览器），无桌面窗口需求 | 不适用（已说明） |
| App-scoped Workspace / 每个插件一套 Session | `teamd --root` 即 App-scoped；作业=进程内存态 + 证据落盘（`eval/run/`） | 已有（文档见 web/README.md §5） |

**Round 14 实跑发现的返工项（已修复）**

1. `promote_check` 预检只看证据 + 守门角色，**不看产物是否存在** → 人工批准后才发现
   promote 失败。修复：预检门禁加入 `artifact_exists`（gate_ok 全部满足才放行），
   测试覆盖「证据在、产物缺 → gate False」「产物齐 → gate True」。
2. `mission_switch_dry` 沙盒拷贝**排除 eval/** → 审计 `evidence_gated` 引用
   `eval/tasks/*.json` 出现与换挡无关的**假阳性**，会误导人工判断。修复：沙盒保留
   eval/（只增不改证据目录拷贝后审计差分=换挡本身），实测 failing 仅剩 `card_role_known`。

**未落地（可选后续）**：任务级生命周期状态机（preparing/running/completed 的独立
task 状态字段，而非仅 attention 派生）；effect 相关性 ID（client/request/sequence per
action）；每插件 App-scoped Workspace（本项目为整队单 root）。

## 8. 多团队与 DSH 风格网页 UI（Round 15）

### 8.1 网页自主创建/切换团队

用户反馈「快速开始后打开网页完全可用，但希望能在网页上自主选择创建不同团队（模板 + 自定义）」。
实现模型：**一个工作区根 = 多个独立团队**，每个团队是一套完整虚拟文件系统。

- 团队注册表：`<workspace>/system/state/teams.json` = `{active, teams:[{team_id, name,
  template, roles, members, root, created_at, created_by}]}`；工作区根自身即团队
  `team_id="default"`（向后兼容：未建过团队时只有一个 default）。
- 团队模板（`teamctl.team_templates()`）：`software`（spec/architect/dev/qa/ops）、
  `documentation`（writer/editor/reviewer/publisher）、`research`（researcher/analyst/
  critic/summarizer）、`general`（planner/executor/reviewer）；也可**自定义角色**列表
  （`id` 或 `id:显示名`，正则 `^[a-z][a-z0-9-]*$`，自动去重）。
- `team_create(root, team_id?, name, template?, roles?, activate=True, by)`:建团队目录 →
  `mission_init` → 按角色 `agent_new` → 写注册表 → 默认自动激活；`team_switch` 切换
  active；`team_effective_root(root)` 解析命令作用根（注册表异常回退 default）。
- 作用域约定：普通命令/任务/作业作用于 **active 团队根**；`team_*` 管理动作作用于
  **工作区根**；job 在发起时快照团队根（切团队不影响已发起的 job）。
- 网页侧：左侧栏「创建团队」（模板下拉/自定义角色/名称）+ 团队列表（点击即切换）+ 成员
  列表渲染 active 团队成员；`web_snapshot` 新增 `teams`/`workspace_root` 键。

### 8.2 网页 UI 按 DSH 主题重写（修复「完全不可用」）

用户按快速开始启动后反馈**网页完全不可用**。根因：`web/index.html` 的 `render()` 内
`const badge` 被声明两次（Round 14 加 attention 徽标时引入），整个 `<script>` 解析失败
（JS SyntaxError），页面所有渲染/交互全部失效；此前测试只覆盖 API 不覆盖 JS，故滑过。

修复与改进：
1. 修复重复声明（第二个改名 `abadge`），`node --check` 语法通过。
2. 界面按 **DeepSeek Harness 网页 UI 风格**重写（参考其
   `packages/client/ui-theme/src/styles/design-platform.css` 暗色语义 token 与三栏形态）：
   - 暗色主题 token：`--bg-base:#151517`、层级 `#232324/#2c2c2e/#353536`、半透明白边框
     `rgba(255,255,255,.06/.12/.16)`、文字 `#f9fafb/#cfd3d6/#adb2b8/#818790`、
     品牌色 `#5686fe`、成功 `#22c55e`、警告 `#f59e0b`、错误 `#f25a5a`、等宽字体
     SF Mono / JetBrains Mono。
   - 布局：顶部状态栏（品牌 + 团队/使命/需关注/用量徽标 + 刷新）+ 左侧栏（团队创建/列表、
     成员）+ 主区（概览/任务/消息/操作/审计页签）+ 底部 composer + 命令日志。
3. 新增 JS 冒烟检查：`node --check` + DOM-stub harness（document/fetch/EventSource 打桩）
   覆盖 render/show/loadTemplates/sendMsg/createTeam/switchTeam/runLLM；getElementById
   id 与 HTML id 集合交叉核对。**后续约定：改 index.html 必须先跑 JS 冒烟再提交。**

### 8.3 证据

- 测试：`test_web` 6→9（TestTeams：模板列表/初始注册表、模板创建自动激活+隔离+切回、自定义
  角色与非法输入校验）；`test_teamd` 5→6（HTTP team_list/team_create/快照/成员/隔离/切回；
  页面断言更新为 DSH 风格标题）。全量 **67/67**。
- 实跑（临时工作区）：页面可达；team_create research → active=research、4 成员；custom
  团队 `activate:false` 不抢活跃；切回 default 使命 A 不变；demo job 完成；子团队审计 8/8。

### 8.4 遗留与说明

- 用户附的 DSH 网页 UI 截图链接（wenote 分享）在本环境不可达（代理拒绝），故以 DSH 源码
  主题 token 为参考，未逐像素对照截图。
- 未做：任务级生命周期状态机、任务/团队级 RBAC（当前 token 为全局写门禁）、团队删除/
  重命名/归档（注册表仅追加激活切换）。

## 9. 免初始化快速开始 + 按 DSH 实机 Web UI 重构（Round 16）

### 9.1 快速开始：下载即可启动，网页内建团队

需求：`git clone` 后**直接启动**网页控制台，在页面里自主创建团队，不再需要先 CLI 初始化使命。

- 新增 `teamctl.ensure_console(root, name="默认团队", template="software", by)`：
  工作区存在性 + 若 `state/mission.json` 缺失 → 以模板角色登记 **default 团队**（工作区根）
  并每角色建成员卡；**幂等**（已登记使命 → 原样返回，绝不覆盖/重复建成员）。
- `teamd.serve()` 启动即调用引导 → `--root` 指向空目录/新克隆也能直接开干。
- 新测试：`test_web` `test_ensure_console_bootstrap_idempotent`（首次 True/5 成员/二次 False
  不重复）；`test_teamd` `test_bare_start_bootstrap`（空目录 → HTTP 快照 default+5 → 页面建
  documentation 团队 → active 切换）。README 快速开始改为「克隆 → 启动 → 页面建团队」。
- 实跑（空目录 `/tmp/r16ws`）：`teamd` 起后快照 mission=default/agents=5；HTTP 创建 research
  → active=research/4 成员；demo 作业在该团队根完成（exit 0）。

### 9.2 依据 DSH 实机 Web UI 重构（亮色主题）

用户上传 DSH Web UI 截图（亮色），并给出可访问的实机地址（`http://127.0.0.1:3081/?token=…`）。
按「源码 token + 实机 CSS + 截图几何」三方对照重写 `web/index.html`：

- **主题来源**：DSH `packages/client/ui-theme/src/styles/design-platform.css` 亮色语义 token
  （`body` 默认即亮色；`data-ds-dark-theme` 才转暗）+ 实机 `/assets/index-*.css` 中
  `--dsh-boot-*` 与组件几何确认。截图亦为亮色（主背景 `#fff`、侧栏 `#f9fafb`、
  选中项 `#ebedf2`、品牌蓝 `#5686fe/#4176e6`），与 token 完全吻合。
- **布局几何**（`AppFrame.tsx` / `columns.ts` / `ConversationRoot.module.css` /
  `InputBar.module.css` / `Button.module.css` / `Input.module.css` / `MessageItem.module.css`）：
  - 三栏：侧栏 280px（264–420 可拖，<1024 自动收为 56px rail）| 中栏 ≥640 | 详情 360
    （默认收起）；分隔线 **0.5px `rgba(0,0,0,.12)`**；本控制台采用「侧栏 280 + 内容」两栏。
  - 会话列宽轴：`clamp(680px, 64%, 920px)`（输入卡 +32px、两侧留白 16px）→ 内容居中。
  - 顶栏：padding 12/28、标题行 min-height 32、底部 0.5px 发丝线。
  - 按钮：**胶囊** `r18/h36`（紧凑 `r16/h32`），primary=**深色填充 `#0f1115`**
    （hover `#43454a`），ghost hover `rgba(38,49,72,.06)`。
  - 输入：h32、`0.5px rgba(0,0,0,.16)` 描边、`r8`、focus 描边替换。
  - 消息：本人气泡 `deepseek-50 #edf3fe`、`r22`、右上对齐（上限 70.2% 内容宽）；
    普通消息卡 `#f9fafb/r12`；代码块 `#f9fafb/r12`（DSH `--dsl-web-radius: 12px`）。
  - 状态：成功 `#22c55e`、警告 `#f59e0b/#dd8629`、错误 `#f25a5a/#ec1313`、品牌 `#5686fe/#4176e6`。
- **实测断言**：`node --check` + 新增**可复现冒烟** `tools/ui_smoke.js`（DOM 打桩：
  document/fetch/EventSource；真实 snapshot fixture 或内置等价 fixture）覆盖
  tick/render/show/loadTemplates/sendMsg/createTeam/switchTeam/runLLM/runDemo/refreshJobs；
  附 Python 交叉核对 getElementById id ⊆ HTML id 集合、onclick 函数存在。
- 说明：DSH 亮色+暗色双主题；本控制台固定亮色（与截图一致），未做主题切换。
