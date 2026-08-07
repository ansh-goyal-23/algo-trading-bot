#!/bin/zsh
cd ~/Documents/algo-trading-bot
source venv/bin/activate
echo "Starting paper trader at $(date)"
python -m execution.paper_trader
echo "Session ended at $(date)"
deactivate
