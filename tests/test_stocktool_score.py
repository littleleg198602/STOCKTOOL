from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
import requests

from scripts.stocktool_score import ApiError, Client, candles_frame, fetch_universe
from scripts.stocktool_score import main
from market_checker_app.config import AppConfig
from market_checker_app.services.pipeline_service import PipelineService
from market_checker_app.storage.sqlite_store import SQLiteStore
from market_checker_app.storage.yahoo_cache_store import YahooCacheStore


NOW = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)


def bar(day, close=100):
    return {'t': int(datetime(2026, 11, day, tzinfo=timezone.utc).timestamp()),
            'o': close-1, 'h': close+2, 'l': close-2, 'c': close, 'v': 1000}


class CandleTests(unittest.TestCase):
    def test_complete_sorted_unadjusted_bars_only(self):
        frame = candles_frame([bar(15), bar(14), bar(13)], now=NOW)
        self.assertEqual(list(frame.index.day), [13, 14])
        self.assertEqual(frame.iloc[-1]['Close'], 100)
        self.assertNotIn('Adj Close', frame)

    def test_invalid_and_duplicate_bars_are_rejected(self):
        for bad in [dict(bar(14), c=float('nan')), dict(bar(14), h=10),
                    dict(bar(14), v=-1), dict(bar(14), t=True)]:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                candles_frame([bad], now=NOW)
        with self.assertRaises(ValueError):
            candles_frame([bar(14), bar(14)], now=NOW)


class RequestTests(unittest.TestCase):
    def test_key_is_never_sent_through_redirect(self):
        client = Client('https://stocktool.test/test', 'k'*32)
        response = requests.Response()
        response.status_code = 302
        with patch.object(client.session, 'request', return_value=response) as request:
            with self.assertRaises(ApiError):
                client.get('data-manager/api/datasets.php')
        self.assertFalse(request.call_args.kwargs['allow_redirects'])

    def test_universe_over_limit_is_not_truncated(self):
        class Fake:
            def get(self, path):
                return {'datasets':[{'symbol': 'AAA', 'timeframe':'D1'},
                                    {'symbol': 'BBB', 'timeframe':'D1'}]}
        with self.assertRaises(ApiError):
            fetch_universe(Fake(), 1)

    def test_api_failure_does_not_become_a_successful_partial_run(self):
        class Fake:
            def get(self, path, **kwargs):
                if path.endswith('datasets.php'):
                    return {'datasets':[{'symbol':'AAA','timeframe':'D1'}]}
                raise ApiError('offline')
        with self.assertRaises(ApiError):
            fetch_universe(Fake(), 1000)


class PipelineExternalSourceTests(unittest.TestCase):
    def test_batch_entry_point_publishes_strict_json_and_learning_report(self):
        published = []
        class OfflineClient:
            def __init__(self, *args):
                pass
            def restore(self, path):
                return 'empty'
            def publish(self, path, payload, revision):
                json.dumps(payload, allow_nan=False)
                with closing(sqlite3.connect(path)) as connection:
                    assert connection.execute('SELECT COUNT(*) FROM runs').fetchone()[0] == 1
                published.append(payload)
                return {'ok':True}
        index = pd.bdate_range(end=pd.Timestamp.now(tz='UTC').normalize()-pd.Timedelta(days=1),periods=260)
        close = pd.Series([100+i*.12 for i in range(len(index))],index=index)
        frame = pd.DataFrame({'Open':close-1,'High':close+2,'Low':close-2,'Close':close,'Volume':10000})
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                with patch('scripts.stocktool_score.Client',OfflineClient), \
                     patch('scripts.stocktool_score.fetch_universe',return_value=(['AAA'],{'AAA':frame},[])), \
                     patch.dict(os.environ, {'STOCKTOOL_RSS_SOURCES':''}):
                    main(['--train'])
            finally:
                os.chdir(previous)
        self.assertEqual(len(published),1)
        self.assertEqual(published[0]['signals'][0]['ticker'],'AAA')
        self.assertNotEqual(published[0]['learning']['status'],'READY')

    def test_web_prices_override_metadata_and_never_call_terminal_or_yahoo(self):
        # Include a missing symbol: external_ohlc must remain authoritative for it too.
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp)/'history.sqlite'
            config = AppConfig(sqlite_path=database, large_universe_threshold=0)
            cache = YahooCacheStore(database)
            cache.upsert_success('AAA', {'currentPrice':9999, 'sector':'Technology'}, yahoo_ticker='AAA')
            index = pd.bdate_range(end=pd.Timestamp.now(tz='UTC').normalize()-pd.Timedelta(days=1), periods=260)
            close = pd.Series([100 + i*.12 for i in range(len(index))], index=index)
            frame = pd.DataFrame({'Open':close-1, 'High':close+2, 'Low':close-2,
                                  'Close':close, 'Volume':100000})
            pipeline = PipelineService(config)
            with patch.object(type(pipeline.mt5_client), 'fetch_ohlcv_batch', side_effect=AssertionError('MT5 called')), \
                 patch.object(type(pipeline.yahoo_client), 'fetch_ohlc', side_effect=AssertionError('Yahoo called')), \
                 patch.object(type(pipeline.yahoo_client), 'fetch_ohlc_only', side_effect=AssertionError('Yahoo called')), \
                 patch.object(type(pipeline.yahoo_client), 'fetch_snapshots', side_effect=AssertionError('Yahoo called')):
                result = pipeline.run(['AAA','BBB'], [], SQLiteStore(database),
                    mt5_enabled=True, rss_enabled=False, yahoo_metadata_enabled=False,
                    external_ohlc={'AAA':frame})
            self.assertIsNotNone(result['run_id'])
            signals = result['signals'].set_index('ticker')
            self.assertEqual(set(signals.index), {'AAA','BBB'})
            self.assertEqual(signals.loc['AAA','current_price'], float(close.iloc[-1]))
            self.assertEqual(signals.loc['AAA','current_price_source'], 'data_manager_close')
            self.assertEqual(signals.loc['BBB','tech_source_used'], 'stocktool_data_manager')
            # Unadjusted broker prices may not be passed off as learning-ready inputs.
            self.assertNotEqual(signals.loc['AAA','learning_status'], 'APPLIED')
            with closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM signal_history').fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()
