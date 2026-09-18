# M8 起点演示 · 2026-09-14（5 角色 + 配额 + 发布守门 + 涌现日志）

> 结果：**PASS**（`python3.10 tools/m8_demo.py` exit 0；明细 `recap.json`）

- 成员（Agent Card 注册）：spec / architect / dev / qa / ops，**无 Manager**；
- 长周期多步任务 `t-m8-long`：spec → architect（设计）→ dev（实现+自测）→ qa（独立验证 evidence）→ ops（promote）；
- 资源配额：预算池 **10000.0 est-tokens**（实耗 **2835**，剩余 **7165.0**）、并发上限 **1**（按序执行满足）；
- 每步用量登记：**27** 条（estimate 标注，source=estimate），按成员分布 {'spec': 383, 'architect': 855, 'dev': 676, 'qa': 634, 'ops': 287}；
- 发布：`shared/dev/order.py` → `shared/deliverables/order.py`（ops 凭 evidence 背书 promote=True）；
- 涌现（可指认事件）：e1 topic self-created: architect published design topic (no central dispatch); e2 new information per hop: ARCHITECTURE.md -> tests -> exec evidence; e3 evidence-gated promotion by ops (role table enforced in code); e4 budget-aware: pool consumed, all members finished within pool。

## 边界说明（诚实）

- 成员由 member.py（ScriptedLLM）承载——协议层/控制平面演示；真实成员运行见 r8/r10；
- 并发上限 1 为「按序执行」的平凡满足，真并发配额在 Round 12 长周期任务中用并行成员实测；
- est-tokens 为估算值（`estimate_tokens`，≈字符/4），真实计量待 DSH 子 Agent 适配器。
