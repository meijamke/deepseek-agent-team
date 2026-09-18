# Run 2026-09-14-r4 —— t-ping 边界集首跑（q=独立验证）

- 任务定义：`eval/tasks/t-ping.json`（边界集，set=boundary）
- 链路：spec（发起）→ dev（实现+自证）→ qa（独立执行验证，PASS）→ spec（review_result）
- 证据：
  - `verify.out`：qa 自产执行证据（REVIEW_PASS: pong；py_compile exit 0）
  - `system/logs/qa.jsonl`：verdict 日志（review=pass, method=execution）
  - `system/messages/direct.jsonl`：`result`（dev→spec）与 `review_result`（qa→spec, id 61b154f904424a28）
  - `system/state/handoffs/t-ping-c170f0345a9c447f.json`：dev→qa 移交包（预算 4.0）
- Judge：`judge.jsonl`（R=4 / P=3 / Q=4，verdict pass；P=3 因 dev 共享区写入未显式加锁，
  无冲突但属协议瑕疵，记录为 M5 关注项）
- 本次运行同时暴露并修复：CLI `--visited` 缺省绕过访问链继承（`split_visited` + 回归测试，
  见 tools/tests/test_protocol.py `test_handoff_chain_inherits_registry_when_omitted`）。
