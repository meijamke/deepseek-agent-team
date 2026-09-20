// @meijamke/dsh-team-room — Host half
//
// 一个普通的 Cordis 插件(无任何 @deepseek-ai 依赖):
//   * 通过 ctx.provide('teamRoom', ...) 注册一个服务;
//   * 用 Typert Gateway 的 SRC 发现机制暴露 Remote 端点(feed / send):
//     - 方法第一个参数叫 `agent` → 自动匹配 typert lookups 的 'agent' 查找器
//       (调用方传 SessionId,Host 侧解析为 live Agent);
//     - 手工标记 Remote 方法(markers),等价于官方 @Remote 装饰器的产物,
//       因此不需要 TypertRemoteService / 生成器 / 装饰器。
//
// 因此本插件可以被任何 dsh 部署以普通 node_modules 包的方式解析加载,
// 无需与 dsh 的 pnpm workspace 共享依赖。

const REMOTE_METHODS = '@deepseek-ai/dsh-typert-protocol/remote-methods'

/** 插件展示名(Cordis row id 由部署 patch 的 insert.id 决定)。 */
export const name = 'team-room'

/**
 * Team Room 服务:一次 feed 返回「团队沟通墙」的全部数据;
 * 一次 send 把人类消息以 plugin 源 UserMessage 送达指定成员。
 * 参数名即协议:第一个参数 agent 由 Gateway 的 lookup 自动解析。
 */
class TeamRoomService {
  /** @param ctx - Host Cordis 上下文。 */
  constructor(ctx) {
    this.ctx = ctx
  }

