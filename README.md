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
