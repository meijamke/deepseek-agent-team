# Run 2026-09-14-r10-parallel — D2 真并行 + D5 乐观锁竞争（实验）

- 方法：两个真实线程（角色 dev/qa）各自 `fs_write` 自己命名空间（rounds=8，pause=10ms），
  记录每线程执行窗口；再构造同一文件竞争（ops 持锁 → dev 写失败 → 释放 → dev 重试成功）。
- 结果（`evidence.json`）：
  - 并行：`ok_counts=[8,8]`（全部成功，互不阻塞=命名空间隔离），窗口 dev=0.109s / qa=0.109s，
    **overlap=true**（真并行）；
  - 竞争：first_attempt `ok=false`（already locked by ops v1）→ after_release `ok=true`（lock_version=2）→
    final_content="won"（乐观锁 CAS：拒绝→重读/重试→成功）。
- 意义：Ch10「共享空间并发冲突」两条路径都有了可复现证据——**命名空间隔离避免竞争** 与
  **乐观锁处理竞争**；真实 LLM 成员为独立 DSH 子代理（独立上下文），即使同步调度也满足上下文独立（D2）。
- 备注：DSH 会话限制同轮单子代理（并发上限外部约束，见 cost.json 记录）。