  /**
   * 读取团队沟通墙(主 Agent + 各成员的实时事件流、成员、任务、消息送达状态)。
   * @param agent - live Agent(调用方传根会话 id,由 Gateway 解析)。
   * @returns JSON-safe 的 feed 快照。
   */
  async feed(agent) {
    const ctx = this.ctx
    const agents = ctx.get('agents')
    const projections = ctx.get('sessionProjections')
    const agentTeams = ctx.get('agentTeams')
    if (agents === undefined || projections === undefined) {
      return { ok: false, error: 'host services unavailable' }
    }
    const lead = agent
    const state = projections.stateOf(lead.session, 'agentTeam')
    if (state === undefined) {
      return { ok: false, error: 'agent-team projection not registered' }
    }

    const serviceReady = agentTeams !== undefined && typeof agentTeams.listMembers === 'function'
    const memberSnapshots = Array.isArray(state.members) ? state.members : []
    const tasksRaw = Array.isArray(state.tasks) ? state.tasks : []
    const messagesRaw = Array.isArray(state.messages) ? state.messages : []
    const deliveredRaw = Array.isArray(state.delivered) ? state.delivered : []
    const deliveredSet = {}
    for (const d of deliveredRaw) deliveredSet[String(d)] = true

    const leadId = String(lead.id)
    const byId = {}
    byId[leadId] = { id: leadId, name: '您（主 Agent）', role: 'lead' }
    for (const m of memberSnapshots) {
      const id = String(m.id)
      byId[id] = {
        id,
        name: typeof m.name === 'string' && m.name !== '' ? m.name : id,
        role: 'teammate',
        phase: typeof m.phase === 'string' ? m.phase : 'active',
        error: typeof m.error === 'string' ? m.error : null,
        description: typeof m.description === 'string' ? m.description : null,
        provider: typeof m.provider === 'string' ? m.provider : null,
        context: typeof m.context === 'string' ? m.context : null,
      }
    }

    let enrich = {}
    if (serviceReady) {
      try {
        const roster = agentTeams.listMembers(lead)
        if (Array.isArray(roster)) {
          const map = {}
          for (const r of roster) {
            if (r === null || typeof r !== 'object') continue
            map[String(r.id)] = {
              status: typeof r.status === 'string' ? r.status : null,
              model: typeof r.model === 'string' ? r.model : null,
              diagnostics: Array.isArray(r.diagnostics)
                ? r.diagnostics.filter((x) => typeof x === 'string')
                : [],
            }
          }
          enrich = map
        }
      } catch (error) {
        enrich = {}
      }
    }

    const leadEnrich = enrich[leadId]
    const members = []
    members.push({
      id: leadId,
      name: '您（主 Agent）',
      role: 'lead',
      status: leadEnrich && leadEnrich.status ? leadEnrich.status : 'running',
      model: leadEnrich && leadEnrich.model ? leadEnrich.model : null,
      diagnostics: leadEnrich ? leadEnrich.diagnostics : [],
    })
    for (const m of memberSnapshots) {
      const id = String(m.id)
      const e = enrich[id]
      const live = agents.get(m.id) !== undefined
      const status = e && e.status
        ? e.status
        : (m.phase === 'failed' ? 'failed' : (live ? 'idle' : 'inactive'))
      members.push({
        id,
        name: byId[id].name,
        role: 'teammate',
        status,
        phase: byId[id].phase,
        error: byId[id].error,
        description: byId[id].description,
        provider: byId[id].provider,
        context: byId[id].context,
        model: e && e.model ? e.model : null,
        diagnostics: e ? e.diagnostics : [],
      })
    }

    const items = []
    const pushItem = (type, time, name, text, meta) => {
      if (typeof time !== 'number') return
      items.push({ type, time, name, text, meta: meta || {} })
    }
    const safeEvents = (a) => {
      try {
        const list = a.session.snapshotEvents()
        return Array.isArray(list) ? list : []
      } catch (error) {
        return []
      }
    }
    const readContent = (content) => {
      if (!Array.isArray(content)) return ''
      const parts = []
      for (const block of content) {
        if (block && typeof block === 'object' && block.type === 'text' && typeof block.text === 'string') {
          parts.push(block.text)
        }
      }
      return parts.join('\n')
    }

    const leadEvents = safeEvents(lead)
    for (const ev of leadEvents) {
      if (!ev || typeof ev !== 'object') continue
      const t = ev.time
      const kind = ev.type
      const d = ev.data
      if (kind === 'user/message') {
        if (d && d.source && d.source.kind === 'team-message') continue
        if (d && Array.isArray(d.content)) pushItem('human', t, '您', readContent(d.content), { to: 'lead' })
      } else if (kind === 'assistant/message') {
        const msg = d && d.message
        if (msg && Array.isArray(msg.content)) {
          pushItem('member', t, '主 Agent', readContent(msg.content), {
            model: msg.source && typeof msg.source.model === 'string' ? msg.source.model : null,
          })
        }
      } else if (kind === 'team/member') {
        const mm = d && d.member
        if (mm && typeof mm.name === 'string') {
          const label = mm.phase === 'active'
            ? '已就绪'
            : (mm.phase === 'provisioning' ? '正在创建' : '创建失败')
          pushItem('status', t, mm.name, label + (typeof mm.error === 'string' ? '：' + mm.error : ''), {})
        }
      } else if (kind === 'team/task') {
        const task = d && d.task
        if (task && typeof task.subject === 'string') {
          pushItem('task', t, task.subject, '任务状态：' + task.status, {
            id: String(task.id),
            revision: task.revision,
          })
        }
      } else if (kind === 'team/message/queued') {
        const msg = d && d.message
        if (msg && typeof msg.senderName === 'string') {
          const target = byId[String(msg.targetId)]
          const targetName = target ? target.name : String(msg.targetId)
          pushItem('peer', t, msg.senderName, readContent(msg.content), {
            to: targetName,
            delivery: msg.delivery,
            id: String(msg.id),
            delivered: !!deliveredSet[String(msg.id)],
          })
        }
      } else if (kind === 'team/message/delivered') {
        const target = byId[String(d && d.targetId)]
        pushItem('status', t, '已送达', target ? target.name : String(d && d.targetId), {})
      }
    }

    for (const ms of memberSnapshots) {
      const memberAgent = agents.get(ms.id)
      if (memberAgent === undefined) continue
      const memberName = byId[String(ms.id)].name
      const events = safeEvents(memberAgent)
      for (const ev of events) {
        if (!ev || typeof ev !== 'object') continue
        const t = ev.time
        const kind = ev.type
        const d = ev.data
        if (kind === 'user/message') {
          if (d && d.source && d.source.kind === 'team-message') continue
          if (d && Array.isArray(d.content)) pushItem('human', t, '您', readContent(d.content), { to: memberName })
        } else if (kind === 'assistant/message') {
          const msg = d && d.message
          if (msg && Array.isArray(msg.content)) {
            pushItem('member', t, memberName, readContent(msg.content), {
              model: msg.source && typeof msg.source.model === 'string' ? msg.source.model : null,
            })
          }
        }
      }
    }

    if (items.length > 400) items.splice(0, items.length - 400)
    items.sort((a, b) => a.time - b.time)
    if (items.length > 400) items.splice(0, items.length - 400)

    const tasks = []
    for (const task of tasksRaw) {
      const owner = task.ownerId ? byId[String(task.ownerId)] : undefined
      tasks.push({
        id: String(task.id),
        subject: typeof task.subject === 'string' ? task.subject : '',
        description: typeof task.description === 'string' ? task.description : '',
        status: typeof task.status === 'string' ? task.status : 'pending',
        revision: typeof task.revision === 'number' ? task.revision : 1,
        ownerName: owner ? owner.name : null,
        blockedBy: Array.isArray(task.blockedBy) ? task.blockedBy.map(String) : [],
        writeScopes: Array.isArray(task.writeScopes) ? task.writeScopes.map(String) : [],
      })
    }

    return clean({
      ok: true,
      sessionId: leadId,
      teamId: String(state.id),
      hasTeam: memberSnapshots.length > 0,
      serviceReady,
      members,
      tasks,
      items,
      messageCount: messagesRaw.length,
    })
  }

