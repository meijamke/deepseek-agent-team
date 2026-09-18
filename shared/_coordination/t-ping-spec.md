# Task t-ping · Spec（移交包附图：任务单）

- **Goal**：实现一个最小 ping 端点模块，供后续 http server（不属于本任务）使用。
- **验收标准**：
  1. `shared/dev/ping.py` 存在；
  2. 内容包含函数 `def ping():` 返回字符串（含 "pong"）；
  3. 无语法错误（`python3.10 -m py_compile` 通过）。
- **Constraints**：只写 `shared/dev/`；不改动其他任何文件；使用 teamctl 协议完成通信与交接。
- **Accepted facts**：
  - 本团队无 Manager；你自主决定何时移交/请求验证（来源：docs/roles.md）。
  - 交付不等于验证：你的 `result` 只表示交付；最终验证由独立审核者（qa）以证据完成。
- **Artifacts refs**：本文件。
