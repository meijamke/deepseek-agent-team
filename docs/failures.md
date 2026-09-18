# 失败模式治理（M3 · Ch10）

> 目标：让每一种多 Agent 失败模式都有**可检查的探测器**（`tools/audit.py`）与**明确的响应**。
> 原则：Agent 是拜占庭式的——不会主动报告自己的错误，所以所有防线都基于**独立证据**。

## 一、六类高频失败模式（书 Ch10）→ 我们的防线

| # | 失败模式 | 书中要点 | 探测器（audit 检查名） | 防线 | 状态 |
|---|---|---|---|---|---|
| 1 | 共享文件系统并发冲突 | 文件级冲突 + **跨文件语义冲突**；乐观锁只防前者 | `locks_released`（卡锁/未释放） | 乐观锁（版本 CAS）+ 命名空间隔离 `shared/<id>/` + 写权限硬边界；语义冲突用 `eval/` 保留集回归 + 合并点人工裁决 | ✅ 演练 F1 + **M7 工具化**（`teamctl fs write` 自动加锁+范围硬检查，r9） |
| 2 | 错误级联放大 | 转述即失真；交叉验证=独立视角重审 | `evidence_gated`（放行必须有 method+evidence；artifact 必须存在） | 提议者-审核者 + 只传 `accepted_facts`/`artifact_refs`（按引用不全文）+ 新信息判据（qa 亲自执行） | ✅ 演练 F2 |
| 3 | 同质趋同 | 同模型/脚手架 → 共因失效，多人审核≠独立证据 | `card_diversity`（warn：同构画像提示） | 角色/能力/上下文/工具区分（Agent Card 强制差异化）；预算与命名空间配额 | ✅ 演练 F3（warn 级） |
| 4 | 互相扯皮 | 目标互斥 → 对抗；运行时须预定义优先级/权限边界 | `handoff_chain`（环/僵局） + `agents_registered` 状态机 | 无中心但**所有权明确**（每产物一个 owner 命名空间）；冲突无法按规则裁决 → `needs_input` + `system/state/conflicts/` 人工仲裁 | ✅ 演练 F4（访问链重置检测）；仲裁路径定义待实战 |
| 5 | 循环失控 | 停不下来/生成千级子 Agent；预算与独立 key | `handoff_chain`（budget ≤0→exhausted）+ `stale_running` | 预算衰减 `remaining_budget`、`max_steps`、cycle 检测（运行时保留，成员不可改） | ✅ 演练 F5 |
| 6 | 理解债/认知投降 | 人的失败：交付太快，人看不懂 | （人侧）`docs/` + 每个交付物带来源 `provenance` | 交付物必须引用证据路径；`eval/rubric.md` 强制证据引用；成员手册=可读契约 | 🔶 无自动化探测器（人侧）；provenance 自动化待做 |

## 二、14 种失败模式三大类（论文《Why Do Multi-Agent LLM Systems Fail?》）

| 大类 | 我们的设计对策 |
|---|---|
| 系统设计缺陷（接口不清/职责重叠/工具配置错） | 协议 Schema 硬校验（信封/移交包/卡片）+ 角色职责表 `docs/roles.md` + 工具边界在代码层（非提示词） |
| Agent 间对齐失败（目标不一致/信息误解/操作矛盾） | handoff 以 goal+constraints+accepted_facts 显式传递；命名空间所有权；conflicts 仲裁 |
| 任务验证缺失（声称完成≠完成） | 证据门禁：`review_result=pass` 必须 method+evidence；audit `evidence_gated` 可机检 |

## 三、运行要求（Gatekeeper / ops 角色职责）

1. **每次里程碑推进前**：`python3.10 tools/audit.py --root <workspace>` 必须 exit 0；
   失败项要么修复，要么在 `docs/PROGRESS.md` 写明原因（不允许默默跳过）。
2. **故障演练（M5）**：故障注入至少覆盖六类模式各一次，记录注入→探测→响应→恢复。
3. 审计只读、纯标准库，可放入 CI/cron。

## 四、已知缺口（诚实登记）

- 模式 1 的**跨文件语义冲突**尚无自动检测：当前靠命名空间 + 保留集回归；
  计划用「单任务单写者（owner）+ worktree 式副本」升级（M8 前）。
- 模式 3 运行期多样性未量化：Agent Card 有 role/capabilities 区分，但没有「同模型共因」的运行时检查。
- 模式 6 的 provenance 报告自动化未做：目前靠人工读 docs + 证据路径。
