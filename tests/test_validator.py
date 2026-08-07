from data.loader import available_stocks
from data.loader import load_stock

print()

passed = 0

failed = 0

for stock in available_stocks():

    try:

        load_stock(stock)

        print(f"✓ {stock}")

        passed += 1

    except Exception as e:

        print(f"✗ {stock} -> {e}")

        failed += 1

print()

print("="*40)

print(f"Passed : {passed}")

print(f"Failed : {failed}")
