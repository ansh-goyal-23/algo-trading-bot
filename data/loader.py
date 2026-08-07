"""
Centralized data loader.

Every module in the project should use this file
instead of calling pd.read_csv directly.
"""

from pathlib import Path
import pandas as pd
from data.validator import validate


DATA_DIR = Path("data/historical")


def load_stock(symbol: str) -> pd.DataFrame:
    """
    Load one stock from the historical database.
    """

    filepath = DATA_DIR / f"{symbol}.csv"

    if not filepath.exists():
        raise FileNotFoundError(
            f"{symbol}.csv not found inside {DATA_DIR}"
        )

    df = pd.read_csv(filepath)

    df["date"] = pd.to_datetime(df["date"])

    df = df.sort_values("date")

    df = df.reset_index(drop=True)

    ok, errors = validate(df)

    if not ok:

        print(f"\nValidation failed for {symbol}")

        for e in errors:
            print(" -", e)

        raise ValueError("Dataset validation failed.")

    return df


def available_stocks():
    """
    Returns all downloaded stocks.
    """

    return sorted(
        file.stem
        for file in DATA_DIR.glob("*.csv")
    )
