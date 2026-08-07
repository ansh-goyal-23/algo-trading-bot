"""
Data validation utilities.

Every historical dataset should pass these checks before
being used for indicators, backtests or optimization.
"""

import pandas as pd


def validate(df: pd.DataFrame):

    errors = []

    # -------------------------------
    # Required Columns
    # -------------------------------

    required = [
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]

    for col in required:
        if col not in df.columns:
            errors.append(f"Missing column: {col}")

    if errors:
        return False, errors

    # -------------------------------
    # Missing Values
    # -------------------------------

    if df[required].isnull().any().any():
        errors.append("Dataset contains NULL values.")

    # -------------------------------
    # Duplicate Dates
    # -------------------------------

    if df["date"].duplicated().any():
        errors.append("Duplicate dates detected.")

    # -------------------------------
    # Price Logic
    # -------------------------------

    if not (df["high"] >= df["low"]).all():
        errors.append("High is below Low.")

    if not (df["high"] >= df["open"]).all():
        errors.append("High is below Open.")

    if not (df["high"] >= df["close"]).all():
        errors.append("High is below Close.")

    if not (df["low"] <= df["open"]).all():
        errors.append("Low is above Open.")

    if not (df["low"] <= df["close"]).all():
        errors.append("Low is above Close.")

    # -------------------------------
    # Negative Values
    # -------------------------------

    if (df[["open","high","low","close"]] <= 0).any().any():
        errors.append("Negative/zero prices detected.")

    if (df["volume"] < 0).any():
        errors.append("Negative volume detected.")

    return len(errors) == 0, errors
