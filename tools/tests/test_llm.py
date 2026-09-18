#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""S3 真实 LLM 成员（OpenAI 兼容适配器）测试：mock 端点 + 计量来源诚实标注。

运行：python3.10 tools/tests/test_llm.py
"""
import json
import pathlib
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = pathlib.Path(__file__).resolve()
sys.path.insert(0, str(HERE.parent.parent))          # tools -> teamctl
sys.path.insert(0, str(HERE.parent.parent.parent / "team"))  # team -> member
import teamctl  # noqa: E402
import member  # noqa: E402

ACTIONS = [
    {"op": "status", "status": "running", "progress": "from real backend"},
    {"op": "bus_send", "type": "result", "topic": "review",
     "payload": {"hello": "world"}, "task_id": "t-llm"},
    {"op": "done", "progress": "mock llm finished"},
]


class MockLLMHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n).decode("utf-8"))
        idx = len(self.server.reqs)
        action = ACTIONS[idx] if idx < len(ACTIONS) else {"op": "done"}
        self.server.reqs.append(body)
        resp = {"choices": [{"message": {"role": "assistant",
                                         "content": json.dumps(action, ensure_ascii=False)}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
        data = json.dumps(resp).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


class TestOpenAICompat(unittest.TestCase):
    def test_real_backend_runs_and_meters(self):
        with tempfile.TemporaryDirectory() as td:
            teamctl.mission_init(td, "A", "T", ["spec"])
            teamctl.agent_new(td, "spec", role="spec")
            # mock OpenAI 兼容端点
            srv = ThreadingHTTPServer(("127.0.0.1", 0), MockLLMHandler)
            srv.reqs = []
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            port = srv.server_address[1]
            try:
                llm = member.OpenAICompatLLM(
                    base_url="http://127.0.0.1:%d/v1" % port,
                    api_key="test-key", model="mock-model")
                summary = member.run_member(td, "spec", llm, max_steps=4, task_id="t-llm")
                self.assertEqual(summary["final"], "done")
                # 计量：真实 usage（15 tokens），来源诚实标注
                usage = teamctl.usage_summary(td, agent_id="spec")
                self.assertEqual(usage["total_est_tokens"], 15 * 3)
                self.assertEqual(usage["sources"], ["real:openai-compat"])
                # 后端确实收到协议化的 context/提示词
                reqs = srv.reqs
                self.assertGreaterEqual(len(reqs), 3)
                self.assertIn("多 Agent 去中心化团队", reqs[0]["messages"][0]["content"])
                self.assertIn("op", reqs[0]["messages"][0]["content"])
                self.assertIn("context", reqs[0]["messages"][1]["content"])
                # 状态最终 done
                status = teamctl.status_get(td, "spec")
                self.assertEqual(status["status"]["status"], "done")
            finally:
                srv.shutdown()

    def test_unreachable_endpoint_fails_loudly(self):
        with tempfile.TemporaryDirectory() as td:
            teamctl.mission_init(td, "A", "T", ["spec"])
            teamctl.agent_new(td, "spec", role="spec")
            llm = member.OpenAICompatLLM(
                base_url="http://127.0.0.1:1/v1", api_key="k", model="m", timeout=3)
            with self.assertRaises(member.ToolError):
                llm.act({"x": 1})

    def test_via_teamd_run_job(self):
        """S3 验收（网页链路）：POST /api/run kind=llm → 真实后端成员完成 + 计量真实标注。"""
        sys.path.insert(0, str(HERE.parent.parent.parent / "web"))
        import teamd as teamd_mod  # noqa: E402
        import urllib.request, urllib.error, time
        with tempfile.TemporaryDirectory() as td:
            teamctl.mission_init(td, "A", "T", ["dev"])
            teamctl.agent_new(td, "dev", role="dev")
            srv = ThreadingHTTPServer(("127.0.0.1", 0), MockLLMHandler)
            srv.reqs = []
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            port = srv.server_address[1]
            # start teamd
            state = {"jobs": {}, "clients": [], "lock": threading.Lock(), "seq": 0}
            handler = type("BH", (teamd_mod.TeamHandler,), {"teamd": {
                "root": td, "message_tail": 10, "log_tail": 5, "token": "", "state": state}})
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            base = "http://127.0.0.1:%d" % httpd.server_address[1]
            try:
                req = urllib.request.Request(
                    base + "/api/run",
                    data=json.dumps({"kind": "llm", "params": {
                        "agent": "dev", "base_url": "http://127.0.0.1:%d/v1" % port,
                        "api_key": "k", "model": "mock"}}).encode("utf-8"),
                    headers={"Content-Type": "application/json"}, method="POST")
                with urllib.request.urlopen(req, timeout=15) as r:
                    rid = json.loads(r.read().decode())["job_id"]
                status = None
                jobs_raw = ""
                for _ in range(60):
                    with urllib.request.urlopen(base + "/api/jobs", timeout=10) as r:
                        jobs_raw = r.read().decode()
                        jobs = json.loads(jobs_raw)["jobs"]
                        job = next((j for j in jobs if j["job_id"] == rid), None)
                        if job and job["status"] in ("done", "failed"):
                            status, result = job["status"], job.get("result", {})
                            break
                    time.sleep(0.5)
                self.assertEqual(status, "done", result)
                self.assertTrue(result["ok"], result)
                # S5 加固：作业记录不得泄露 api_key（jobs 视图不含密钥字段）
                self.assertNotIn("api_key", jobs_raw)
                self.assertEqual(result["result"]["backend"], "real:openai-compat")
                self.assertEqual(teamctl.status_get(td, "dev")["status"]["status"], "done")
                usage = teamctl.usage_summary(td, agent_id="dev")
                self.assertEqual(usage["sources"], ["real:openai-compat"])
            finally:
                httpd.shutdown(); httpd.server_close()
                srv.shutdown(); srv.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
