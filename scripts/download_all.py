from config.nifty50 import NIFTY50
from data.fetch_yfinance import fetch_historical

SUCCESS = []
FAILED = []

print("=" * 60)
print("Downloading NIFTY 50 Historical Data")
print("=" * 60)

for i, stock in enumerate(NIFTY50, start=1):

    print(f"[{i:02d}/50] {stock:<15}", end=" ")

    try:

        df = fetch_historical(stock)

        SUCCESS.append(stock)

        print(f"✓ {len(df)} rows")

    except Exception as e:

        FAILED.append(stock)

        print(f"✗ {e}")

print("\n")

print("=" * 60)
print("DOWNLOAD SUMMARY")
print("=" * 60)

print(f"Successful : {len(SUCCESS)}")
print(f"Failed     : {len(FAILED)}")

if FAILED:

    print("\nFailed Stocks:")

    for stock in FAILED:

        print(stock)
