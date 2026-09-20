# DeepSeek Agent Team

[English](README.en.md) | 中文

DeepSeek Agent Team（`agent-team`）是**多 Agent 去中心化团队**的开源实现，
由 [meijamke](https://github.com/meijamke) 依据 [《深入理解 AI Agent》](https://bojieli.github.io/ai-agent-book/)
（bojieli）的纲领构建：**无中心 Manager**，对等成员（spec / architect / dev / qa / ops）通过共享工作区
与消息协议自主协作，具备评估、容错与持续进化能力。

它由三层组成：**协议层**（[`tools/teamctl.py`](tools/teamctl.py)，纯 Python 标准库：信封 / 移交包 /
乐观锁 / 审计 / 用量）、**成员内核**（[`team/member.py`](team/member.py)：ReAct + LLM 后端）、
**运行时**（[`web/teamd.py`](web/teamd.py)：单文件无构建网页控制台 + HTTP/SSE 管理面，S0–S5）。
全部依赖仅为 Python ≥ 3.10 标准库。

文档：[docs/protocols/README.md](docs/protocols/README.md)（协议） ·
[docs/roles.md](docs/roles.md)（角色） · [docs/filesystem.md](docs/filesystem.md)（文件系统） ·
[web/README.md](web/README.md)（部署 / 安全） · [PLAN.md](PLAN.md)（计划） ·
[docs/PROGRESS.md](docs/PROGRESS.md)（进度）

## 开发者预览

项目处于**持续迭代**阶段（按「轮」推进，最近一轮见 [docs/PROGRESS.md](docs/PROGRESS.md)）。
**未来可能出现不兼容变更。** 运行前请阅读 [web/README.md](web/README.md)（部署 / 安全）
与 [docs/protocols/README.md](docs/protocols/README.md)（协议规范）。

## 运行

### 快速开始（从源码运行）

```bash
git clone https://github.com/meijamke/deepseek-agent-team.git
cd deepseek-agent-team

# 初始化一个使命（创建 5 角色成员）
python3.10 tools/teamctl.py --root . mission init --mission A \
    --title "使命A·初始" --roles spec architect dev qa ops
python3.10 tools/teamctl.py --root . agent new --id spec --role spec   # 其余 4 角色同理

# 启动网页控制台（S0–S5 全部能力）
python3.10 web/teamd.py --root . --port 8090    # 打开 http://127.0.0.1:8090/
```

`teamd` 常用参数：`--host 0.0.0.0`（对外监听）、`--token <secret>`（写操作 / 作业需
`X-Token`）、`--max-stale-hours 2`（「需关注」判定阈值）、`--real-llm`（成员接入真实 LLM）。
管理员面：`GET /api/snapshot`、`GET /api/jobs`、SSE `/api/events`；`POST /api/command`
（受控白名单）、`POST /api/run`（成员执行）。

### 命令行（协议层）

```bash
python3.10 tools/teamctl.py --root . send --sender spec --type task_assigned \
    --recipient dev --payload '{"task":"ping"}'
python3.10 tools/teamctl.py --root . read --from dev --tail 5
python3.10 tools/teamctl.py --root . usage report          # 令牌用量
python3.10 tools/audit.py --root .                          # 审计（exit 0 = 通过）
python3.10 tools/probe_safety.py --root .                   # 安全探测
```

### 自检与回归

```bash
python3.10 tools/tests/test_protocol.py     # 协议层（29 项）
python3.10 tools/tests/test_member.py       # 成员执行（8 项）
python3.10 tools/tests/test_audit.py        # 审计（9 项）
python3.10 tools/tests/test_drill.py        # 故障演练（1 项）
python3.10 tools/tests/test_parallel.py     # 并发（2 项）
python3.10 tools/tests/test_web.py          # 关注点/路由等 web 能力（6 项）
python3.10 tools/tests/test_teamd.py        # HTTP 管理端（5 项）
python3.10 tools/tests/test_llm.py          # LLM 后端（3 项）
# 全量 63/63 通过
```

## 目录结构（四区域虚拟文件系统）

```
deepseek_agentteam/
├── agents/<id>/          # ① 成员私有：agent-card / status / progress.md / scratch/
├── shared/               # ② 多成员共享：<agent_id>/ 交付物，_coordination/ 协调产物
├── skills/               # ③ 系统内置只读技能（按需加载，渐进式披露）
├── mounts/               # ④ （预留）外部挂载资源
├── system/
│   ├── messages/         # 消息总线（按 topic 分的 JSONL，只追加）
│   ├── state/            # locks/ handoffs/ tasks.json
│   └── logs/             # 轨迹持久化 <agent_id>.jsonl（只追加）
├── eval/                 # 评估集（边界集+保留集+安全集）—— 见 PLAN M6
├── evolution/            # 持续进化证据与提案 —— 见 PLAN M7
├── docs/                 # 协议、角色、文件系统、进度
├── web/                  # 网页运行时 teamd（纯标准库 HTTP+SSE+单文件控制台）
└── tools/teamctl.py      # 协议层参考实现（stdlib，仅 Python 标准库）
```

## 社区与支持

- 通过 [GitHub Issues](https://github.com/meijamke/deepseek-agent-team/issues) 提交反馈或 bug 报告。

## 参与贡献

参见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 开发

- 计划与路线图：[PLAN.md](PLAN.md)；按轮进度：[docs/PROGRESS.md](docs/PROGRESS.md)
- 协议规范：[docs/protocols/README.md](docs/protocols/README.md)
- 角色与成员手册：[docs/roles.md](docs/roles.md) · [docs/member-manual.md](docs/member-manual.md)
- 文件系统约定：[docs/filesystem.md](docs/filesystem.md)
- 运行时部署 / 安全 / 多实例：[web/README.md](web/README.md) · [docs/web-deployment.md](docs/web-deployment.md)

## 许可证

[MIT](LICENSE)
