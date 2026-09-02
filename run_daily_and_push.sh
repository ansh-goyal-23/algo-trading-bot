#!/bin/bash
set -uo pipefail
cd ~/algo-trading-bot || exit 1

TODAY=$(date +%Y-%m-%d)
LOG_DIR="logs"
LOG_FILE="$LOG_DIR/run_daily_${TODAY}.log"
mkdir -p "$LOG_DIR"

timeout --signal=TERM --kill-after=30s 8h venv/bin/python -u -m execution.run_daily > "$LOG_FILE" 2>&1
RUN_EXIT=$?

if [ $RUN_EXIT -eq 124 ]; then
    echo "[run_daily_and_push] WARNING: run_daily.py hit the 8h timeout and was killed — investigate for a hang." >> "$LOG_FILE"
fi

git add "$LOG_FILE" reports/ 2>/dev/null

if ! git diff --cached --quiet; then
    git commit -m "Daily run log — ${TODAY} (exit code ${RUN_EXIT})" >/dev/null 2>&1
    git push origin main >/dev/null 2>&1
    PUSH_EXIT=$?
    if [ $PUSH_EXIT -ne 0 ]; then
        echo "[run_daily_and_push] WARNING: git push failed (exit $PUSH_EXIT)" >&2
    fi
else
    echo "[run_daily_and_push] Nothing to commit for ${TODAY}."
fi

exit $RUN_EXIT
