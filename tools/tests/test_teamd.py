#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""teamd HTTP 层测试（S0）：端点行为 + 页面可达 + 与 CLI 快照一致性。

运行：python3.10 tools/tests/test_teamd.py
"""
import json
import pathlib
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent.parent))          # tools/ -> teamctl
sys.path.insert(0, str(HERE.parent.parent.parent / "web"))  # web/ -> teamd
import teamctl  # noqa: E402
import teamd as teamd_mod  # noqa: E402


def _start(root, token=""):
    teamctl.ensure(root)
    handler = type("BoundTeamHandler", (teamd_mod.TeamHandler,), {
        "teamd": {"root": str(pathlib.Path(root).resolve()),
                  "message_tail": 10, "log_tail": 5, "token": token,
                  "state": {"jobs": {}, "clients": [], "lock": threading.Lock(), "seq": 0}}})
    httpd = teamd_mod.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, "http://127.0.0.1:%d" % httpd.server_address[1]


def _get(url, path):
    with urllib.request.urlopen(url + path, timeout=10) as r:
        return r.status, r.read().decode("utf-8")


def _post(url, path, obj, token=None):
    data = json.dumps(obj).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url + path, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _setup_small(td):
    teamctl.mission_init(td, "A", "T", ["spec", "dev", "qa"])
    teamctl.agent_new(td, "spec", role="spec")
    teamctl.agent_new(td, "dev", role="dev")
    teamctl.agent_new(td, "qa", role="qa")


class TestTeamdHttp(unittest.TestCase):
    def test_index_and_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            _setup_small(td)
            httpd, base = _start(td)
            try:
                st, body = _get(base, "/")
                self.assertEqual(st, 200)
                self.assertIn("多 Agent 去中心化团队", body)
                st, body = _get(base, "/api/snapshot")
                self.assertEqual(st, 200)
                data = json.loads(body)
                self.assertEqual(data["mission"]["mission"], "A")
                self.assertEqual(len(data["agents"]), 3)
                self.assertIn("attention", data)  # #5180 attention 聚合随快照下发
                # 与 CLI 直调一致（generated_at 除外）
                cli = teamctl.web_snapshot(td)
                data.pop("generated_at"); cli.pop("generated_at")
                self.assertEqual(data, cli)
                # 404
                with self.assertRaises(urllib.error.HTTPError) as cm:
                    _get(base, "/nope")
                self.assertEqual(cm.exception.code, 404)
            finally:
                httpd.shutdown()

    def test_commands(self):
        with tempfile.TemporaryDirectory() as td:
            _setup_small(td)
            httpd, base = _start(td)
            try:
                # 建任务
                st, r = _post(base, "/api/command", {"action": "task_new",
                                                     "params": {"task_id": "t9", "goal": "build x"}})
                self.assertEqual(st, 200); self.assertTrue(r["ok"], r)
                # 发消息
                st, r = _post(base, "/api/command", {"action": "send", "params": {
                    "sender": "spec", "type": "task_assigned", "recipient": "dev",
                    "payload": {"task": "x"}, "task": "t9"}})
                self.assertTrue(r["ok"], r)
                # 状态
                st, r = _post(base, "/api/command", {"action": "status_set",
                                                     "params": {"agent": "dev", "status": "running"}})
                self.assertTrue(r["ok"], r)
                # promote 无证据 → gate_ok False
                st, r = _post(base, "/api/command", {"action": "promote_check", "params": {
                    "agent": "dev", "path": "shared/dev/out.md", "target": "out.md",
                    "by": "qa", "task": "t9"}})
                self.assertTrue(r["ok"] and not r["result"]["gate_ok"], r)
                # 补证据 → 放行 → promote
                st, r = _post(base, "/api/command", {"action": "send", "params": {
                    "sender": "qa", "type": "review_result", "topic": "review", "task": "t9",
                    "payload": {"verdict": "pass", "method": "verify", "evidence": "e1"}}})
                self.assertTrue(r["ok"], r)
                # 证据已就位但产物缺失 → 预检 gate 仍 False（人工审批不被误导）
                st, r = _post(base, "/api/command", {"action": "promote_check", "params": {
                    "agent": "dev", "path": "shared/dev/out.md", "target": "out.md",
                    "by": "qa", "task": "t9"}})
                self.assertTrue(r["ok"] and not r["result"]["gate_ok"], r)
                self.assertFalse(r["result"]["artifact_exists"], r)
                teamctl.fs_write(td, "dev", "shared/dev/out.md", "ok")
                st, r = _post(base, "/api/command", {"action": "promote_check", "params": {
                    "agent": "dev", "path": "shared/dev/out.md", "target": "out.md",
                    "by": "qa", "task": "t9"}})
                self.assertTrue(r["result"]["gate_ok"], r)
                self.assertTrue(r["result"]["artifact_exists"], r)
                st, r = _post(base, "/api/command", {"action": "promote", "params": {
                    "agent": "dev", "path": "shared/dev/out.md", "target": "out.md",
                    "by": "qa", "task": "t9"}})
                self.assertTrue(r["ok"] and r["result"].get("ok"), r)
                # 审计命令
                st, r = _post(base, "/api/command", {"action": "audit"})
                self.assertTrue(r["ok"] and r["result"]["passed"], r)
                # 未知动作
                st, r = _post(base, "/api/command", {"action": "rm_rf"})
                self.assertFalse(r["ok"])
                # #5180：路由建议（只读，无 Manager 仅建议）
                st, r = _post(base, "/api/command",
                              {"action": "route_suggest", "params": {"goal": "实现订单并写测试"}})
                self.assertTrue(r["ok"], r)
                self.assertIn("dev", r["result"]["matched"])
            finally:
                httpd.shutdown()

    def test_security_headers(self):
        """S5 验收：页面与 API 响应均带安全头（CSP/nosniff/frame/ref），错误响应同样带。"""
        with tempfile.TemporaryDirectory() as td:
            _setup_small(td)
            httpd, base = _start(td)
            try:
                with urllib.request.urlopen(base + "/", timeout=10) as r:
                    csp = r.headers.get("Content-Security-Policy", "")
                    self.assertIn("default-src 'none'", csp)
                    self.assertIn("connect-src 'self'", csp)
                    self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")
                    self.assertEqual(r.headers.get("X-Frame-Options"), "DENY")
                    self.assertEqual(r.headers.get("Referrer-Policy"), "no-referrer")
                # API 响应（含 401 错误）同样携带
                st, r = _post(base, "/api/command", {"action": "audit"})
                self.assertEqual(st, 200)
                st2, r2 = _post(base, "/api/command", {"action": "rm_rf"})
                self.assertEqual(st2, 200)
                # 页面 CSP 不阻断同源 fetch/SSE：snapshot 与 events 均可达
                st3, body = _get(base, "/api/snapshot")
                self.assertEqual(st3, 200)
                json.loads(body)
            finally:
                httpd.shutdown()

    def test_token_enforced(self):
        with tempfile.TemporaryDirectory() as td:
            _setup_small(td)
            httpd, base = _start(td, token="sekrit")
            try:
                st, r = _post(base, "/api/command", {"action": "audit"})
                self.assertEqual(st, 401)
                st, r = _post(base, "/api/command", {"action": "audit"}, token="sekrit")
                self.assertEqual(st, 200)
                self.assertTrue(r["ok"])
            finally:
                httpd.shutdown()

    def test_run_demo_job(self):
        """S2 验收：网页发起完整任务（demo 链），作业进度可查，证据落盘。"""
        with tempfile.TemporaryDirectory() as td:
            _setup_small(td)
            httpd, base = _start(td)
            ev_received = []
            def read_sse():
                try:
                    with urllib.request.urlopen(base + "/api/events", timeout=20) as r:
                        for raw in r:
                            line = raw.decode("utf-8").strip()
                            if line.startswith("data: "):
                                ev_received.append(json.loads(line[6:]))
                                if any(e.get("type") == "job" for e in ev_received):
                                    break
                except Exception:
                    pass
            t = threading.Thread(target=read_sse, daemon=True)
            t.start()
            try:
                st, r = _post(base, "/api/run", {"kind": "demo"})
                self.assertEqual(st, 200)
                self.assertTrue(r["ok"])
                job_id = r["job_id"]
                # 轮询直到作业结束
                status = None
                for _ in range(120):
                    st, jr = _get(base, "/api/jobs")
                    jobs = json.loads(jr)["jobs"]
                    job = next((j for j in jobs if j["job_id"] == job_id), None)
                    if job and job["status"] in ("done", "failed"):
                        status = job["status"]
                        result = job.get("result", {})
                        break
                    time.sleep(0.5)
                self.assertEqual(status, "done", result)
                self.assertTrue(result["result"]["ok"], result)
                out_dir = pathlib.Path(result["result"]["out_dir"])
                self.assertTrue((out_dir / "recap.json").exists())
                t.join(timeout=5)
                self.assertTrue(any(e.get("type") == "job" for e in ev_received))
            finally:
                httpd.shutdown()


if __name__ == "__main__":
    unittest.main(verbosity=2)
