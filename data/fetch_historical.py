"""
Pulls historical daily candles for a given symbol and saves as CSV.
Requires KITE_ACCESS_TOKEN in .env (run kite_auth.py first each day).
"""
import os
import pandas as pd
from dotenv import load_dotenv
from kiteconnect import KiteConnect

load_dotenv()

API_KEY = os.getenv("KITE_API_KEY")
ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN")


def get_instrument_token(kite, symbol, exchange="NSE"):
    instruments = kite.instruments(exchange)
    for inst in instruments:
        if inst["tradingsymbol"] == symbol:
            return inst["instrument_token"]
    raise ValueError(f"Symbol {symbol} not found on {exchange}")


def fetch_historical(symbol, from_date, to_date, interval="day", exchange="NSE"):
    kite = KiteConnect(api_key=API_KEY)
    kite.set_access_token(ACCESS_TOKEN)

    token = get_instrument_token(kite, symbol, exchange)
    candles = kite.historical_data(
        instrument_token=token,
        from_date=from_date,
        to_date=to_date,
        interval=interval,
    )
    df = pd.DataFrame(candles)
    out_path = f"data/{symbol}_{interval}.csv"
    df.to_csv(out_path, index=False)
    print(f"Saved {len(df)} rows to {out_path}")
    return df


if __name__ == "__main__":
    fetch_historical(
        symbol="RELIANCE",
        from_date="2023-01-01",
        to_date="2024-01-01",
        interval="day",
    )
