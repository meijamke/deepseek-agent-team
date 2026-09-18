# Task t-stats · Spec（任务单，topic=t-stats 消息池分发附图）

> 本文件由 spec 策划并写入 `shared/_coordination/`。dev 以本单为实现依据；qa 以本单的验收标准（a1–a4）做独立验证。

## 1. 目标

实现共享工具模块 `stats`：`mean(values)` 与 `median(values)`，行为精确、含自测；并通过『消息池/订阅』协作（P3 里程碑）跑通 spec → dev → qa 全程，无中心 Manager。

## 2. 交付物（只允许这两份文件，仅标准库）

| 文件 | 内容 |
|---|---|
| `shared/dev/stats.py` | 模块，导出函数 `mean(values)`、`median(values)` |
| `shared/dev/test_stats.py` | 自测脚本：`python3.10 shared/dev/test_stats.py` 直接运行，全部断言通过并以退出码 0 结束 |

- 仅使用 Python 标准库，不引入任何第三方依赖（stdlib only）。
- 不修改除上述两份文件外的任何文件（`shared/dev/` 内其他文件亦不可动）。

## 3. 精确语义（实现必须逐条满足）

1. `mean(values)`：接受数值序列（list/tuple 等可迭代）。
   - 空序列 → 抛出 `ValueError`（例如 `mean([])` 必须抛 `ValueError`）。
   - 非空 → 返回 `sum(values) / len(values)`，结果为 `float`（例：`mean([1,2,3,4]) == 2.5`，`mean([2,4]) == 3.0`）。
2. `median(values)`：接受数值序列，**不修改传入的列表**。
   - 空序列 → 抛出 `ValueError`（`median([])` 必须抛 `ValueError`）。
   - 元素个数为奇数 → 按升序排序后返回中间元素（保持原类型，例：`median([1,2,3]) == 2`，`median([5]) == 5`）。
   - 元素个数为偶数 → 按升序排序后取中间两数的算术平均，结果为 `float`（例：`median([1,2,3,4]) == 2.5`，`median([1,2]) == 1.5`）。
3. `test_stats.py` 用例必须覆盖：空列表（mean/median 各一，断言抛 `ValueError`）、奇数个元素、偶数个元素、单元素、浮点结果类型/取值（比较用 `==` 即可，勿依赖 `type()` 细节）。
4. 两个文件均可独立被 `python3.10 -m py_compile` 编译通过。

## 4. 验收标准（对应 eval/tasks/t-stats.json 的 a1–a4）

- **a1（execution）**：`python3.10 -m py_compile shared/dev/stats.py shared/dev/test_stats.py` 退出码 0。
- **a2（execution）**：`python3.10 shared/dev/test_stats.py` 退出码 0（**须由 qa 亲跑**；用例覆盖空列表/奇数/偶数/单元素）。
- **a3（execution）**：抽查 `mean([1,2,3,4]) == 2.5`、`median([1,2,3,4]) == 2.5`、`mean([])` 抛 `ValueError`（须由 qa 亲跑）。
- **a4（holistic）**：消息链上 `task_assigned` / `status_update` / `review_result` 三类信封均至少一次经 `--topic t-stats`（消息池）收发，而非仅点对点。

## 5. 无 Manager 说明（去中心化铁律）

- 本任务**没有中心 Manager**：无人自动派活、无人自动验收。
- dev 完成实现与自测后，**必须**通过 `teamctl handoff new --task t-stats --sender dev --recipient qa --goal ...` 主动移交 qa（或至少经 `--topic t-stats` 发 `result` 信封并在移交包中注明）。
- 验证**必须由 qa 独立执行**（亲跑 a1/a2/a3 并检查 a4）；不得引用 dev 的自检输出作为通过依据。spec 只负责策划与任务单，不代验。
- 访问链（`visited_agents`）与预算（`remaining_budget`）由运行时继承，任何成员不得自行清空或修改。

## 6. 消息协议约定

- 信封类型：`task_assigned`（spec→topic）、`status_update`（各角色→topic）、`result`（dev→topic）、`review_result`（qa→topic）。
- 所有信封使用 `--topic t-stats`（消息池/订阅模式），各成员按 `agent-card.json` 中 `subscriptions` 订阅。
- 预算：dev 以 8 steps 为上限（继承自 spec 发出的移交包）；超出预算或收到 `verdict: cycle/exhausted` 时停止并上报，不得硬闯。

## 7. Accepted facts（供接手者引用）

- 本团队无 Manager；何时移交、向谁移交由成员自主决定（来源：docs/member-manual.md 第 1/10 章）。
- 交付 ≠ 验证：`result` 只表示已交付，最终闭环以 qa 的 `review_result=pass` 为准（来源：docs/member-manual.md 第 4 章铁律 2）。

## 8. Artifacts refs

- 本文件（任务单）。
- `eval/tasks/t-stats.json`（任务定义与验收标准原始出处）。
- `shared/dev/ping.py`（风格参考：极简、无第三方依赖）。
