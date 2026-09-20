#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""teamd —— 多 Agent 去中心化团队的网页运行时（Roadmap S0–S5）。

设计原则（与 docs/web-deployment.md 一致）：
  - 协议层不动：teamd 只是 teamctl.py / member.py 的另一个调用面；
  - 浏览器只发命令，不写文件；所有写操作仍过 _check_fs_scope / _check_write / 乐观锁；
  - 纯标准库（http.server），无构建步骤；页面为 web/index.html（原生 JS）。

路线完成情况：
  S0 只读控制台 —— GET / 仪表盘、GET /api/snapshot（web_snapshot 聚合）；
  S1 受控命令 —— POST /api/command（白名单 web_cmd，可选 Bearer token）；
  S2 成员执行 —— POST /api/run（kind=demo 完整任务链，作业状态 + SSE 推送）；
  S3 真实 LLM —— POST /api/run（kind=llm，OpenAI 兼容端点 → MemberRuntime 记账）；
  S4 使命/安全 —— snapshot 含 mission/audit/usage/eval，命令含 mission_switch_dry/apply/probe；
  S5 加固 —— 安全响应头/CSP、--token、--host 绑定、部署文档 web/README.md。

用法：
    python3.10 web/teamd.py --root /path/to/workspace --port 8090
    # 对外暴露建议：--host 0.0.0.0 --token <随机串>
