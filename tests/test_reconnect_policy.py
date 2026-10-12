"""Tests for execution/reconnect_policy.py and execution/shutdown_guard.py (pure Python, no network)."""
import io
import contextlib
import threading
import time
import unittest

from execution.reconnect_policy import ReconnectPolicy
from execution import shutdown_guard as sg


def cycle(p, t, ticks, burst=0, flow=0):
    """
    One 60s staleness cycle as run_daily does it: decide, then note_attempt.
    `burst` ticks arrive instantly at the attempt (snapshot after subscribe);
    `flow` ticks arrive later in the cycle (real, sustained ticks).
    Returns (action, ticks_after).
    """
    action = p.decide(t, ticks)
    if action == "relogin":
        p.record_relogin(t)
    ticks += burst
    p.note_attempt(t, ticks)
    p.sample(t + p.settle_s + 1, ticks)      # loop iteration after the settle period
    ticks += flow
    return action, ticks


class Policy(unittest.TestCase):
    def test_first_staleness_is_a_plain_resubscribe(self):
        p = ReconnectPolicy()
        self.assertEqual(p.decide(0, 100), "resubscribe")
        self.assertEqual(p.failures, 0)

    def test_dead_feed_escalates_after_three_failures(self):
        p = ReconnectPolicy()
        acts, ticks = [], 0
        for i in range(4):
            a, ticks = cycle(p, 60.0 * (i + 1), ticks)
            acts.append(a)
        # cycle1: first-ever -> resubscribe (failures 0); 2,3 -> resubscribe (1,2); 4 -> relogin (3)
        self.assertEqual(acts, ["resubscribe", "resubscribe", "resubscribe", "relogin"])

    def test_snapshot_burst_does_not_count_as_recovery(self):
        """The 2026-10 flaw: a few snapshot ticks after every resubscribe reset the failure counter."""
        p = ReconnectPolicy()
        ticks, acts = 0, []
        for i in range(6):
            a, ticks = cycle(p, 60.0 * (i + 1), ticks, burst=40)   # 40 snapshot ticks, nothing afterwards
            acts.append(a)
        self.assertIn("relogin", acts)

    def test_sustained_ticks_after_settle_do_count_as_recovery(self):
        p = ReconnectPolicy()
        ticks = 0
        for i in range(3):
            _, ticks = cycle(p, 60.0 * (i + 1), ticks)
        self.assertEqual(p.failures, 2)
        _, ticks = cycle(p, 240.0, ticks, flow=50)       # decide=relogin(3), then ticks flow afterwards
        a, ticks = cycle(p, 300.0, ticks)                # next staleness: recovery noticed
        self.assertEqual(a, "resubscribe")
        self.assertEqual(p.failures, 0)

    def test_backoff_doubles_and_caps(self):
        p = ReconnectPolicy(base_backoff_s=300, max_backoff_s=1800, max_relogins=99)
        t, ticks, relogin_times = 0.0, 0, []
        for _ in range(400):
            t += 60
            a, ticks = cycle(p, t, ticks)
            if a == "relogin":
                relogin_times.append(t)
        gaps = [b - a for a, b in zip(relogin_times, relogin_times[1:])]
        self.assertEqual(gaps[:4], [300, 600, 1200, 1800])
        self.assertTrue(all(g == 1800 for g in gaps[3:]))

    def test_hard_cap_per_run(self):
        p = ReconnectPolicy(base_backoff_s=60, max_backoff_s=60, max_relogins=5)
        t, ticks, n, last = 0.0, 0, 0, None
        for _ in range(500):
            t += 60
            a, ticks = cycle(p, t, ticks)
            n += a == "relogin"
            last = a
        self.assertEqual(n, 5)
        self.assertEqual(last, "exhausted")

    def test_day_long_outage_is_bounded(self):
        """Old behaviour: ~119 re-logins in a 6.25h session. Now: at most max_relogins."""
        p = ReconnectPolicy()
        t, ticks, n = 9 * 3600.0, 0, 0
        for _ in range(375):          # 09:15..15:30 at one cycle per minute
            t += 60
            a, ticks = cycle(p, t, ticks)
            n += a == "relogin"
        self.assertLessEqual(n, 10)
        self.assertGreaterEqual(n, 5)

    def test_recovery_resets_backoff(self):
        p = ReconnectPolicy()
        t, ticks = 0.0, 0
        for _ in range(8):
            t += 60
            _, ticks = cycle(p, t, ticks)
        self.assertGreaterEqual(p.relogins, 1)
        t += 60
        _, ticks = cycle(p, t, ticks, flow=100)
        t += 60
        a, ticks = cycle(p, t, ticks)
        self.assertEqual(a, "resubscribe")
        self.assertEqual(p._backoff_s, p.base_backoff_s)


class Guard(unittest.TestCase):
    def run_it(self, fn):
        codes = []
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            sg.run_and_exit(fn, exit_fn=codes.append)
        return codes, buf.getvalue()

    def test_clean_return_exits_zero(self):
        codes, out = self.run_it(lambda: None)
        self.assertEqual(codes, [0])
        self.assertIn("exiting without waiting", out)

    def test_exception_exits_one(self):
        def boom():
            raise RuntimeError("x")
        codes, _ = self.run_it(boom)
        self.assertEqual(codes, [1])

    def test_system_exit_code_is_preserved(self):
        def bye():
            raise SystemExit(7)
        self.assertEqual(self.run_it(bye)[0], [7])

    def test_watchdog_fires_when_not_cancelled(self):
        codes, ev = [], threading.Event()
        def exit_fn(c):
            codes.append(c); ev.set()
        with contextlib.redirect_stdout(io.StringIO()):
            sg.start_watchdog(0.05, "t", exit_fn=exit_fn)
            self.assertTrue(ev.wait(2))
        self.assertEqual(codes, [3])

    def test_watchdog_can_be_cancelled(self):
        codes = []
        cancel = sg.start_watchdog(0.2, "t", exit_fn=codes.append)
        cancel.set()
        time.sleep(0.4)
        self.assertEqual(codes, [])

    def test_real_process_with_stuck_nondaemon_thread_exits(self):
        """End to end: a hung non-daemon thread must not keep the process alive."""
        import subprocess, sys, textwrap
        code = textwrap.dedent("""
            import threading, time
            from execution import shutdown_guard as sg
            threading.Thread(target=lambda: time.sleep(3600)).start()   # like a hung subscribe()
            sg.run_and_exit(lambda: print("done"))
        """)
        t0 = time.time()
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(time.time() - t0, 20)
        self.assertIn("done", r.stdout)

    def test_control_without_guard_would_hang(self):
        """Sanity check that the scenario above really hangs without the guard."""
        import subprocess, sys, textwrap
        code = textwrap.dedent("""
            import threading, time
            threading.Thread(target=lambda: time.sleep(3600)).start()
        """)
        with self.assertRaises(subprocess.TimeoutExpired):
            subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=3)


if __name__ == "__main__":
    unittest.main()