  /**
   * 把一条人类消息写入指定 Agent 的会话(plugin 源 UserMessage)。
   * @param agent - live 根 Agent。
   * @param request - { targetId: 'lead' | 成员 SessionId, text: string }。
   */
  async send(agent, request) {
    const agents = this.ctx.get('agents')
    if (agents === undefined) return { ok: false, error: 'agents service unavailable' }
    const targetId = request && typeof request.targetId === 'string' ? request.targetId : 'lead'
    const text = request && typeof request.text === 'string' ? request.text : ''
    const trimmed = text.trim()
    if (trimmed === '') return { ok: false, error: 'empty message' }
    if (trimmed.length > 20000) return { ok: false, error: 'message too long' }
    const lead = agent
    const targetAgent = targetId === 'lead' || targetId === lead.id ? lead : agents.get(targetId)
    if (targetAgent === undefined) return { ok: false, error: '目标成员未在运行,请暂缓发送' }
    const message = {
      id: 'hm-' + Date.now().toString(36) + '-' + Math.floor(Math.random() * 0xffffff).toString(36),
      role: 'user',
      content: [{ type: 'text', text: trimmed }],
      source: { kind: 'plugin', plugin: 'team-room' },
    }
    try {
      targetAgent.followup(message)
    } catch (error) {
      return { ok: false, error: 'send failed: ' + (error && error.message ? error.message : String(error)) }
    }
    const sessionsSvc = this.ctx.get('sessions')
    if (sessionsSvc !== undefined && typeof sessionsSvc.flush === 'function') {
      try { void sessionsSvc.flush(targetAgent.session) } catch (error) { /* 忽略 */ }
    }
    return { ok: true, sessionId: String(targetAgent.id) }
  }
}

/** 递归把 undefined 归一成 null,保证返回结果通过 lossless JSON 校验。 */
function clean(value) {
  if (value === undefined || value === null) return null
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return value
  if (Array.isArray(value)) return value.map(clean)
  if (typeof value === 'object') {
    const out = {}
    for (const key of Object.keys(value)) out[key] = clean(value[key])
    return out
  }
  return null
}

// 手工声明 Remote 方法标记(等价于 @Remote 装饰器的运行期产物),
// 让 Typert Gateway 的 SRC 发现机制把 feed/send 暴露为 teamRoom 命名空间端点。
Object.defineProperty(TeamRoomService.prototype, REMOTE_METHODS, {
  configurable: true,
  value: Object.freeze({
    version: 1,
    methods: Object.freeze([
      Object.freeze({ method: 'feed', invocation: Object.freeze({ kind: 'direct' }) }),
      Object.freeze({ method: 'send', invocation: Object.freeze({ kind: 'direct' }) }),
    ]),
  }),
})

/** Cordis 插件入口:注册 teamRoom 服务(服务随本插件的 fiber 生命周期卸载)。 */
export function apply(ctx) {
  const service = new TeamRoomService(ctx)
  ctx.provide('teamRoom', service)
}
