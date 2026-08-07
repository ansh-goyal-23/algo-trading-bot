# """
# Pulls historical daily OHLCV data via yfinance for backtesting.
# NSE tickers need a ".NS" suffix, e.g. RELIANCE.NS, TCS.NS.
# """
# import yfinance as yf
# import pandas as pd


# def fetch_historical(symbol, start="2020-01-01", end=None, interval="1d"):
#     ticker = f"{symbol}.NS" if not symbol.endswith(".NS") else symbol
#     df = yf.download(ticker, start=start, end=end, interval=interval, progress=False)

#     if df.empty:
#         raise ValueError(f"No data returned for {ticker} - check symbol/date range")

#     df = df.reset_index()
#     df.columns = [c.lower() if isinstance(c, str) else c[0].lower() for c in df.columns]
#     df = df.rename(columns={"date": "date", "adj close": "adj_close"})

#     out_path = f"data/{symbol}_{interval}.csv"
#     df.to_csv(out_path, index=False)
#     print(f"Saved {len(df)} rows to {out_path}")
#     return df


# if __name__ == "__main__":
#     fetch_historical("RELIANCE", start="2020-01-01")
#     fetch_historical("TCS", start="2020-01-01")
#     fetch_historical("ITBEES", start="2020-01-01")


"""
Download historical OHLCV data using Yahoo Finance.
"""

from pathlib import Path

import pandas as pd
import yfinance as yf


DATA_DIR = Path("data/historical")


def fetch_historical(
    symbol,
    start="2020-01-01",
    end=None,
    interval="1d",
    save=True,
):

    ticker = symbol if symbol.endswith(".NS") else f"{symbol}.NS"

    df = yf.download(
        ticker,
        start=start,
        end=end,
        interval=interval,
        progress=False,
        auto_adjust=False,
    )

    if df.empty:
        raise ValueError(f"No data found for {ticker}")

    df = df.reset_index()

    # Keep only required columns
    df = df[
        [
            "Date",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
        ]
    ]

    df.columns = [
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]

    df["date"] = pd.to_datetime(df["date"])

    if save:

        DATA_DIR.mkdir(parents=True, exist_ok=True)

        filename = DATA_DIR / f"{symbol}.csv"

        df.to_csv(filename, index=False)

    return df