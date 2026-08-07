from datetime import date

from backtest.trade_logger import TradeLogger
from backtest.run_info import generate_run_id


run_id = generate_run_id()

logger = TradeLogger(run_id)


logger.log_trade(

    strategy="Checklist_v1.0",

    stock="RELIANCE",

    entry_date=date(2024,1,1),

    exit_date=date(2024,1,10),

    direction="LONG",

    entry_price=100,

    exit_price=108,

    quantity=50,

    pnl=400,

    exit_reason="Signal",

)


logger.save(f"reports/{run_id}/trade_history.csv")

print(logger.dataframe())
