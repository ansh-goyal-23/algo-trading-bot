"""
Support & Resistance Zone Detection.

Finds significant price zones by:
1. Identifying all swing highs and lows over the full history
2. Clustering nearby levels (within 1% of each other) into zones
3. Ranking zones by number of touches (more touches = stronger zone)
4. At signal time, checking if price is within 1.5% of a zone

Reference: Varsity Module 2, Ch.3 (Support & Resistance)
"""

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema


SWING_ORDER      = 3     # bars each side to qualify as swing point
CLUSTER_TOLERANCE= 0.01  # 1% — levels within this % are merged into one zone
PROXIMITY_PCT    = 0.015 # 1.5% — price must be within this % of zone to count
MIN_TOUCHES      = 2     # minimum touches for a zone to be significant


def find_sr_levels(df: pd.DataFrame) -> list:
    """
    Finds significant support/resistance zones from full price history.

    Returns list of dicts:
        {price, touches, type: 'support'|'resistance'|'both', strength}
    sorted by strength descending.
    """
    close = df["close"]
    high  = df["high"]
    low   = df["low"]

    # find swing highs (resistance candidates) and swing lows (support candidates)
    high_idx = argrelextrema(high.values,  np.greater_equal, order=SWING_ORDER)[0]
    low_idx  = argrelextrema(low.values,   np.less_equal,    order=SWING_ORDER)[0]

    resistance_levels = high.iloc[high_idx].values.tolist()
    support_levels    = low.iloc[low_idx].values.tolist()

    all_levels = [(p, "resistance") for p in resistance_levels] + \
                 [(p, "support")    for p in support_levels]

    if not all_levels:
        return []

    # cluster nearby levels
    all_levels.sort(key=lambda x: x[0])
    zones = []
    current_cluster = [all_levels[0]]

    for i in range(1, len(all_levels)):
        price, level_type = all_levels[i]
        cluster_avg = np.mean([p for p, _ in current_cluster])

        if abs(price - cluster_avg) / cluster_avg <= CLUSTER_TOLERANCE:
            current_cluster.append(all_levels[i])
        else:
            zones.append(current_cluster)
            current_cluster = [all_levels[i]]
    zones.append(current_cluster)

    # build zone objects
    zone_list = []
    for cluster in zones:
        prices     = [p for p, _ in cluster]
        types      = [t for _, t in cluster]
        zone_price = np.mean(prices)
        touches    = len(cluster)
        has_support    = "support"    in types
        has_resistance = "resistance" in types
        zone_type  = "both"       if has_support and has_resistance else \
                     "support"    if has_support else "resistance"

        if touches >= MIN_TOUCHES:
            zone_list.append({
                "price":    round(zone_price, 2),
                "touches":  touches,
                "type":     zone_type,
                "strength": touches * (2 if zone_type == "both" else 1),
            })

    zone_list.sort(key=lambda x: x["strength"], reverse=True)
    return zone_list


def is_near_support(price: float, zones: list,
                    proximity: float = PROXIMITY_PCT) -> bool:
    """Returns True if price is within proximity% of a support zone."""
    for zone in zones:
        if zone["type"] in ("support", "both"):
            if abs(price - zone["price"]) / zone["price"] <= proximity:
                return True
    return False


def is_near_resistance(price: float, zones: list,
                       proximity: float = PROXIMITY_PCT) -> bool:
    """Returns True if price is within proximity% of a resistance zone."""
    for zone in zones:
        if zone["type"] in ("resistance", "both"):
            if abs(price - zone["price"]) / zone["price"] <= proximity:
                return True
    return False


def get_nearest_zone(price: float, zones: list) -> dict | None:
    """Returns the nearest S/R zone to current price."""
    if not zones:
        return None
    return min(zones, key=lambda z: abs(z["price"] - price))


def add_sr_context(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds support/resistance context columns to dataframe.
    Computed once per df using full history.
    """
    zones = find_sr_levels(df)

    near_support    = []
    near_resistance = []
    nearest_zone    = []

    for i, row in df.iterrows():
        price = row["close"]
        near_support.append(is_near_support(price, zones))
        near_resistance.append(is_near_resistance(price, zones))
        nz = get_nearest_zone(price, zones)
        nearest_zone.append(round(nz["price"], 2) if nz else None)

    df["near_support"]    = near_support
    df["near_resistance"] = near_resistance
    df["nearest_sr_zone"] = nearest_zone
    df["sr_zones"]        = [zones] * len(df)  # store for interpreter use
    return df
