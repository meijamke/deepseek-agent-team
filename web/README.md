# teamd —— 多 Agent 去中心化团队的网页运行时（S0–S5）

`teamd` 是团队协议层（`tools/teamctl.py` / `team/member.py`）的**网页调用面**：
一个纯标准库的 HTTP 服务（`http.server`），零依赖、零构建，浏览器打开即是一个
「成员消息流 / 任务板 / 审批 / 审计 / 运行」控制台。只读展示走 `web_snapshot`
（零副作用聚合），全部写操作仍经过协议层的 `_check_fs_scope` / `_check_write` /
乐观锁（CAS），网页**不可能绕过协议**。

对应 Roadmap：`docs/web-deployment.md` 的 S0（只读）、S1（受控命令）、S2（成员执行）、
S3（真实 LLM）、S4（使命/安全）、S5（独立部署加固）均已实现并有测试覆盖
（`tools/tests/test_web.py` × 5、`test_teamd.py` × 5、`test_llm.py` × 3）。

## 1. 快速开始

```bash
# 本机默认：只监听 127.0.0.1，读/写均开（适合个人开发台）
python3.10 web/teamd.py --root /path/to/workspace --port 8090
# 浏览器打开 http://127.0.0.1:8090/
```

`--root` 缺省为仓库根（`web/` 上两级）。首次启动会调用 `teamctl.ensure` 补齐
`system/`、`agents/`、`shared/` 等运行时目录，不会覆盖已有内容。

## 2. 命令行选项

| 选项 | 默认 | 说明 |
|---|---|---|
| `--root` | 仓库根 | 团队工作区（含 `system/`、`agents/`、`eval/`） |
| `--host` | `127.0.0.1` | 绑定地址；对外暴露才改 `0.0.0.0` |
| `--port` | `8090` | 监听端口 |
| `--message-tail` | `10` | 快照中消息总线尾部条数 |
| `--log-tail` | `5` | 快照中每成员进度尾部条数 |
| `--token` | 空（本机免令牌） | 非空时**命令接口**（POST）需要 `Authorization: Bearer <token>` |

## 3. HTTP 接口

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/` | 无 | 控制台页面（单文件，无外链资源） |
| GET | `/api/snapshot` | 无 | 只读聚合：mission/history/agents/tasks/quotas/messages/handoffs/conflicts/usage/logs/audit/eval/deliverables（=`teamctl web_snapshot`） |
| GET | `/api/jobs` | 无 | 本实例作业列表（内存态，`params` 已剥离 `api_key`） |
| GET | `/api/events` | 无 | SSE：作业进度事件 + 15s 心跳 |
| POST | `/api/command` | `--token` | 白名单动作（`teamctl web_cmd`）：`snapshot/task_new/send/status_set/promote_check/promote/audit/probe/run_demo/run_llm/mission_switch_dry/mission_apply` |
| POST | `/api/run` | `--token` | 异步作业：`kind=demo`（完整 5 角色任务链）或 `kind=llm`（OpenAI 兼容真实成员） |

命令示例：

```bash
curl -s -X POST http://127.0.0.1:8090/api/command -H 'Content-Type: application/json' \
     -d '{"action":"audit","params":{}}'
curl -s -X POST http://127.0.0.1:8090/api/run -H 'Content-Type: application/json' \
     -d '{"kind":"llm","params":{"agent":"spec","base_url":"https://api.deepseek.com/v1",
          "api_key":"<key>","model":"deepseek-chat","max_steps":8}}'
```

## 4. 安全模型（S5 加固）

1. **默认绑定 `127.0.0.1`**：不开端口给局域网，是最强的默认值。
2. **命令鉴权**：`--token <随机串>` 后，所有写操作（POST）必须带 `Authorization: Bearer`；
   401 无副作用。
3. **密钥不落盘**：`api_key` 只进入作业 worker 线程内存，不出现在 `/api/jobs` 的
   `params`/`result` 中（有测试断言），也不写进工作区任何文件。
4. **安全响应头**：所有响应带 `Content-Security-Policy`（`default-src 'none'`，仅
   `connect-src 'self'`）、`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、
   `Referrer-Policy: no-referrer`；页面内联脚本/样式自身内联，不加载任何外部资源。
5. **只读面免令牌的边界**：`/api/snapshot`、`/api/jobs`、`/api/events` 无鉴权（浏览器
   EventSource 无法带自定义头）。若运行在不可信网络，请在反向代理（如 nginx）上加
   Basic Auth/内网 ACL，或保持 `127.0.0.1` 绑定。快照为聚合只读数据，不含密钥。
6. **人工干预点**：promote（qa/ops + evidence 门禁）、使命换挡（沙盒预演 → 确认）、
   运行成员均在 UI 上显式确认，符合「人类是唯一可修改系统边界的角色」。

## 5. 多实例与并发

- 协议层数据（任务/配额/成员状态/消息/权限）由乐观锁 CAS + 版本号保护，多个
  `teamd` 进程共享同一个 `--root` 时**不会写坏协议状态**（并发安全由
  `tools/tests/test_parallel.py` 覆盖）。
- **作业队列是进程内存态**（`/api/jobs` 只反映本实例），实例重启作业即消失；
  作业执行侧的结果会以证据形式落盘（demo → `eval/run/<date>-web-demo-NN/`，
  LLM 成员 → 工作区消息/用量 JSONL/进度日志），因此观察面应指向实际执行实例。
- 两个实例**同时**发起 demo 作业时，`eval/run` 目录的 `-NN` 序号存在极小概率竞争
  （取首个不存在目录，非原子）；可错峰发起，或按实例分配不同 `--root`。

## 6. 生产部署示例

```bash
# systemd 单元（/etc/systemd/system/teamd.service）
[Unit]
Description=multi-agent team web runtime
After=network.target
[Service]
WorkingDirectory=/srv/team
ExecStart=/usr/bin/python3.10 /srv/team/web/teamd.py --root /srv/team --host 0.0.0.0 --port 8090 --token "$(cat /etc/teamd.token)"
Restart=on-failure
[Install]
WantedBy=multi-user.target
```

> 注意：`--host 0.0.0.0` 时读取端点无鉴权，务必在上游反向代理加认证（见第 4.5 节）。

## 7. 与 DSH 的关系

`teamd` 与 DeepSeek Harness（DSH）是**两个独立运行时**，但形态对齐：

| DSH | teamd |
|---|---|
| host 进程 + Cordis 注册表 | `teamd`（持有 root + 协议层） |
| Web GUI / Run 卡片 / 审批 | `web/index.html` 控制台（成员/消息/任务/审批/审计） |
| 会话 / Session / 子代理 | task / 任务链 / `member.py` 成员 |
| 模型路由 | OpenAI 兼容端点（S3，`source_tag=real:openai-compat`） |

团队协议层不依赖 DSH；未来若需要把「团队」作为 DSH 的一个能力（DSH 主机内嵌
teamd、或在 DSH 中用 5 个 agent preset 当成员），可在不改协议层的前提下加一层
适配（S3 备选路线，见 `docs/web-deployment.md`）。
