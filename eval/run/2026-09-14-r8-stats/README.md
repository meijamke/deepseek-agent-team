# Run 2026-09-14-r8 — t-stats 消息池/订阅多步任务（P3 里程碑，无 Manager）

- 链路：spec（真实 LLM，策划+topic 分发）→ dev（真实 LLM，实现+自证）→ qa（真实 LLM，独立执行验证 PASS）
- 拓扑：**消息池/订阅**（topic=t-stats：task_assigned / status_update / review_result 全部或部分落池），
  区别于 t-ping 的纯点对点；另有移交包 spec→dev→qa（预算 8→5，访问链由运行时继承 ["dev"]——修复生效）
- 交付物：`shared/dev/stats.py`（mean/median，空序列 ValueError，偶数取中间均值）、`shared/dev/test_stats.py`（5 组断言）
- 证据：
  - `system/messages/t-stats.jsonl`（task_assigned/status_update×2/review_result，信封 id de43236dc2584418、5ec94cbae7ac4ec6、e493bf0650b14ac0、b6894dd9291f450d）
  - `system/logs/{spec,dev,qa}.jsonl`（verdict 行）
  - `system/state/handoffs/t-stats-{07970fe3d7b147f0,4c263ea6fe844bb9}.json`
- **qa 额外发现**（独立验证价值）：a3 验证命令模板本身是语法错误的 Python（try/except 不可同行分号）；
  qa 最小复现证明与实现无关，改用等价合法命令 → SPOT_CHECK_PASS + EXTRA_SEMANTICS_PASS；
  已把可执行命令修正写回 `eval/tasks/t-stats.json`（verify_commands）。
- Judge：`judge.jsonl`（R4/P3/Q4 → pass；P-1：dev 共享区写入未显式 lock——两度出现，列入 M5 工具级强制待办）
