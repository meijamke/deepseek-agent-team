#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""D2 真并行实验 + D5 乐观锁竞争（Ch10）。

- 并行：两个成员（dev/qa）各自在自己的命名空间并发 fs_write（互不阻塞=命名空间隔离）；
  记录执行窗口，断言存在重叠时间段（真并行）且全部成功（互不冲突）。
- 竞争：同一文件被 qa 持锁时 dev 的 fs_write 返回失败，释放后重试成功（乐观锁重试语义）。

运行：python3.10 tools/tests/test_parallel.py
"""
import json
import pathlib
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import teamctl  # noqa: E402


def _setup(root):
    teamctl.agent_new(root, "dev", role="dev", capabilities=["coding", "test"])
    teamctl.agent_new(root, "qa", role="qa", capabilities=["review", "verify"])


def parallel_write_demo(root, rounds=6, pause=0.02):
    """并发写各自命名空间；返回 (ok_count, windows, overlap_bool)。"""
    windows = {}
    ok = [0, 0]
    lock = threading.Lock()

    def worker(agent, idx):
        t0 = time.monotonic()
        for i in range(rounds):
            r = teamctl.fs_write(root, agent, "shared/%s/p%d.txt" % (agent, i), "v%d-%d" % (idx, i))
            if r.get("ok"):
                with lock:
                    ok[idx] += 1
            time.sleep(pause)
        t1 = time.monotonic()
        windows[agent] = (t0, t1)

    ts = [threading.Thread(target=worker, args=("dev", 0)),
          threading.Thread(target=worker, args=("qa", 1))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    (t0a, t1a), (t0b, t1b) = windows["dev"], windows["qa"]
    overlap = min(t1a, t1b) > max(t0a, t0b)
    return ok, [(a, round(w[1] - w[0], 3)) for a, w in windows.items()], overlap


def contention_demo(root):
    """qa 持锁 -> dev fs_write 失败 -> qa 释放 -> dev 重试成功（乐观锁 CAS）。"""
    teamctl.agent_new(root, "ops", role="ops", capabilities=["gatekeeper"])
    f = "shared/dev/contended.md"
    teamctl.lock_acquire(root, f, "ops")
    r1 = teamctl.fs_write(root, "dev", f, "tries")
    teamctl.lock_release(root, f, "ops")
    r2 = teamctl.fs_write(root, "dev", f, "won")
    return {"first_attempt": {"ok": r1.get("ok"), "reason": r1.get("reason")},
            "after_release": {"ok": r2.get("ok"), "lock_version": r2.get("lock_version")},
            "final_content": teamctl.fs_read(root, f)["content"]}


class TestParallel(unittest.TestCase):
    def test_parallel_isolated_writers(self):
        with tempfile.TemporaryDirectory() as rt:
            _setup(rt)
            ok, windows, overlap = parallel_write_demo(rt, rounds=4)
            self.assertEqual(ok, [4, 4])          # 全部成功，互不阻塞
            self.assertTrue(overlap, windows)     # 执行窗口重叠 = 真并行

    def test_lock_contention_retry(self):
        with tempfile.TemporaryDirectory() as rt:
            _setup(rt)
            d = contention_demo(rt)
            self.assertFalse(d["first_attempt"]["ok"])
            self.assertIn("locked by", d["first_attempt"]["reason"])
            self.assertTrue(d["after_release"]["ok"])
            self.assertEqual(d["final_content"], "won")


if __name__ == "__main__":
    unittest.main(verbosity=2)
