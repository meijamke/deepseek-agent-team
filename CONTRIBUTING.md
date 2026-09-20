# 参与贡献（CONTRIBUTING）

感谢对 `agent-team` 的关注！本项目是一个多 Agent 去中心化团队的协议层与运行时实现，
按「轮（Round）」迭代推进（见 [docs/PROGRESS.md](docs/PROGRESS.md)）。

## 如何提 PR

1. Fork 本仓库 → 新建功能分支（`feature/xxx` 或 `fix/xxx`）。
2. 修改代码，并为改动**补充或调整测试**（`tools/tests/test_*.py`）。
3. 本地运行全部回归，确保通过（当前基线 **63/63**）：

   ```bash
   for t in test_protocol test_member test_audit test_drill test_parallel test_web test_teamd test_llm; do
     python3.10 tools/tests/$t.py || exit 1
   done
   python3.10 -m py_compile tools/teamctl.py web/teamd.py tools/audit.py tools/probe_safety.py
   ```

4. 修改协议层 / 运行时后，请额外执行：
   - `python3.10 tools/audit.py --root .`（应 exit 0）
   - `python3.10 tools/probe_safety.py --root .`（安全探测全通过）
5. 提交信息说明「改了什么 + 为什么 + 验证证据」，并附上测试输出。

## 编码约定

- **仅用 Python 标准库**（`teamctl.py` / `teamd.py` 是纯 stdlib 实现），不要引入第三方依赖。
- 保持「零副作用只读」与「写操作可恢复」不变式；网页快照聚合函数不得产生写副作用。
- 所有协议对象（信封 / 移交包 / 成员卡 / 任务）必须有 JSON Schema 校验与对应测试。
- 文档使用中文，证据优先：可复现产物与测试输出优先于文字描述。

## 行为准则

保持友善、证据优先、对等协作——与项目自身「无中心 Manager」的价值观一致。
