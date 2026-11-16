#!/usr/bin/env python3
"""Offline isolation checks for Equity MT5 vs Market MT5.
Run: py -3 -m unittest discover -s tests -p "test_market_mt5_split.py"
No MetaTrader5 process, keys, network or FORPSI required.
"""
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import stocktool_mt5_sync as sync
import stocktool_mt5_market_sync as market


def example_mt5():
    paths = [
        ("AAPL", "Stocks\\USA"),
        ("MSFT", "CFDs\\Shares"),
        ("US500", "Indices\\USA"),
        ("GER40.cash", "CFD\\Indices"),
        ("XAUUSD", "Metals\\Spot"),
        ("EURUSD", "Forex\\Majors"),
        ("OIL", "Energy\\Commodities"),
        ("US500_X", "CFD\\Indexes"),
    ]
    data = [SimpleNamespace(name=name, path=path, visible=True) for name, path in paths]
    return SimpleNamespace(symbols_get=lambda: data)


class MarketSplitTests(unittest.TestCase):
    def setUp(self):
        self.old_sync = sync.MARKET_SYNC

    def tearDown(self):
        sync.MARKET_SYNC = self.old_sync

    def test_equity_universe_preserved(self):
        sync.MARKET_SYNC = False
        cfg = SimpleNamespace(universe="stocks", symbols_file=None, max_symbols=100)
        symbols = sync.get_symbols(example_mt5(), cfg)
        self.assertIn("AAPL", symbols)
        self.assertIn("MSFT", symbols)
        self.assertNotIn("US500", symbols)
        self.assertNotIn("XAUUSD", symbols)

    def test_market_universe_excludes_stocks(self):
        sync.MARKET_SYNC = True
        cfg = SimpleNamespace(universe="markets", symbols_file=None, max_symbols=100)
        symbols = sync.get_symbols(example_mt5(), cfg)
        self.assertIn("US500", symbols)
        self.assertIn("GER40.cash", symbols)
        self.assertIn("XAUUSD", symbols)
        self.assertIn("EURUSD", symbols)
        self.assertIn("OIL", symbols)
        self.assertNotIn("AAPL", symbols)
        self.assertNotIn("MSFT", symbols)

    def test_marketwatch_cannot_silently_import_shares(self):
        sync.MARKET_SYNC = True
        cfg = SimpleNamespace(universe="marketwatch", symbols_file=None, max_symbols=100)
        symbols = sync.get_symbols(example_mt5(), cfg)
        self.assertNotIn("AAPL", symbols)
        self.assertNotIn("MSFT", symbols)

    def test_file_universe_filters_known_stocks(self):
        import tempfile
        sync.MARKET_SYNC = True
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "instruments.txt"
            path.write_text("# Chosen symbols\nAAPL\nXAUUSD\nUS500\n", encoding="utf-8")
            cfg = SimpleNamespace(universe="file", symbols_file=path, max_symbols=100)
            symbols = sync.get_symbols(example_mt5(), cfg)
            self.assertEqual(["XAUUSD", "US500"], symbols)

    def test_market_symbols_are_path_safe(self):
        self.assertTrue(sync.MARKET_NAME.fullmatch("#US500"))
        self.assertTrue(sync.MARKET_NAME.fullmatch("GER40.cash"))
        self.assertFalse(sync.MARKET_NAME.fullmatch("C:\\unsafe"))
        self.assertFalse(sync.MARKET_NAME.fullmatch("../bad"))
        self.assertFalse(sync.MARKET_NAME.fullmatch("hello/world"))

    def test_separate_market_api_and_data_dir(self):
        self.assertNotEqual(sync.API_URL, market.MARKET_URL)
        self.assertIn("/market-data/api/ingest.php", market.MARKET_URL)
        market_common = (ROOT / "site/market-data/api/common.php").read_text(encoding="utf-8")
        stock_common = (ROOT / "site/data-manager/api/common.php").read_text(encoding="utf-8")
        self.assertIn("'market-data'", market_common)
        self.assertIn("'data'", stock_common)
        self.assertIn("market_setup", market_common)
        self.assertIn("setup($allowBrowserSession)", market_common)

    def test_strategy_lab_reads_only_market_api(self):
        app = (ROOT / "site/strategy-lab/app.js").read_text(encoding="utf-8")
        self.assertIn("../market-data/api/datasets.php", app)
        self.assertIn("../market-data/api/candles.php", app)
        self.assertNotIn("../data-manager/api/datasets.php", app)
        self.assertNotIn("../data-manager/api/candles.php", app)
        self.assertIn('dataTimeframe!==selectedTimeframe', app)

    def test_explicit_second_terminal_argument(self):
        self.assertEqual(
            market.get_terminal_path(["--once", "--terminal-path", "C:\\MT5-B\\terminal64.exe"]),
            "C:\\MT5-B\\terminal64.exe")
        self.assertEqual(
            market.get_terminal_path(["--terminal-path=C:\\MT5-B\\terminal64.exe"]),
            "C:\\MT5-B\\terminal64.exe")

    def test_market_sync_state_is_separate_from_stocks(self):
        src = (ROOT / "scripts/stocktool_mt5_market_sync.py").read_text(encoding="utf-8")
        self.assertIn("mt5_market_state_", src)
        self.assertIn("bridge.MARKET_SYNC = True", src)
        self.assertIn("bridge.API_URL = MARKET_URL", src)


if __name__ == "__main__":
    unittest.main()
