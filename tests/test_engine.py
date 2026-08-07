from backtest.config import BacktestConfig
from backtest.engine import BacktestEngine
from backtest.trade_logger import TradeLogger
from backtest.run_info import generate_run_id

config = BacktestConfig()

logger = TradeLogger(generate_run_id())

engine = BacktestEngine(config, logger)

print(engine)