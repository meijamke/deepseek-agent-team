// @meijamke/dsh-team-room — Client half (source; 由 scripts/build.mjs 打包为 client.bundle.js)
//
// 浏览器侧入口:
//   * 把手写的 Typert 贡献(teamRoom/feed、teamRoom/send)挂载到 ctx.remote;
//   * 在 conversation.view 注册「团队沟通」视图(成员状态 + 消息流 + 任务 + 直发);
//   * 通过注入 <style> 标签提供自身样式(client-modules 的 claimStyles 会接管,
//     插件卸载/HMR 时自动清理)。
//
// 注意:这是普通 client 插件,运行在 module-table 环境,`react` 由平台提供,
// 因此只 `import React from 'react'`,不能用动态插件风格的全局 facade。

import React from 'react'

const PLUGIN_ID = '@meijamke/dsh-team-room'

const CSS = [
  '.tm-room { height: 100%; min-height: 0; display: flex; flex-direction: column; gap: 12px; padding: 16px 20px 8px; color: var(--dsw-alias-label-primary); font-size: var(--dsh-content-font-size, 14px); }',
  '.tm-room * { box-sizing: border-box; }',
  '.tm-room .tm-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }',
  '.tm-room .tm-head h2 { margin: 0; font-size: 16px; font-weight: 600; }',
  '.tm-room .tm-chip { display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 999px; background: var(--dsw-alias-bg-layer-1); border: 1px solid var(--dsw-alias-border-l1); color: var(--dsw-alias-label-secondary); font-size: 12px; }',
  '.tm-room .tm-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--dsw-alias-label-secondary); }',
  '.tm-room .tm-dot.running { background: var(--dsw-alias-state-success-primary); }',
  '.tm-room .tm-dot.failed { background: var(--dsw-alias-state-error-primary); }',
  '.tm-room .tm-dot.provisioning { background: var(--dsw-alias-brand-primary); }',
  '.tm-room .tm-hint { padding: 12px 14px; border-radius: 12px; background: var(--dsw-alias-bg-layer-1); border: 1px solid var(--dsw-alias-border-l1); color: var(--dsw-alias-label-secondary); line-height: 1.6; }',
  '.tm-room .tm-feed { flex: 1 1 auto; min-height: 0; overflow-y: auto; display: flex; flex-direction: column; gap: 6px; padding-right: 4px; }',
  '.tm-room .tm-row { display: flex; gap: 8px; align-items: baseline; padding: 6px 10px; border-radius: 10px; background: var(--dsw-alias-bg-layer-1); border: 1px solid var(--dsw-alias-border-l1); }',
  '.tm-room .tm-row.human { background: var(--dsw-alias-bg-layer-2); }',
  '.tm-room .tm-row.peer { border-left: 2px solid var(--dsw-alias-brand-primary); }',
  '.tm-room .tm-row.status, .tm-room .tm-row.task { background: transparent; border: none; color: var(--dsw-alias-label-secondary); padding: 2px 10px; font-size: 12px; }',
  '.tm-room .tm-who { flex: 0 0 auto; min-width: 84px; color: var(--dsw-alias-label-secondary); font-size: 12px; }',
  '.tm-room .tm-who b { color: var(--dsw-alias-label-primary); font-weight: 600; }',
  '.tm-room .tm-body { flex: 1 1 auto; white-space: pre-wrap; word-break: break-word; line-height: 1.55; min-width: 0; }',
  '.tm-room .tm-meta { color: var(--dsw-alias-label-secondary); font-size: 11px; }',
  '.tm-room .tm-composer { display: flex; gap: 8px; padding: 8px 0 16px; align-items: flex-end; }',
  '.tm-room .tm-composer select, .tm-room .tm-composer textarea, .tm-room .tm-composer button { font: inherit; color: inherit; }',
  '.tm-room .tm-composer select { height: 34px; padding: 0 8px; border-radius: 10px; background: var(--dsw-alias-bg-layer-1); border: 1px solid var(--dsw-alias-border-l2); }',
  '.tm-room .tm-composer textarea { flex: 1 1 auto; min-height: 34px; max-height: 140px; resize: vertical; padding: 7px 10px; border-radius: 10px; background: var(--dsw-alias-bg-layer-1); border: 1px solid var(--dsw-alias-border-l2); }',
  '.tm-room .tm-composer textarea:focus, .tm-room .tm-composer select:focus { outline: none; border-color: var(--dsw-alias-brand-primary); }',
  '.tm-room .tm-composer button { height: 34px; padding: 0 14px; border-radius: 10px; border: 1px solid var(--dsw-alias-border-l2); background: var(--dsw-alias-bg-layer-1); cursor: pointer; }',
  '.tm-room .tm-composer button:disabled { opacity: 0.5; cursor: default; }',
  '.tm-room .tm-error { color: var(--dsw-alias-state-error-primary); font-size: 12px; }',
].join('\n')

