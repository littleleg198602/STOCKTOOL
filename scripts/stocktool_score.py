"""Run the original JOHNY scoring pipeline using StockTool's authenticated API.

No terminal access, orders, pickle models, committed credentials or public artifacts.
State is restored/published as a SQLite snapshot; publication uses optimistic locking.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.parse import urlparse

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from market_checker_app.analysis.buy_learning import (
    LearningConfig, train_from_history, save_learning_result,
)
from market_checker_app.config import AppConfig
from market_checker_app.services.pipeline_service import PipelineService, SCORING_VERSION
from market_checker_app.services.yahoo_enrichment_service import YahooEnrichmentService
from market_checker_app.storage.sqlite_store import SQLiteStore
from market_checker_app.storage.yahoo_cache_store import YahooCacheStore

MAX_DATABASE_BYTES = 128 * 1024 * 1024
SYMBOL = re.compile(r"[A-Z0-9._:-]{1,30}\Z")


class ApiError(RuntimeError):
    pass


class Client:
    def __init__(self, base: str, key: str):
        parsed = urlparse(base)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("STOCKTOOL_BASE_URL must be an HTTPS URL without credentials or query")
        if len(key) < 32 or any(c in key for c in "\r\n"):
            raise ValueError("Set STOCKTOOL_API_KEY in GitHub Actions secrets")
        self.base = base.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"X-StockTool-Key": key})

    def request(self, path, *, method="GET", **kwargs):
        # Never forward the private key through redirects or print response bodies.
        response = self.session.request(method, self.base + "/" + path,
                                        timeout=(15, 180), allow_redirects=False, **kwargs)
        if not 200 <= response.status_code < 300:
            raise ApiError(f"StockTool API returned HTTP {response.status_code} for {path.split('?')[0]}")
        return response

    def get(self, path, **params):
        response = self.request(path, params=params)
        try:
            data = response.json()
        except ValueError:
            raise ApiError("StockTool API did not return JSON") from None
        if not isinstance(data, dict) or data.get("ok") is not True:
            raise ApiError("StockTool API returned an unsuccessful response")
        return data

    def restore(self, path: Path) -> str:
        manifest = self.get("johny/api/state.php", kind="manifest")
        revision = manifest["revision"]
        if revision == "empty":
            if path.exists():
                raise ApiError("Refusing to mix local state with a new remote history")
            return revision
        if not re.fullmatch(r"[a-f0-9]{32}", str(revision)):
            raise ApiError("Invalid state revision")
        digest = hashlib.sha256()
        size = 0
        with self.request("johny/api/state.php", params={"kind": "database", "revision": revision},
                          stream=True) as response, path.open("wb") as output:
            for chunk in response.iter_content(1024 * 1024):
                size += len(chunk)
                if size > MAX_DATABASE_BYTES:
                    raise ApiError("History database exceeded configured size limit")
                digest.update(chunk)
                output.write(chunk)
        if digest.hexdigest() != manifest.get("database_sha256"):
            raise ApiError("History database checksum mismatch")
        with closing(sqlite3.connect(path)) as connection:
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise ApiError("History database integrity check failed")
        return revision

    def publish(self, path: Path, result: dict, revision: str):
        # sqlite backup includes any committed WAL contents and produces a closed file.
        snapshot = path.with_suffix(".snapshot")
        with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(snapshot)) as dest:
            source.backup(dest)
        if snapshot.stat().st_size > MAX_DATABASE_BYTES:
            raise ApiError("History database exceeded configured size limit")
        with snapshot.open("rb") as database:
            response = self.request("johny/api/publish.php", method="POST",
                data={"expected_revision": revision,
                      "result": json.dumps(result, ensure_ascii=False, allow_nan=False)},
                files={"database": ("history.sqlite", database, "application/octet-stream")})
        payload = response.json()
        if payload.get("ok") is not True:
            raise ApiError("Result publication failed")
        return payload


def candles_frame(bars: list, *, now: datetime | None = None) -> pd.DataFrame:
    """Validate complete D1 bars. Broker OHLC is never marked split-adjusted."""
    now = now or datetime.now(timezone.utc)
    rows = []
    for bar in bars:
        if not isinstance(bar, dict):
            raise ValueError("Invalid candle")
        values = [bar.get(field) for field in ("t", "o", "h", "l", "c", "v")]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
            raise ValueError("Non-finite candle")
        stamp, opening, high, low, close, volume = values
        if stamp != int(stamp) or stamp <= 0 or min(opening, high, low, close) <= 0 or volume < 0:
            raise ValueError("Invalid candle range")
        if high < max(opening, close, low) or low > min(opening, close, high):
            raise ValueError("Inconsistent OHLC candle")
        date = pd.Timestamp(stamp, unit="s", tz="UTC")
        if date.date() >= now.date():
            continue
        rows.append({"time": date, "Open": opening, "High": high,
                     "Low": low, "Close": close, "Volume": volume})
    if not rows:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    frame = pd.DataFrame(rows).set_index("time").sort_index()
    if frame.index.has_duplicates:
        raise ValueError("Duplicate candle timestamps")
    return frame


def fetch_universe(client, limit: int) -> tuple[list[str], dict[str, pd.DataFrame], list[str]]:
    datasets = client.get("data-manager/api/datasets.php").get("datasets")
    if not isinstance(datasets, list):
        raise ApiError("Missing dataset list")
    watchlist = sorted({item["symbol"] for item in datasets
                        if isinstance(item, dict) and item.get("timeframe") == "D1"
                        and isinstance(item.get("symbol"), str) and SYMBOL.fullmatch(item["symbol"])})
    if not watchlist or len(watchlist) > limit:
        raise ApiError(f"D1 universe contains {len(watchlist)} symbols; allowed range is 1..{limit}")
    frames, warnings = {}, []
    for position, ticker in enumerate(watchlist, 1):
        # Network/auth failures abort the run. Invalid individual datasets remain visible.
        data = client.get("data-manager/api/candles.php", symbol=ticker, timeframe="D1", limit=5000)
        if data.get("symbol") != ticker or data.get("timeframe") != "D1":
            raise ApiError("Dataset identity mismatch")
        try:
            frame = candles_frame(data["bars"])
            if frame.empty:
                warnings.append(f"{ticker}: žádné dokončené D1 svíčky")
            elif (datetime.now(timezone.utc).date() - frame.index.max().date()).days > 7:
                warnings.append(f"{ticker}: D1 svíčky jsou starší než 7 dní; technické skóre nebude použito")
                frame = frame.iloc[:0]
            frames[ticker] = frame
        except (ValueError, KeyError, TypeError, OverflowError):
            warnings.append(f"{ticker}: neplatná D1 historie")
            frames[ticker] = pd.DataFrame()
        if position % 25 == 0 or position == len(watchlist):
            print(f"Data Manager: {position}/{len(watchlist)}", flush=True)
        time.sleep(0.05)
    if not any(not frame.empty for frame in frames.values()):
        raise ApiError("No usable D1 datasets; previous results remain unchanged")
    return watchlist, frames, warnings


def records(frame):
    # Pandas serializes NaN/NaT as null; strict JSON downstream rejects non-finite values.
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-symbols", type=int, default=1000)
    parser.add_argument("--refresh-yahoo", type=int, default=0, choices=range(0, 51), metavar="0..50")
    parser.add_argument("--train", action="store_true")
    args = parser.parse_args(argv)
    if not 1 <= args.max_symbols <= 1000:
        parser.error("--max-symbols must be 1..1000 (the universe is never silently truncated)")
    client = Client(os.environ.get("STOCKTOOL_BASE_URL", "https://www.stocktool.eu/test"),
                    os.environ.get("STOCKTOOL_API_KEY", ""))
    state = Path(".score-state")
    state.mkdir(exist_ok=True)
    database = state / "history.sqlite"
    revision = client.restore(database)
    watchlist, frames, warnings = fetch_universe(client, args.max_symbols)
    config = AppConfig(output_dir=state, sqlite_path=database, export_excel=False,
                       max_tickers_per_run=args.max_symbols, large_universe_threshold=0)
    store = SQLiteStore(database)
    cache = YahooCacheStore(database)
    enrichment = {}
    if args.refresh_yahoo:
        service = YahooEnrichmentService(cache)
        enrichment["prices"] = service.refresh_price_history(watchlist, max_items=args.refresh_yahoo)
        # Metadata and prices retain the original retry/rate-limit protections.
        enrichment["metadata"] = asdict(service.refresh(watchlist, max_items=args.refresh_yahoo))
    pipeline = PipelineService(config)
    last_step = [None]
    def progress(value):
        step = (value.processed_symbols // 25, value.current_step)
        if step != last_step[0] and value.current_step in {"start", "save_history", "done"}:
            print(f"Analysis: {value.processed_symbols}/{len(watchlist)}", flush=True)
            last_step[0] = step
    rss = [url.strip() for url in os.environ.get("STOCKTOOL_RSS_SOURCES", "").splitlines() if url.strip()]
    result = pipeline.run(watchlist, rss, store, progress_callback=progress,
                          mt5_enabled=False, external_ohlc=frames,
                          yahoo_metadata_enabled=False, rss_enabled=bool(rss))
    if result["run_id"] is None:
        raise ApiError("History could not be saved; publication aborted")
    learning = {"status": "NOT_REQUESTED"}
    if args.train:
        learning_config = LearningConfig()
        model, learning = train_from_history(database, config=learning_config)
        save_learning_result(database, learning_config, model, learning)
        # Accepted models affect the next run, avoiding training on this run's outcome.
    payload = {
        "schema_version": 1, "scoring_version": SCORING_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "metadata": {**asdict(result["metadata"]),
                     "started_at": result["metadata"].started_at.isoformat(),
                     "finished_at": result["metadata"].finished_at.isoformat()},
        "run_id": result["run_id"], "source": "Data Manager D1",
        "signals": records(result["signals"]), "buy": records(result["buy"]),
        "buy_details": result["buy_details"], "articles": records(result["articles"]),
        "sources": records(result["sources"]),
        "warnings": warnings + result["warnings"], "errors": result["errors"],
        "learning": learning, "enrichment": enrichment,
        "workflow_url": (f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/"
                         f"{os.environ['GITHUB_RUN_ID']}" if os.environ.get("GITHUB_RUN_ID") else None),
    }
    client.publish(database, payload, revision)
    print(f"Published {len(payload['signals'])} results; learning: {learning['status']}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (ApiError, ValueError, requests.RequestException):
        # requests exceptions can include URLs/headers; never echo their representation.
        print("Score run failed. Check API configuration, data availability and server limits. Previous published state is retained.", file=sys.stderr)
        sys.exit(1)
