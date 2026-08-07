from data.loader import load_stock
from data.loader import available_stocks


print()

print("Downloaded Stocks")

print(available_stocks())

print()

df = load_stock("RELIANCE")

print(df.head())

print()

print(df.tail())

print()

print(df.shape)
