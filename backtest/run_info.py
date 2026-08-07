"""
Run Information

Creates a unique ID for every backtest execution.
"""

from datetime import datetime


def generate_run_id():

    return datetime.now().strftime("RUN_%Y%m%d_%H%M%S")
