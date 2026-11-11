"""Offline unit tests for StockTool multi-timeframe MT5 sync logic.

Run from repository root:
    py -3 -m unittest discover -s tests -v

No MetaTrader terminal, API key, network or broker connection is required.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "stocktool_mt5_sync.py"
SPEC = importlib.util.spec_from_file_location("stocktool_mt5_sync", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


class FakeMT5:
    def __init__(self, times):
        self.times = times
        self.calls = []

    def copy_rates_from_pos(self, symbol, tf, position, count):
        self.calls.append((symbol, tf, position, count))
        if position < len(self.times):
            return [{"time": self.times[position]}]
        return []


class TestCompletedCandles(unittest.TestCase):
    def test_incomplete_h1_candle_is_skipped(self):
        now = 2000000000
        broker = FakeMT5([now - 1800, now - 5400])
        with patch.object(sync.time, "time", return_value=now):
            latest = sync.newest_closed_position(broker, "AAPL", 1, "H1")
        self.assertEqual(latest, (1, now - 5400))
        self.assertEqual(broker.calls[-1][2], 1)

    def test_completed_h1_last_candle_included(self):
        now = 2000000000
        broker = FakeMT5([now - 3700, now - 7300])
        with patch.object(sync.time, "time", return_value=now):
            latest = sync.newest_closed_position(broker, "AAPL", 1, "H1")
        self.assertEqual(latest, (0, now - 3700))

    def test_daily_candle_last_on_weekend_is_included(self):
        now = 2000000000
        broker = FakeMT5([now - 180000, now - 266400])
        with patch.object(sync.time, "time", return_value=now):
            latest = sync.newest_closed_position(broker, "AAPL", 1, "D1")
        self.assertEqual(latest, (0, now - 180000))

    def test_no_mt5_bars(self):
        broker = FakeMT5([])
        self.assertIsNone(sync.newest_closed_position(broker, "AAPL", 1, "W1"))


class TestBarValidation(unittest.TestCase):
    def test_open_bar_filtered_and_sorted(self):
        raw = [
            {"time": 300, "open": 3, "high": 5, "low": 2, "close": 4, "tick_volume": 15},
            {"time": 100, "open": 1, "high": 3, "low": 1, "close": 2, "tick_volume": 10},
            {"time": 200, "open": 2, "high": 4, "low": 1, "close": 3, "tick_volume": 12},
        ]
        bars = sync.rates_to_bars(raw, before_time=300)
        self.assertEqual([bar["t"] for bar in bars], [100, 200])
        self.assertEqual([bar["v"] for bar in bars], [10, 12])

    def test_timeframes_supported(self):
        for timeframe in ("H1", "H4", "D1", "W1"):
            self.assertIn(timeframe, sync.TIMEFRAMES)
            self.assertGreater(sync.TIMEFRAME_SECONDS[timeframe], 0)


if __name__ == "__main__":
    unittest.main()
