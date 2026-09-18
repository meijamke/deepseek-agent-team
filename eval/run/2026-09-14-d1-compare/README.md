# D1 完整对照实验 · 2026-09-14（member-crash vs baseline）

> 判据：**任一成员崩溃不导致系统停摆**，且无固定 Manager 节点承担路由。
> 结果：**对照断言 PASS**（`python3.10 tools/d1_compare.py` 的退出码）

| 观测项 | (A) baseline 全员在线 | (B) member-crash 崩溃 |
|---|---|---|
| spec 完成 | done | done |
| dev 完成 | done | failed |
| qa 完成 | done | done |
| review_request（dev→qa） | 1 | 0 |
| 审核触发方式 | review_request | self-initiated: dev stale, artifact present |
| deliverable（shared/dev/stats.py） | True | True |
| 崩溃前审计 | 通过 | **stale_running 探测 FAIL（注入 3h 陈旧时间戳）** |
| 恢复后审计 | 通过 | 通过 |
| handoff 包数 | 2 | 1 |
| 用量记录 | 19 records / 2645 est-tokens | 12 records / 1394 est-tokens |

## 结论（对齐 Ch10「无中心控制者」）

- (B) 中 dev 交付后崩溃：**没有** handoff、**没有** review_request、status 停留在 running；
  qa 作为**共享文件系统 + 订阅观察者**自主复核（先 fs_list 发现产物、dev 失效、无人审核，
  再执行验证并放行）——**路由决策完全由成员做出，无任何调度节点参与**。
- 任务在崩溃条件下照常完成（qa done = done，验证代码 0，产物存在），证明「崩溃成员不阻塞其余成员」。
- 运行时仅做**存活簿记**（把崩溃成员标 failed 并恢复审计干净），该动作不参与任务路由；
  这与 F6 演练（探测）+ audit 修复构成闭环。

## 诚实边界

1. 成员由 member.py（ScriptedLLM）承载：本实验证明**协议层/控制平面**的容错性质；
   真实成员（DSH 子代理）的独立验证见 `eval/run/2026-09-14-r8-stats/`、r10 并行运行。
2. qa 的「自主发现」由成员动作序列代表（真实成员中该决策来自模型 + member-manual 的失效规则）；
   本实验验证协议允许该行为——qa 无需任何 review_request 也能拿到证据并放行。
3. 崩溃注入 = dev 进程终止（未运行 done/handoff）+ 3h 陈旧时间戳；「存活清理」为运行时簿记。

## 复现

```bash
python3.10 tools/d1_compare.py        # 缺省写入 eval/run/2026-09-14-d1-compare/
```