// 工厂执行期间注入 <style>;client-modules 的 claimStyles 会把它标记为
// 本插件所有,卸载与 HMR 时自动移除。
const style = document.createElement('style')
style.setAttribute('data-plugin', PLUGIN_ID)
style.textContent = CSS
document.head.append(style)

// 手写的 Typert Remote 贡献。schema 用恒等 parse 即可:客户端只要求
// codec.mode === 'strict' 且 schema 提供 parse();真正的校验数据在 Host 侧完成。
const sessionIdCodec = {
  mode: 'strict',
  typeSymbol: '@deepseek-ai/dsh-session/types#SessionId',
  schema: { parse: (value) => value },
}
const jsonCodec = {
  mode: 'strict',
  typeSymbol: '@meijamke/dsh-team-room#Json',
  schema: { parse: (value) => value },
}

const CONTRIBUTION = {
  package: PLUGIN_ID,
  descriptors: [
    {
      id: PLUGIN_ID + '#teamRoom/feed',
      service: 'teamRoom',
      namespace: 'teamRoom',
      method: 'feed',
      implementation: 'feed',
      invocation: { kind: 'direct' },
      scope: { context: 'agent', wire: 'agentId' },
      parameters: [
        { name: 'agent', wire: 'agentId', source: 'lookup', lookup: 'agent', codec: sessionIdCodec },
      ],
      result: {
        mode: 'strict',
        typeSymbol: '@meijamke/dsh-team-room#FeedResult',
        schema: { parse: (value) => value },
      },
      sourceLocation: { file: 'plugins/team-room/client.src.js', line: 1, column: 1 },
    },
    {
      id: PLUGIN_ID + '#teamRoom/send',
      service: 'teamRoom',
      namespace: 'teamRoom',
      method: 'send',
      implementation: 'send',
      invocation: { kind: 'direct' },
      scope: { context: 'agent', wire: 'agentId' },
      parameters: [
        { name: 'agent', wire: 'agentId', source: 'lookup', lookup: 'agent', codec: sessionIdCodec },
        { name: 'request', wire: 'request', source: 'json', codec: jsonCodec },
      ],
      result: {
        mode: 'strict',
        typeSymbol: '@meijamke/dsh-team-room#SendResult',
        schema: { parse: (value) => value },
      },
      sourceLocation: { file: 'plugins/team-room/client.src.js', line: 1, column: 1 },
    },
  ],
}

export const inject = ['slots', 'timer']

