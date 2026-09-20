# DeepSeek Agent Team

English | [中文](README.md)

DeepSeek Agent Team (`agent-team`) is an open-source implementation of a **multi-agent
decentralized team**, built by [meijamke](https://github.com/meijamke) following the
principles of [_Understanding AI Agents_](https://bojieli.github.io/ai-agent-book/)
(bojieli): **no central Manager** — peer members (spec / architect / dev / qa / ops)
collaborate autonomously over a shared workspace and a message protocol, with evaluation,
fault tolerance, and continuous evolution.

It is composed of three layers: the **protocol layer**
([`tools/teamctl.py`](tools/teamctl.py), pure Python stdlib: envelopes / handoffs /
optimistic locks / audit / usage), the **member kernel**
([`team/member.py`](team/member.py): ReAct + LLM backend), and the **runtime**
([`web/teamd.py`](web/teamd.py): single-file, build-free web console + HTTP/SSE admin
surface, S0–S5). The only dependency is the Python ≥ 3.10 standard library.

Docs: [docs/protocols/README.md](docs/protocols/README.md) (protocols) ·
[docs/roles.md](docs/roles.md) (roles) · [docs/filesystem.md](docs/filesystem.md) (filesystem) ·
[web/README.md](web/README.md) (deployment / security) · [PLAN.md](PLAN.md) (plan) ·
[docs/PROGRESS.md](docs/PROGRESS.md) (progress)

## Developer preview

This project is in **continuous iteration** (advanced round by round; see
[docs/PROGRESS.md](docs/PROGRESS.md)). **There will be compatibility-breaking changes.**
Before running, read [web/README.md](web/README.md) (deployment / security) and
[docs/protocols/README.md](docs/protocols/README.md) (protocol specification).

## Run

### Quick start (from source)

```bash
git clone https://github.com/meijamke/deepseek-agent-team.git
cd deepseek-agent-team

# Start the web console (all S0–S5 capabilities; a missing mission is
# bootstrapped automatically as the "default team")
python3.10 web/teamd.py --root . --port 8090    # open http://127.0.0.1:8090/
```

The page is **usable immediately — no manual mission init required**: on first start the
workspace root is registered as the "default team" (software template:
spec/architect/dev/qa/ops — five members). In the sidebar you can **create teams**
from templates (software / documentation / research / general — members are created and
the team is activated automatically) or with custom roles, and switch the active team
with one click — each team is an isolated workspace. If you already initialized a
mission via the CLI, `teamd` will not bootstrap again.

Useful `teamd` flags: `--host 0.0.0.0` (listen externally), `--token <secret>` (writes /
jobs require `X-Token`), `--max-stale-hours 2` (attention threshold), `--real-llm` (members
use a real LLM). Admin surface: `GET /api/snapshot`, `GET /api/jobs`, SSE `/api/events`;
`POST /api/command` (whitelisted), `POST /api/run` (member execution).

### Command line (protocol layer)

```bash
python3.10 tools/teamctl.py --root . send --sender spec --type task_assigned \
    --recipient dev --payload '{"task":"ping"}'
python3.10 tools/teamctl.py --root . read --from dev --tail 5
python3.10 tools/teamctl.py --root . usage report          # token usage
python3.10 tools/audit.py --root .                          # audit (exit 0 = pass)
python3.10 tools/probe_safety.py --root .                   # safety probe
```

### Self-check and regression

```bash
python3.10 tools/tests/test_protocol.py     # protocol layer (29 tests)
python3.10 tools/tests/test_member.py       # member execution (8)
python3.10 tools/tests/test_audit.py        # audit (9)
python3.10 tools/tests/test_drill.py        # failure drill (1)
python3.10 tools/tests/test_parallel.py     # concurrency (2)
python3.10 tools/tests/test_web.py          # web capabilities / multi-team / bootstrap (10)
python3.10 tools/tests/test_teamd.py        # HTTP admin server (7)
python3.10 tools/tests/test_llm.py          # LLM backend (3)
node tools/ui_smoke.js                      # JS smoke (DOM stub; optional real fixture arg)
# full suite: 69/69 passing
```

## Directory layout (four-zone virtual filesystem)

```
deepseek_agentteam/
├── agents/<id>/          # ① member-private: agent-card / status / progress.md / scratch/
├── shared/               # ② shared: <agent_id>/ deliverables, _coordination/ artifacts
├── skills/               # ③ built-in read-only skills (on-demand, progressive disclosure)
├── mounts/               # ④ (reserved) external mounts
├── system/
│   ├── messages/         # message bus (JSONL per topic, append-only)
│   ├── state/            # locks/ handoffs/ tasks.json
│   └── logs/             # trajectory persistence <agent_id>.jsonl (append-only)
├── eval/                 # evaluation sets (boundary + held-out + safety) — PLAN M6
├── evolution/            # continuous-evolution evidence & proposals — PLAN M7
├── docs/                 # protocols, roles, filesystem, progress
├── web/                  # teamd runtime (stdlib HTTP+SSE + single-file console)
└── tools/teamctl.py      # protocol-layer reference implementation (stdlib only)
```

## Community and support

- Submit feedback or bug reports through [GitHub Issues](https://github.com/meijamke/deepseek-agent-team/issues).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Development

- Plan & roadmap: [PLAN.md](PLAN.md); round-by-round progress: [docs/PROGRESS.md](docs/PROGRESS.md)
- Protocol specification: [docs/protocols/README.md](docs/protocols/README.md)
- Roles & member manual: [docs/roles.md](docs/roles.md) · [docs/member-manual.md](docs/member-manual.md)
- Filesystem conventions: [docs/filesystem.md](docs/filesystem.md)
- Runtime deployment / security / multi-instance: [web/README.md](web/README.md) · [docs/web-deployment.md](docs/web-deployment.md)

## License

[MIT](LICENSE)
