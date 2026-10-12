"""
Decision logic for the websocket-staleness loop in execution/run_daily.py.

Why this exists (2026-10-13): during the Kotak `mlhsm` market-data outage
(2026-10-05..13) the old inline logic did a full ``login()`` every ~3 minutes all
session -- ~119 forced re-logins per dead day -- because
  (a) nothing limited how often it escalated, and
  (b) "did the last attempt recover?" was judged by ``total_tick_count`` having
      moved at all, so the handful of snapshot ticks that arrive right after any
      (re)subscribe reset the failure counter and made a dead feed look alive.

This module is pure Python (no I/O, no clocks of its own) so it can be unit tested:

  * Recovery is judged on ticks that arrive AFTER a settle period following the
    attempt (``settle_s``), and must number at least ``recovery_ticks``. The initial
    snapshot burst is therefore ignored.
  * Full re-login is limited by exponential backoff (``base_backoff_s`` doubling up
    to ``max_backoff_s``) and a hard per-run cap (``max_relogins``).
  * Plain unsubscribe/subscribe retries still happen every cycle below the failure
    threshold, exactly as before.

Usage (once per 60 s staleness cycle)::

    action = policy.decide(t, ticks)      # "resubscribe" | "relogin" | "wait" | "exhausted"
    ... do it ...
    if action == "relogin": policy.record_relogin(t)
    policy.note_attempt(t, ticks)
    # and every loop iteration:
    policy.sample(t, ticks)
"""
from __future__ import annotations


class ReconnectPolicy:
    def __init__(
        self,
        fail_threshold: int = 3,
        base_backoff_s: float = 300.0,
        max_backoff_s: float = 1800.0,
        max_relogins: int = 10,
        settle_s: float = 20.0,
        recovery_ticks: int = 5,
    ):
        self.fail_threshold = fail_threshold
        self.base_backoff_s = base_backoff_s
        self.max_backoff_s = max_backoff_s
        self.max_relogins = max_relogins
        self.settle_s = settle_s
        self.recovery_ticks = recovery_ticks

        self.failures = 0
        self.relogins = 0
        self.skipped = 0            # cycles where a relogin was wanted but held back
        self._backoff_s = base_backoff_s
        self._next_relogin_at = 0.0
        self._attempted = False
        self._attempt_t = 0.0
        self._ticks_at_attempt = 0
        self._ticks_settled: int | None = None

    # ── recovery judgement ───────────────────────────────────────────────
    def note_attempt(self, t: float, ticks: int) -> None:
        """Call at the end of every staleness cycle (whatever action was taken)."""
        self._attempted = True
        self._attempt_t = t
        self._ticks_at_attempt = ticks
        self._ticks_settled = None

    def sample(self, t: float, ticks: int) -> None:
        """Call every loop iteration; captures the tick count once the settle time passes."""
        if self._attempted and self._ticks_settled is None and t - self._attempt_t >= self.settle_s:
            self._ticks_settled = ticks

    def recovered(self, ticks: int) -> bool:
        """Did real (non-snapshot) ticks flow after the previous attempt?"""
        if not self._attempted:
            return True  # first-ever staleness event: nothing failed yet
        baseline = self._ticks_settled if self._ticks_settled is not None else self._ticks_at_attempt
        return ticks - baseline >= self.recovery_ticks

    # ── decision ─────────────────────────────────────────────────────────
    def decide(self, t: float, ticks: int) -> str:
        if self.recovered(ticks):
            self.failures = 0
            self._backoff_s = self.base_backoff_s
        else:
            self.failures += 1

        if self.failures < self.fail_threshold:
            return "resubscribe"
        if self.relogins >= self.max_relogins:
            self.skipped += 1
            return "exhausted"
        if t < self._next_relogin_at:
            self.skipped += 1
            return "wait"
        return "relogin"

    def record_relogin(self, t: float) -> None:
        """Count a full re-login attempt (successful or not) and schedule the next allowed one."""
        self.relogins += 1
        self._next_relogin_at = t + self._backoff_s
        self._backoff_s = min(self._backoff_s * 2, self.max_backoff_s)

    def seconds_until_relogin(self, t: float) -> float:
        return max(0.0, self._next_relogin_at - t)

    def summary(self) -> str:
        return (f"failures={self.failures} relogins={self.relogins}/{self.max_relogins} "
                f"held_back={self.skipped}")
