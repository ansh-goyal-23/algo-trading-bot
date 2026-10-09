"""
Tests for execution/quote_utils.py and config/excluded_trades.py.
Pure Python, no Kotak/yfinance needed.   Run: python3 -m unittest tests.test_quote_utils -v
"""
import unittest

from execution import quote_utils as q
from config.excluded_trades import EXCLUDED_TRADE_IDS, filter_valid_trades

# Real response captured from the VM on 2026-10-09 (quote_type="ohlc", APOLLOHOSP):
# no 'ltp', no volume, and 'close' is the PREVIOUS close (7666 is below today's low).
REAL_OHLC_RESP = [{
    "exchange_token": "157", "display_symbol": "APOLLOHOSP-EQ", "exchange": "nse_cm",
    "ohlc": {"open": "7950.0000", "high": "7985.0000", "low": "7775.5000", "close": "7666.0000"},
}]
TODAY = "2026-10-09"


class BuildKotakCandle(unittest.TestCase):
    def test_real_ohlc_response_alone_is_rejected_not_filled_with_prev_close(self):
        # The original bug: this used to yield close=7666 (yesterday's close).
        candle, why = q.build_kotak_candle(REAL_OHLC_RESP, None, TODAY)
        self.assertIsNone(candle)
        self.assertIn("no usable LTP", why)

    def test_valid_ltp_gives_candle_with_ltp_close(self):
        ltp = [{"exchange_token": "157", "ltp": "7906.50"}]
        candle, why = q.build_kotak_candle(REAL_OHLC_RESP, ltp, TODAY)
        self.assertEqual(why, "")
        self.assertEqual(candle["close"], 7906.5)
        self.assertEqual((candle["open"], candle["high"], candle["low"]), (7950.0, 7985.0, 7775.5))
        self.assertEqual(candle["date"], TODAY)
        self.assertEqual(candle["volume"], 0)  # filled separately

    def test_ltp_inside_ohlc_response_is_used(self):
        resp = [dict(REAL_OHLC_RESP[0], ltp="7900.0")]
        candle, _ = q.build_kotak_candle(resp, None, TODAY)
        self.assertEqual(candle["close"], 7900.0)

    def test_ltp_outside_day_range_is_rejected(self):
        ltp = [{"ltp": "7666.0"}]  # below today's low 7775.5 -> inconsistent candle
        candle, why = q.build_kotak_candle(REAL_OHLC_RESP, ltp, TODAY)
        self.assertIsNone(candle)
        self.assertIn("close outside day range", why)

    def test_zero_or_garbage_ltp_is_rejected(self):
        for bad in ([{"ltp": "0"}], [{"ltp": None}], [{"ltp": "abc"}], [], None, {}):
            candle, _ = q.build_kotak_candle(REAL_OHLC_RESP, bad, TODAY)
            self.assertIsNone(candle, bad)

    def test_missing_ohlc_block_is_rejected(self):
        candle, why = q.build_kotak_candle([{"ltp": "100"}], [{"ltp": "100"}], TODAY)
        self.assertIsNone(candle)
        self.assertIn("ohlc", why)

    def test_dict_with_data_wrapper_is_handled(self):
        candle, _ = q.build_kotak_candle({"data": REAL_OHLC_RESP}, {"data": [{"ltp": "7906.5"}]}, TODAY)
        self.assertEqual(candle["close"], 7906.5)


class CandleChecks(unittest.TestCase):
    def good(self, **kw):
        c = {"date": TODAY, "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 10}
        c.update(kw)
        return c

    def test_good_candle(self):
        self.assertTrue(q.candle_is_valid(self.good()))

    def test_bad_candles(self):
        self.assertFalse(q.candle_is_valid(self.good(close=0)))
        self.assertFalse(q.candle_is_valid(self.good(close=97.0)))   # below low
        self.assertFalse(q.candle_is_valid(self.good(close=106.0)))  # above high
        self.assertFalse(q.candle_is_valid(self.good(open=110.0)))   # open above high
        self.assertFalse(q.candle_is_valid(self.good(high=90.0)))    # high < low
        self.assertFalse(q.candle_is_valid(None))
        self.assertFalse(q.candle_is_valid({"open": 1}))

    def test_tiny_rounding_tolerance(self):
        self.assertTrue(q.candle_is_valid(self.good(close=105.02)))  # 0.019% over high


class FallbackAndVolume(unittest.TestCase):
    row = {"date": TODAY, "open": 100.0, "high": 105.0, "low": 98.0, "close": 103.0, "volume": 123456}

    def test_fallback_requires_todays_date(self):
        stale = dict(self.row, date="2026-10-08")
        cand, why = q.accept_fallback_candle(stale, TODAY)
        self.assertIsNone(cand)
        self.assertIn("stale", why)
        self.assertIsNotNone(q.accept_fallback_candle(self.row, TODAY)[0])

    def test_fallback_rejects_inconsistent_row(self):
        self.assertIsNone(q.accept_fallback_candle(dict(self.row, close=50.0), TODAY)[0])
        self.assertIsNone(q.accept_fallback_candle(None, TODAY)[0])

    def test_fill_volume(self):
        c = {"date": TODAY, "volume": 0}
        self.assertTrue(q.fill_volume(c, self.row, TODAY))
        self.assertEqual(c["volume"], 123456)
        c2 = {"volume": 0}
        self.assertFalse(q.fill_volume(c2, dict(self.row, date="2026-10-08"), TODAY))
        self.assertFalse(q.fill_volume(c2, dict(self.row, volume=0), TODAY))
        self.assertFalse(q.fill_volume(c2, None, TODAY))
        self.assertEqual(c2["volume"], 0)


class ExcludedTrades(unittest.TestCase):
    def test_filter_drops_only_excluded_ids(self):
        rows = [{"id": i} for i in range(2, 13)]
        kept = [r["id"] for r in filter_valid_trades(rows)]
        self.assertEqual(kept, [2, 3, 4, 5, 6, 7])
        self.assertEqual(len(rows), 11)  # input untouched
        self.assertEqual(set(EXCLUDED_TRADE_IDS), {8, 9, 10, 11, 12})


if __name__ == "__main__":
    unittest.main()
