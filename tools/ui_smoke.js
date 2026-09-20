// DOM-stub UI 冒烟：以真实 snapshot fixture 驱动 web/index.html 的渲染与关键动作。
// 用法：python3.10 -c "...生成 fixture..." 已由上层完成；node tools/ui_smoke.js /tmp/fixture.json
// 覆盖：tick/render/show/loadTemplates/sendMsg/createTeam/switchTeam/runLLM/runDemo/refreshJobs。
const fs = require('fs');
const html = fs.readFileSync('/home/weiyuanxin/deepseek_agentteam/web/index.html', 'utf8');
const fixturePath = process.argv[2] || '/tmp/fixture.json';
const DEFAULT_FIXTURE = {
  generated_at: '2026-09-20T01:00:00.000Z', root: '.', workspace_root: '.',
  mission: { mission: 'default', title: '默认团队', roles: ['spec', 'architect', 'dev', 'qa', 'ops'],
             revision: 1 },
  teams: { active: 'default', teams: [] },
  agents: ['spec', 'architect', 'dev', 'qa', 'ops'].map(r => ({
    agent_id: r, name: r, role: r, description: '', tools: [], skills: [],
    subscriptions: [], status: 'idle', updated_at: '', progress_tail: [],
    usage_total_tokens: 0, usage_records: 0 })),
  tasks: [], messages: [], handoffs: [], conflicts: [], logs: {}, eval_runs: [],
  deliverables: ['shared/spec/ping.md'],
  audit: { passed: true, fail: 0, warn: 0, checks: [{ name: 'card_role_known', status: 'pass', title: 'x' }] },
  usage: { total_est_tokens: 0, records: 0, sources: ['estimate'] },
  attention: [], quotas: {}, mission_history: [],
};
let fixture;
try { fixture = JSON.parse(fs.readFileSync(fixturePath, 'utf8')); }
catch (e) { fixture = DEFAULT_FIXTURE; console.error('(fixture missing, using built-in DEFAULT_FIXTURE)'); }
const templates = { ok: true, result: { templates: [
  { id: 'software', name: '软件开发团队', roles: ['spec', 'architect', 'dev', 'qa', 'ops'] },
  { id: 'documentation', name: '文档创作团队', roles: ['writer', 'editor', 'reviewer', 'publisher'] },
  { id: 'research', name: '研究分析团队', roles: ['researcher', 'analyst', 'critic', 'summarizer'] },
  { id: 'general', name: '通用协作团队', roles: ['planner', 'executor', 'reviewer'] },
] } };
const calls = [];
let last = null; // 最近一次 POST /api/command 或 /api/run 的 body
function makeEl(id) {
  const el = {
    id, value: '', textContent: '', innerHTML: '', className: '', hidden: false,
    dataset: { view: id }, checked: false, scrollTop: 0, scrollHeight: 100,
    options: [], style: {},
    classList: { toggle() {}, add() {}, remove() {}, contains() { return false; } },
    appendChild() {}, removeChild() {}, addEventListener() {}, remove() {}, focus() {},
  };
  return el;
}
const els = new Map();
function getEl(id) { if (!els.has(id)) els.set(id, makeEl(id)); return els.get(id); }
const documentStub = {
  getElementById: getEl,
  querySelectorAll: () => [],
  createElement: () => makeEl('x'),
  body: makeEl('body'),
};
async function fetchStub(url, opts) {
  let bodyTxt = null;
  if (opts && opts.body) { bodyTxt = JSON.parse(opts.body); if (/\/api\/(command|run)/.test(url)) last = bodyTxt; }
  calls.push({ url, body: bodyTxt });
  let payload = { ok: true, jobs: [] };
  if (url === '/api/snapshot') payload = fixture;
  else if (url === '/api/jobs') payload = { jobs: [] };
  else if (url === '/api/command' && bodyTxt && bodyTxt.action === 'team_templates') payload = templates;
  else if (url === '/api/command') payload = { ok: true, result: { ok: true } };
  else if (url === '/api/run') payload = { ok: true, job_id: 'job-stub' };
  return { ok: true, json: async () => payload, text: async () => JSON.stringify(payload) };
}
class EventSourceStub { constructor(u) { this.url = u; this.onmessage = null; this.onerror = null; } close() {} }
const confirmStub = () => true;
const scriptBody = html.split('<script>')[1].split('</script>')[0];
const makeApp = new Function('document', 'fetch', 'EventSource', 'setInterval', 'setTimeout', 'confirm',
  scriptBody + '\n;return {tick,render,show,cmd,sendMsg,runDemo,runLLM,refreshJobs,loadTemplates,createTeam,switchTeam,esc,gv};');
const app = makeApp(documentStub, fetchStub, EventSourceStub, () => 0, (fn) => { fn(); }, confirmStub);
const out = [];
function ok(name, cond, extra = '') { out.push((cond ? 'ok  ' : 'FAIL') + ' ' + name + (extra ? ' | ' + extra : '')); if (!cond) process.exitCode = 1; }
(async () => {
  await app.tick();
  const teamsHtml = getEl('teams').innerHTML;
  ok('tick/render teams', teamsHtml.includes('default') || teamsHtml.includes('team'), teamsHtml.slice(0, 40));
  ok('render agents list', getEl('agents').innerHTML.includes('spec') || getEl('agents').innerHTML.length > 0);
  ok('render mission chip', getEl('mission').textContent.includes('使命') || getEl('mission').textContent.includes('default'));
  app.show('ops');
  ok('show ops no throw', true);
  app.show('audit');
  ok('show audit no throw', true);
  await app.loadTemplates();
  ok('loadTemplates options', getEl('t_template').innerHTML.includes('software'));
  getEl('c_sender').value = 'dev';
  getEl('c_type').value = 'task_assigned';
  getEl('c_payload').value = '{"task":"ping"}';
  getEl('c_recipient').value = '';
  await app.sendMsg();
  ok('sendMsg action', last && last.action === 'send' && last.params.sender === 'dev', JSON.stringify(last));
  getEl('t_template').value = 'software';
  await app.createTeam();
  ok('createTeam action', last && last.action === 'team_create' && last.params.template === 'software', JSON.stringify(last));
  await app.switchTeam('software');
  ok('switchTeam action', last && last.action === 'team_switch' && last.params.team === 'software', JSON.stringify(last));
  getEl('l_agent').value = 'dev';
  await app.runLLM();
  ok('runLLM action', last && last.kind === 'llm' && last.params.agent === 'dev', JSON.stringify(last));
  await app.runDemo();
  ok('runDemo action', last && last.kind === 'demo', JSON.stringify(last));
  await app.refreshJobs();
  ok('refreshJobs no throw', true);
  console.log(out.join('\n'));
  console.log(process.exitCode ? 'SMOKE_FAIL' : 'ALL_OK');
})();
