# Evolution Run 2026-09-14-r9 — 锁纪律工具化（M7 首演）

## 触发（真实运行积累的经验）

- **两次真实运行（r4/r8）**：dev 写共享区未显式 `lock`——无并发冲突（幸运），但属协议违规，
  Judge P 分两次被扣。根因：真实成员用原始 write 工具，锁纪律依赖自觉；参考运行时（member.py）自动加锁，
  但 CLI 路径没有同等待遇 → **行为漂移**。

## 变更（三层验证后落地）

| 载体（Ch9 四载体） | 变更 | 内容 |
|---|---|---|
| 程序/Harness | `teamctl fs write --path --content --agent` | **自动** lock acquire（冲突则不写）→ 写 → release；同时做**代码级**写范围硬检查（agents/<id>/、shared/<id>/，与 member.py 同语义，非提示词） |
| 知识（文档） | `docs/member-manual.md` §2 | fs write 定为共享区写规范路径；显式持锁仅用于多步场景 |
| 评估 | `eval/tasks/t-stats.json` | verify_commands 修正（顺带，见 r8） |
| 参数 | 无 | 不涉及 |

## 三层验证（Ch7/Ch9）

1. **结果层**：`tools/tests/test_protocol.py` → 20/20（新增 2 项：自动锁+范围检查、锁冲突不落盘）；
   全量回归 32/32；`audit.py` exit 0。
2. **过程层**：CLI 冒烟（临时工作区）——before：无锁直写 0 条锁记录；after：`fs write` →
   lock record v1、写入后释放、audit pass（证据见本目录 `before-after.json`）。
3. **质量层**：变更**向后兼容**（fs write 为新增路径，旧路径仍可运行，仅 Judge 扣 P 分）→
   回滚=改回手册 + 保留旧路径，无破坏性。

## 安全边界（Ch9）

- 范围检查在**代码层**（可信根 = teamctl/member/audit 运行时），不依赖成员自觉；
- `--content` 仅作为数据写入，不构成指令（证据/指令隔离）；
- 可信根不自改：本变更只新增工具+文档，未引入成员可修改可信根的通道。

## 灰度/回归

- 先以测试+临时工作区验证（本轮），旧路径保留；下次真实成员运行（r10+）观察 fs write 使用率与 P 分。
