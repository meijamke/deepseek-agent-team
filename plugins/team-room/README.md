# dsh-team-room

**人 × 多 Agent 对等沟通墙** —— 一个可热插拔的 DeepSeek Harness (Cordis) 插件。

在会话的「团队沟通」视图里,你可以:

- **互相看见**:主 Agent 与所有团队成员的会话消息、成员间消息(`team/message`)、成员状态(运行中/空闲/创建中/失败)、任务板,实时汇总在一个时间线上;
- **互相沟通**:直接给主 Agent 或任意成员发送消息(以 `plugin` 源 UserMessage 注入对方的会话,对方 Agent 下一条消息即可看到);
- **对等**:没有 Manager,成员由 lead 用 `spawn_teammate` 创建,任何人(人/agent)都可以看见并参与同一面墙。

## 架构

这是一个 **普通的 Cordis 双面插件**(宿主 `host.js` + 浏览器 `client.bundle.js`),
不依赖 `@deepseek-ai` 的任何运行时导入:

| 面 | 文件 | 说明 |
| --- | --- | --- |
| Host | `host.js` | `ctx.provide('teamRoom', ...)` 注册服务;用 Typert Gateway 的 **SRC 发现**暴露 `teamRoom/feed`、`teamRoom/send` 两个 Remote 端点(手工写 `remote-methods` 标记,等价官方 `@Remote` 装饰器运行期产物)。零第三方 import,因此任何 dsh 部署只要能把包放进 node_modules 就能加载。 |
| Client | `client.src.js` → `client.bundle.js` | `window.__ModuleLoader__.load({ id, factory })` 格式(官方 client-modules 契约);挂载手写的 Typert 贡献(`teamRoom` 命名空间),在 `conversation.view` 槽注册「团队沟通」视图;样式通过 `<style>` 标签注入,由 client-modules 的 `claimStyles` 接管清理。 |

数据源完全复用官方 `agent-team` 服务:`sessionProjections.stateOf(session, 'agentTeam')`
(成员/消息/任务/送达)+ `agentTeams.listMembers`(运行态)+ 各成员会话的事件日志。

## 安装(独立 + 热插拔)

### 方式 A:作为 profile bundle(推荐,生产)

```sh
# 在 dsh 安装目录执行,路径相对当前目录会被锚定到插件 checkout
dsh plugin add link:/绝对路径/到/plugins/team-room
```

`dsh plugin add` 会把该包加入 profile 的 `dsh.profile.bundles`
(`package.json` 声明了 `dsh.bundle.patch`,会自动接入插件行);
下一次启动 `dsh web` 即生效。

```sh
dsh plugin remove @meijamke/dsh-team-room   # 卸载
```

### 方式 B:手动 patch(适合已在运行的 GUI,零重启热插拔)

```sh
# 1) 把插件链接进 profile 的 node_modules(与 dsh 相同解析路径)
mkdir -p ~/.dsh/profiles/<profile>/node_modules/@meijamke
ln -s /绝对路径/到/plugins/team-room ~/.dsh/profiles/<profile>/node_modules/@meijamke/dsh-team-room

# 2) 在 ~/.dsh/profiles/<profile>/cordis.patch.yml 增加:
#    - insert:
#        - id: team-room
#          name: '@meijamke/dsh-team-room'
```

`patchReload: live` 会热加载该行(无需重启);删除/注释这几行即热卸载。
客户端加载需要刷新一次页面(新的 bundle 会进入 boot graph)。

## 开发

```sh
pnpm run build:client    # 重新打包 client.bundle.js(需要 esbuild,或用 ESBUILD_BIN 指定)
```

插件本身无依赖;构建脚本零依赖(仅调用 esbuild)。
产物 `client.bundle.js` 已提交,普通使用者无需构建。

## 依赖前提

Host 侧服务由 profile 组合提供,建议与官方
`agent-team-profile`/`agent-team-web-profile` 一起使用:

- `agent-team`(@deepseek-ai/dsh-experimental-agent-team)
- `tool-agent-team`(@deepseek-ai/dsh-experimental-tool-agent-team)
- 会话投影 `sessionProjections` 与 `agents`、`sessions` 服务(dsh-base 自带)

缺任一服务时,视图会显示友好提示而不是崩溃。

## 仓库

`meijamke/deepseek-agent-team` → `plugins/team-room/`
License: MIT