"""
import argparse
import json
import pathlib
import queue
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
import teamctl  # noqa: E402

# S5 加固：全部响应附安全头；页面为单文件（无外链资源），CSP 允许内联脚本/样式、仅同源连接。
SECURITY_HEADERS = (
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
    ("Content-Security-Policy",
     "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
     "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'"),
)

# 多团队工作区：这些动作作用于工作区根（注册表），其余命令作用于 active 团队根。
TEAM_ACTIONS = frozenset({"team_templates", "team_list", "team_create", "team_switch"})


class TeamHandler(BaseHTTPRequestHandler):
    server_version = "teamd/0.1"
    teamd = None  # 由 serve() 注入（含 root/options）

    # ---------------------------------------------------------------- helpers

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in SECURITY_HEADERS:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _err(self, status, message):
        self._json({"ok": False, "error": message}, status=status)

    def _body_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise ValueError("invalid JSON body")

    def log_message(self, fmt, *args):  # 安静化（默认打到 stderr 的访问日志改为可读行）
        sys.stderr.write("[teamd %s] %s\n" % (self.address_string(), fmt % args))

    # ---------------------------------------------------------------- GET

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/":
                self._serve_index()
            elif path == "/api/snapshot":
                self._json(teamctl.web_snapshot(self._team_root(),
                                                message_tail=self.teamd.get("message_tail", 10),
                                                log_tail=self.teamd.get("log_tail", 5),
                                                workspace_root=self._ws_root()))
            elif path == "/api/jobs":
                st = self.teamd["state"]
                jobs = sorted(st["jobs"].values(), key=lambda j: j["job_id"])
                self._json({"jobs": jobs})
            elif path == "/api/events":
                self._events()
            else:
                self._err(404, "no such endpoint: %s" % path)
        except Exception as e:  # noqa: BLE001 —— 服务不因单次请求崩溃
            self._err(500, "%s: %s" % (type(e).__name__, e))

    def _events(self):
        """SSE 推送：任务作业进度（job 事件）+ 15s 心跳。"""
        st = self.teamd["state"]
        q = queue.Queue(maxsize=200)
        with st["lock"]:
            st["clients"].append(q)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                try:
                    ev = q.get(timeout=15)
                    payload = b"data: " + json.dumps(ev, ensure_ascii=False).encode("utf-8") + b"\n\n"
                except queue.Empty:
                    payload = b": ping\n\n"
                self.wfile.write(payload)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with st["lock"]:
                if q in st["clients"]:
                    st["clients"].remove(q)

    def _ws_root(self):
        """多团队工作区根（--root，注册表所在）。"""
        return self.teamd["root"]

    def _team_root(self):
        """当前请求的命令作用根：active 团队（default=工作区根）。"""
        return teamctl.team_effective_root(self._ws_root())

    def _serve_index(self):
        page = HERE / "index.html"
        body = page.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in SECURITY_HEADERS:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    # ---------------------------------------------------------------- POST（S1 受控命令）

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/command":
                self._command()
            elif path == "/api/run":
                self._run()
            else:
                self._err(404, "no such endpoint: %s" % path)
        except Exception as e:  # noqa: BLE001
            self._err(500, "%s: %s" % (type(e).__name__, e))

    def _require_token(self):
        tok = self.teamd.get("token") or ""
        if not tok:
            return True
        auth = self.headers.get("Authorization") or ""
        if auth == "Bearer " + tok:
            return True
        self._err(401, "unauthorized (missing/invalid token)")
        return False

    def _command(self):
        if not self._require_token():
            return
        try:
            body = self._body_json()
        except ValueError as e:
            self._err(400, str(e))
            return
        action = body.get("action")
        params = body.get("params") or {}
        run_root = self._ws_root() if action in TEAM_ACTIONS else self._team_root()
        res = teamctl.web_cmd(run_root, action, params)
        self._json(res)

    def _run(self):
        """S2/S3：网页发起任务运行（异步作业 + SSE 进度）。kind: demo | llm。"""
        if not self._require_token():
            return
        try:
            body = self._body_json()
        except ValueError as e:
            self._err(400, str(e))
            return
        kind = body.get("kind")
        params = body.get("params") or {}
        if kind not in ("demo", "llm"):
            self._err(400, "unknown run kind %r (allowed: demo, llm)" % kind)
            return
        job_id = self._spawn_job(kind, params)
        self._json({"ok": True, "job_id": job_id})

    def _spawn_job(self, kind, params=None):
        params = dict(params or {})
        # S5 加固：api_key 只进入 worker 线程内存，不落在作业记录 /api/jobs 里。
        api_key = params.pop("api_key", None)
        st = self.teamd["state"]
        with st["lock"]:
            st["seq"] += 1
            job_id = "job-%06d" % st["seq"]
        job = {"job_id": job_id, "kind": kind, "params": params, "status": "queued",
               "created_at": teamctl.now()}
        st["jobs"][job_id] = job
        self._publish({"type": "job", "job": dict(job)})
        root = teamctl.team_effective_root(self.teamd["root"])  # 记录发起时的 active 团队

        def worker():
            job["status"] = "running"
            job["started_at"] = teamctl.now()
            self._publish({"type": "job", "job": dict(job)})
            try:
                work_params = dict(params)
                if api_key is not None:
                    work_params["api_key"] = api_key
                if kind == "llm":
                    res = teamctl.web_cmd(root, "run_llm", work_params)
                else:
                    res = teamctl.web_cmd(root, "run_demo", {})
                job["result"] = res
                inner = res.get("result") or {}
                job["status"] = "done" if (res.get("ok") and inner.get("ok", True)) else "failed"
            except Exception as e:  # noqa: BLE001
                job["status"] = "failed"
                job["result"] = {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}
            job["ended_at"] = teamctl.now()
            self._publish({"type": "job", "job": dict(job)})

        threading.Thread(target=worker, daemon=True).start()
        return job_id

    def _publish(self, ev):
        st = self.teamd["state"]
        with st["lock"]:
            for q in list(st["clients"]):
                try:
                    q.put_nowait(ev)
                except queue.Full:
                    pass


def serve(root, host="127.0.0.1", port=8090, message_tail=10, log_tail=5, token=""):
    # 免初始化引导：缺使命时按模板登记默认团队 + 每角色成员（clone → 启动 → 网页即用）
    teamctl.ensure_console(root)
    root = str(pathlib.Path(root).resolve())
    state = {"jobs": {}, "clients": [], "lock": threading.Lock(), "seq": 0}
    handler = type("BoundTeamHandler", (TeamHandler,), {"teamd": {
        "root": str(pathlib.Path(root).resolve()),
        "message_tail": message_tail, "log_tail": log_tail, "token": token,
        "state": state,
    }})
    httpd = ThreadingHTTPServer((host, port), handler)
    sys.stderr.write("teamd listening on http://%s:%d/ (root=%s%s)\n"
                     % (host, port, pathlib.Path(root).resolve(),
                        ", token required for commands" if token else ""))
    httpd.serve_forever()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="teamd", description="团队网页运行时（S0 只读控制台 → S1 受控命令）")
    ap.add_argument("--root", default=None, help="工作区根目录（默认：web/ 上两级 = 仓库根）")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--message-tail", type=int, default=10)
    ap.add_argument("--log-tail", type=int, default=5)
    ap.add_argument("--token", default="", help="命令接口的可选 Bearer 令牌（空=本机免令牌）")
    args = ap.parse_args(argv)
    root = args.root or str(HERE.parent)
    serve(root, args.host, args.port, args.message_tail, args.log_tail, args.token)


if __name__ == "__main__":
    main()
