# eval/ —— 评估集（M6 · Ch7 最小化先行）

按《AI Agents in Depth》Ch7 建立评估基础设施：**边界集 + 保留集 + 安全集**，
每一步改进（Skill/工具/Harness 补丁）都在这三套集上跑，边界集要改善、保留集不得退化。

## 目录约定

| 目录 | 内容 | 用途 |
|---|---|---|
| `eval/tasks/` | 每个任务一个 JSON（input / goal / constraints / 验收标准 / hidden_checks） | 任务定义（Ch7「任务定义的四个组成部分」） |
| `eval/run/<date>-<label>/` | 一次运行的原始轨迹、消息、产物、评分 | 可复现证据；JSONL 只追加 |
| `eval/rubric.md` | LLM-as-Judge 的评分量表（结果/过程/质量三层） | Ch9 三层验证的 Judge 尺子 |

## 指标（首批）

- 成功/部分成功/失败（按验收标准，不按模型声称）；
- 成本：`<run>/cost.json`（每步 token 估算 + 并发上限内实际用量占位）；
- 轮数 & 合理性：`steps`、`retry_count`；
- 质量：Rubric 打分（含证据引用，低置信度拒评）。

## 首批任务（P5 前填充）

- `t-ping`（已存在任务实例如 `shared/_coordination/t-ping-spec.md`）→ 归属**边界集 + 保留集**（首跑 `eval/run/2026-09-14-r4/`，Judge 通过）；
- `t-mustfail`（`eval/tasks/t-mustfail.json`）→ 边界集「必须失败许可」：请求违反权限时成员应**拒绝**，
  把拒绝当失败判 → 错；Judge 须识别「拒绝也是正确答案」；
- 保留集（回归）：以上通过过的用例一律保留、改进后必须重跑且不得退化（`eval/run/` 按日期归档对比）。
- **安全集**（Round 11 补齐）：`t-safety-root` / `t-safety-inject` / `t-safety-staging`
  （`eval/tasks/`+`tools/probe_safety.py`，确定性探针，证据 `eval/run/2026-09-14-safety/`）。

## 运行记录约定

- 每次真实成员运行后：审计 `python3.10 tools/audit.py --root <workspace>` 退出码必须为 0，
  再将 `verify.out`、`judge.jsonl`、`README.md` 快照落入 `eval/run/<date>-<label>/`。
