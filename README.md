# Multi-Agent Decentralized Team (in DSH)

依据《深入理解 AI Agent》(bojieli, [ai-agent-book](https://bojieli.github.io/ai-agent-book/)) 的纲领，
在本工作区构建**多 Agent 去中心化团队**：无中心 Manager，对等成员通过共享工作区与消息协议
自主协作，具备评估、容错与持续进化能力。

- **计划**：[PLAN.md](PLAN.md)（目标拆解 / WBS / 路线图 / 验收闸门）
- **角色**：[docs/roles.md](docs/roles.md)
- **文件系统约定**：[docs/filesystem.md](docs/filesystem.md)
- **协议规范**：[docs/protocols/README.md](docs/protocols/README.md)
- **进度**：[docs/PROGRESS.md](docs/PROGRESS.md)
- **网页运行时**：[web/README.md](web/README.md)（teamd：S0–S5 部署/安全/多实例文档）

## 安装与运行

**环境要求**：Python ≥ 3.10（推荐 3.10），**无需任何第三方依赖**（全部仅用 Python 标准库）。

```bash
# 1) 克隆
git clone https://github.com/meijamke/deepseek-agent-team.git
cd deepseek-agent-team

# 2) 自检（可选但推荐）
python3.10 tools/tests/test_protocol.py     # 协议层
python3.10 tools/tests/test_member.py       # 成员执行
python3.10 tools/tests/test_audit.py        # 审计
python3.10 tools/tests/test_web.py          # 关注点/路由等 web 能力
python3.10 tools/tests/test_teamd.py        # HTTP 管理端
# 全量回归：tools/tests/run_all.sh（或逐个运行）

# 3) 初始化一个使命（创建 5 角色成员）
python3.10 tools/teamctl.py --root . mission init --mission A \
    --title "使命A·初始" --roles spec architect dev qa ops
python3.10 tools/teamctl.py --root . agent new --id spec --role spec        # 其它 4 角色同理
# 没有 --root 时默认用当前目录；mission init 会创建 members/ 与 system/ 骨架

# 4) 启动网页控制台（teamd，S0–S5 全部能力）
python3.10 web/teamd.py --root . --port 8090          # 打开 http://127.0.0.1:8090/
# 常用参数：--host 0.0.0.0   --token <secret>（作业/写操作需 X-Token）
#           --max-stale-hours 2（attention 判定阈值）   --real-llm（成员接入真实 LLM）

# 5) 命令行同样可用（协议层与网页共用同一实现）
python3.10 tools/teamctl.py --root . send --sender spec --type task_assigned \
    --recipient dev --payload '{"task":"ping"}'
python3.10 tools/teamctl.py --root . read --from dev --tail 5
python3.10 tools/teamctl.py --root . usage report          # 令牌用量
python3.10 tools/audit.py --root .                          # 审计（exit 0=通过）
python3.10 tools/probe_safety.py --root .                   # 安全探测
```

**运行形态**：`teamd` 是独立进程（ThreadingHTTPServer，纯标准库），
GET `/` `/api/snapshot` `/api/jobs` + SSE `/api/events`；POST `/api/command`（受控白名单）与
`/api/run`（成员执行）。数据全部落盘于 `--root`（不变式：网页可随时重启并从磁盘恢复，
恢复后审计、关注点、任务/配额均一致）。更完整的部署/安全/多实例说明见 [web/README.md](web/README.md)。

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

## 快速上手

```bash
# 协议层（CLI）
python3.10 tools/tests/test_protocol.py      # 协议层单元测试
python3.10 tools/teamctl.py --root . agent new --id spec --role spec
python3.10 tools/teamctl.py --root . send --sender spec --type task_assigned --recipient dev --payload '{"task":"ping"}'
python3.10 tools/teamctl.py --root . read --from dev --tail 5

# 网页运行时（直接部署，S0–S5 已实现）
python3.10 web/teamd.py --root . --port 8090   # 打开 http://127.0.0.1:8090/
```

> 说明：协议层（数据/控制平面）已实现并测试通过；`web/teamd.py` 提供网页部署运行
> （只读控制台/受控命令/成员执行/真实 LLM/使命换挡，详见 [web/README.md](web/README.md)）。
> 完整的安装与运行方式见上方「安装与运行」。