export async function apply(ctx) {
  // 1) 挂载 Remote 命名空间(贡献注册在 ctx.remote.teamRoom)。
  const remote = ctx.get('remote')
  if (remote !== undefined && typeof remote.$mount === 'function') {
    await remote.$mount(CONTRIBUTION)
  }

  // 2) 注册「团队沟通」视图。
  function TeamRoomView(props) {
    const sessionId = props.sessionId
    const [feed, setFeed] = React.useState(null)
    const [error, setError] = React.useState(null)
    const [target, setTarget] = React.useState('lead')
    const [text, setText] = React.useState('')
    const [sending, setSending] = React.useState(false)

    const remoteOk = remote !== undefined && remote.teamRoom !== undefined

    React.useEffect(function () {
      let alive = true
      const load = function () {
        if (!remoteOk) return
        remote.teamRoom.feed(sessionId).then(function (v) {
          if (!alive) return
          setFeed(v)
          setError(null)
        }).catch(function (e) {
          if (alive) setError(String(e && e.message ? e.message : e))
        })
      }
      load()
      const stop = ctx.interval(load, 3000)
      return function () { alive = false; stop() }
    }, [sessionId, remoteOk])

    const send = function () {
      const value = text.trim()
      if (value === '' || sending) return
      setSending(true)
      remote.teamRoom.send(sessionId, { targetId: target, text: value }).then(function (r) {
        if (r && r.ok) {
          setText('')
          return remote.teamRoom.feed(sessionId).then(function (v) { setFeed(v) }).catch(function () { return null })
        }
        setError(r && r.error ? r.error : '发送失败')
        return null
      }).catch(function (e) {
        setError(String(e && e.message ? e.message : e))
      }).finally(function () { setSending(false) })
    }

    const onKey = function (e) {
      if (e && e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        send()
      }
    }

    const fmtTime = function (t) {
      if (typeof t !== 'number') return ''
      const d = new Date(t)
      const p = function (n) { return n < 10 ? '0' + n : String(n) }
      return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds())
    }

    let body
    if (!remoteOk) {
      body = React.createElement('div', { className: 'tm-hint' }, 'Remote 未挂载,团队沟通不可用。')
    } else if (feed === null) {
      body = React.createElement('div', { className: 'tm-hint' }, '正在加载团队沟通记录…')
    } else if (feed.ok === false) {
      body = React.createElement('div', { className: 'tm-hint' }, '暂不可用：' + String(feed.error || '未知原因'))
    } else {
      const members = Array.isArray(feed.members) ? feed.members : []
      const items = Array.isArray(feed.items) ? feed.items : []
      const tasks = Array.isArray(feed.tasks) ? feed.tasks : []
      const chips = members.map(function (m) {
        const dotClass = m.status === 'running' ? 'running'
          : (m.status === 'failed' ? 'failed' : (m.status === 'provisioning' ? 'provisioning' : ''))
        const title = (m.description || '') + (m.model ? ' · ' + m.model : '')
          + (m.diagnostics && m.diagnostics.length ? ' · ' + m.diagnostics.join('；') : '')
        return React.createElement('span', { key: m.id, className: 'tm-chip', title: title },
          React.createElement('span', { className: 'tm-dot ' + dotClass }),
          m.name,
          m.status === 'running' ? ' · 运行中'
            : (m.status === 'idle' ? ' · 空闲'
              : (m.status === 'inactive' ? ' · 未运行'
                : (m.status === 'provisioning' ? ' · 创建中' : ''))))
      })
      const rows = items.map(function (item, index) {
        let meta = ''
        if (item.type === 'peer') {
          meta = ' → ' + (item.meta && item.meta.to ? item.meta.to : '')
            + (item.meta && item.meta.delivered ? '（已送达）' : '')
        } else if (item.type === 'human') {
          meta = ' → ' + (item.meta && item.meta.to ? item.meta.to : '')
        }
        return React.createElement('div', { key: index, className: 'tm-row ' + item.type },
          React.createElement('span', { className: 'tm-who' },
            React.createElement('b', null, item.name),
            React.createElement('span', { className: 'tm-meta' }, ' ' + fmtTime(item.time) + meta)),
          React.createElement('div', { className: 'tm-body' }, item.text))
      })
      const options = [React.createElement('option', { value: 'lead', key: 'lead' }, '主 Agent')]
      for (const m of members) {
        if (m.role === 'teammate') options.push(React.createElement('option', { value: m.id, key: m.id }, m.name))
      }
      body = React.createElement(React.Fragment, null,
        React.createElement('div', { className: 'tm-head' },
          React.createElement('h2', null, '团队沟通'),
          chips),
        feed.hasTeam === false ? React.createElement('div', { className: 'tm-hint' },
          feed.serviceReady
            ? '当前还没有团队成员。请直接告诉主 Agent：让 TA 使用 spawn_teammate 创建成员（例如「创建两名成员：一名写代码、一名审查」）。成员加入后，本面板会自动展示所有会话消息、成员间消息、状态与任务。'
            : 'Agent Teams 服务未加载，无法使用团队沟通。') : null,
        tasks.length > 0 ? React.createElement('div', { className: 'tm-hint' },
          '任务：' + tasks.map(function (t) { return t.subject + '（' + t.status + '）' }).join('；')) : null,
        React.createElement('div', { className: 'tm-feed' },
          rows.length > 0 ? rows : React.createElement('div', { className: 'tm-hint' }, '暂无沟通记录')),
        error !== null ? React.createElement('div', { className: 'tm-error' }, error) : null,
        React.createElement('div', { className: 'tm-composer' },
          React.createElement('select', { value: target, onChange: function (e) { setTarget(e.target.value) } }, options),
          React.createElement('textarea', {
            value: text,
            placeholder: '发送给选中的 Agent（Enter 发送，Shift+Enter 换行）',
            onChange: function (e) { setText(e.target.value) },
            onKeyDown: onKey,
          }),
          React.createElement('button', {
            type: 'button',
            disabled: sending || text.trim() === '',
            onClick: send,
          }, sending ? '发送中…' : '发送')))
    }

    return React.createElement('div', { className: 'tm-room' }, body)
  }

  const slots = ctx.get('slots')
  if (slots === undefined) return
  slots.inject('conversation.view', function () {
    return slots.register(
      { name: 'conversation.view', id: 'team-room', order: 5, label: '团队沟通' },
      function (props) { return React.createElement(TeamRoomView, props) },
    )
  })
}
