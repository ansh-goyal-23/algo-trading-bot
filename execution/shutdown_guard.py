"""
Guarantees the unattended run actually EXITS.

Why this exists (2026-10-13): on all six days Oct 5-12 the process printed
"Run ending" at ~15:30 IST and then never exited, until run_daily_and_push.sh's
8h ``timeout`` killed it -- so the log was only committed/pushed hours late.
Cause: abandoned worker threads. neo_api_client's subscribe()/un_subscribe() can
block forever on a dead socket (see _call_with_timeout in run_daily.py), and
those workers (ThreadPoolExecutor + the SDK's own websocket threads) are
non-daemon, so interpreter shutdown waits on them indefinitely.

Fix: once main() has finished (or failed), flush the logs and ``os._exit`` -- there
is nothing left to clean up (all state is written synchronously to Supabase). A
daemon watchdog additionally force-exits if the run is still alive well past
market close, e.g. if the main thread itself is wedged.
"""
from __future__ import annotations

import os
import sys
import threading
import traceback


def hard_exit(code: int = 0, exit_fn=os._exit) -> None:
    """Flush stdout/stderr, then terminate immediately (skipping thread joins)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    exit_fn(code)


def _exit_code_from_system_exit(e: SystemExit) -> int:
    if e.code is None:
        return 0
    if isinstance(e.code, int):
        return e.code
    print(e.code, file=sys.stderr)
    return 1


def run_and_exit(main_fn, exit_fn=os._exit) -> None:
    """Run main_fn(); always finish with a hard exit (0 ok, 1 on unhandled error)."""
    try:
        main_fn()
        code = 0
    except SystemExit as e:
        code = _exit_code_from_system_exit(e)
    except BaseException:
        traceback.print_exc()
        code = 1
    print(f"[shutdown_guard] main() finished (exit code {code}) — exiting without waiting for stray threads.")
    hard_exit(code, exit_fn)


def start_watchdog(seconds: float, label: str = "run", exit_fn=os._exit, exit_code: int = 3):
    """
    Start a daemon thread that force-exits the process after ``seconds`` unless
    cancelled. Returns the threading.Event; set() it to cancel.
    """
    cancel = threading.Event()

    def _watch():
        if cancel.wait(seconds):
            return
        print(f"\n[shutdown_guard] 🔴 watchdog: {label} still running {seconds:.0f}s after start — "
              f"force-exiting (something is hung).")
        hard_exit(exit_code, exit_fn)

    threading.Thread(target=_watch, name="shutdown-watchdog", daemon=True).start()
    return cancel
