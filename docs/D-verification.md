# D1–D8 成功判据核验（2026-09-14 · Round 10）

> 对照 PLAN §1.1。每项给出证据指针与诚实备注；未达标项明确列出，不以模糊措辞带过。

| # | 判据 | 证据指针 | 状态 |
|---|---|---|---|
| D1 | 无中心控制者：任务路由由成员自主，无固定 Manager | 架构：`docs/roles.md`（无 Manager 角色，ops=gatekeeper）；成员自决移交对象；**完整对照实验**（`eval/run/2026-09-14-d1-compare/`）：同任务 (A) 全员在线 vs (B) dev 崩溃——B 无 review_request、qa 自主发现并放行、任务照常完成、audit 探测 stale_running→恢复；F6 演练 + LIVE 卡锁演练 | ✅（注：对照组由 member.py/ScriptedLLM 承载=协议层验证；真实成员容错另见 r8/r10） |
| D2 | 真并行：上下文独立、可并发、互不阻塞 | `tools/tests/test_parallel.py` 2/2 + `eval/run/2026-09-14-r10-parallel/evidence.json`：dev/qa 并发 8 轮 fs_write 各自命名空间，执行窗口**重叠**（0.109s 区间内），`ok_counts=[8,8]`；真实成员各自独立 DSH 子代理/独立轨迹（r4/r8 日志分区） | ✅ |
| D3 | 信息增量：交互携带可指认新信息 | 协议强制：handoff `accepted_facts[{fact, source}]`（schema 校验）；`evidence_gated` 审计——`review_result=pass` 必须 method+evidence（qa 亲自执行输出）；r8 qa 捕获模板缺陷即新信息样本 | ✅（注：schema 无名为「新增信息」的字段——以 accepted_facts/evidence 承载，语义等价） |
| D4 | 接口清晰：结构化移交包+信封+文件引用 | 三 Schema（envelope/handoff/card）+ `envelope_valid` 审计（收发双方注册）+ artifact_refs 路径引用（`evidence_gated` 校验存在） | ✅ |
| D5 | 容错闭环：环检测/预算/交叉验证/冲突治理 | `handoff_chain`（cycle/exhausted）、`locks_released`、r10 contention（乐观锁拒绝→释放→重试成功 v2）、F1–F5 演练 + 真实审计抓历史断链 | ✅ |
| D6 | 可评估：评估集/指标/Judge/边界+保留集 | `eval/REPORT-2026-09-14.md`（3 次真实运行 3/3 pass，R4.0/P3.33/Q4.0）；rubric 三层；边界集 3 用例+保留集无退化（`eval/run/2026-09-14-{r4,r7,r8}/`）；**安全集补齐 3/3**（`eval/tasks/t-safety-{root,inject,staging}.json` + `eval/run/2026-09-14-safety/`）——边界/保留/安全三套齐备 | ✅（注：n=3 小样本如实标注） |
| D7 | 可进化：经验→三层验证→知识/程序更新，可回滚 | `eval/run/2026-09-14-r9-evol/`：锁纪律经验 → `teamctl fs write`（程序载体）+ 手册（知识载体）→ 结果/过程/质量三层验证 → 向后兼容可回滚 | ✅ |
| D8 | 成本可控：token 预算/并发上限/预算感知 | **可插拔 token 计量接入**（Round 11）：`teamctl usage record/report`（`system/state/usage.jsonl` 只增）+ `estimate_tokens`（估算法，source=estimate 标注）+ 适配器接口（真实后端可注入）；handoff `budget_units∈{steps,tokens,calls}`；**资源配额** `quota_init/consume/status`（预算池 + 并发上限），member 运行时 `budget_pool_task` 耗尽即 fail | ✅（注：DSH 的 `tokenMeter` 是 Host 内 Session 服务（`measure(session)`），Python 协议层不可直连——故计量为**估算+可插拔**，不冒充真实 token；真实计量待成员迁移到 DSH 子 Agent 时经适配器接入） |

## 结论

**D1–D8 全部有可指认证据**；Round 11 已将此前三条诚实备注逐条闭合：D1 完整对照实验（✅）、
D6 安全集（✅ 3/3）、D8 token 计量（✅ 可插拔接入 + 诚实的估算标注）。剩余 M8（规模化/涌现）
为长期可选，M9 为越级项（按计划默认不启用）。
