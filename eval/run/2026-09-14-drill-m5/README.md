# Drill · 2026-09-14 — M5 故障注入演练（六场全过）

> 结论先行：**6/6 注入被守卫探测（detected）、6/6 恢复后复绿（recovered）**。
> 方法：每场在工作区副本上注入 → `tools/audit.py` 必须抓到对应检查失败 → 撤销注入 → 审计 exit 0。

| 演练 | 注入 | 探测检查 | 结果 |
|---|---|---|---|
| F1-lock-stuck | 获取锁不释放 | `locks_released` fail | ✅ |
| F2-pass-without-evidence | 审核放行却无 method/evidence | `evidence_gated` fail | ✅ |
| F3-homogeneous | 两个成员画像同构（同质趋同） | `card_diversity` warn | ✅ |
| F4-chain-reset | dev→qa 访问链被清空（Round 4 历史缺陷复现） | `handoff_chain` fail | ✅ |
| F5-budget-exhausted | `remaining_budget=0` 的移交包 | `handoff_chain` fail（verdict=exhausted） | ✅ |
| LIVE-F1 | **真实工作区**卡锁一次（非副本） | `locks_released` fail → release 复绿 | ✅ |

- 逐场明细：`<name>.json`（含注入前后完整审计报告 bad_rep/good_rep）；
- 六场汇总：`report.json`；
- F3 为 warn 级（同质趋同只能提示，由使命/角色集决定多样性，不宜判死）。

## 意义

- 守卫不是玩具：F4 复现的就是 Round 4 真实运行的 CLI 缺陷，F2 是 Ch10「假成功/级联放大」的
  拜占庭形态——两者都被**机检**抓到（不再依赖人眼）。
- 每场演练都证明「注入 → 探测 → 恢复」闭环存在，M5 无需等到 P4 再补课。

## 遗留（诚实登记）

- F6「理解债/认知投降」是**人的失败**，无自动化探测器：以 `docs/` + 证据引用要求缓解（见 eval/rubric.md）。
- 跨文件语义冲突（F1 引申）仍靠命名空间 + 保留集回归，无自动检测。
