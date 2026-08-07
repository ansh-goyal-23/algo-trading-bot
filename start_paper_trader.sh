#!/bin/zsh
# Run this at 3:20 PM IST on trading days.
# No need to keep it running all day anymore.
cd ~/Documents/algo-trading-bot
source venv/bin/activate
echo "EOD Scanner started at $(date)"
python -m execution.eod_scanner
echo "Done at $(date)"
deactivate
