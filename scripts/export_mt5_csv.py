#!/usr/bin/env python3
"""StockTool Data Manager – local OHLCV CSV exporter from a running MetaTrader 5 terminal.

Usage:
    py -m pip install MetaTrader5
    py scripts/export_mt5_csv.py --symbol XAUUSD --timeframe H1 --count 5000

No passwords are collected or sent to the website.
By default exports only completed candles (position 1, excluding the current open bar).
Timestamps exported as UTC as returned by MetaTrader5 Python integration.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
import re
import sys


PERIOD_NAMES = ("M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1")


def argument_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Export completed candles from MetaTrader 5 to CSV for StockTool Data Manager."
    )
    p.add_argument("--symbol", required=True, help="Exact broker symbol, e.g. XAUUSD or US500.cash")
    p.add_argument("--timeframe", default="H1", choices=PERIOD_NAMES, help="Bar timeframe (default: H1)")
    p.add_argument("--count", type=int, default=5000, help="Number of latest closed bars (1..100000)")
    p.add_argument("--output", type=Path, help="Output CSV path; default: stocktool_SYMBOL_TF.csv")
    p.add_argument("--terminal-path", type=Path, help="Optional path to terminal64.exe for a particular MT5 installation")
    return p


def main() -> int:
    options = argument_parser().parse_args()
    if not 1 <= options.count <= 100000:
        print("CHYBA: --count musí být mezi 1 a 100000.", file=sys.stderr)
        return 2
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,30}", options.symbol):
        print("CHYBA: Neplatný název symbolu.", file=sys.stderr)
        return 2

    try:
        import MetaTrader5 as mt5
    except ImportError:
        print("CHYBA: Nainstaluj balíček: py -m pip install MetaTrader5", file=sys.stderr)
        return 3

    connected = (
        mt5.initialize(path=str(options.terminal_path))
        if options.terminal_path
        else mt5.initialize()
    )
    if not connected:
        print(f"CHYBA: MT5 připojení selhalo: {mt5.last_error()}", file=sys.stderr)
        print("Otevři a přihlas se do MetaTraderu 5 na tomto počítači.", file=sys.stderr)
        return 4

    try:
        if not mt5.symbol_select(options.symbol, True):
            print(
                f"CHYBA: Symbol '{options.symbol}' nelze vybrat v Market Watch: {mt5.last_error()}",
                file=sys.stderr,
            )
            return 5

        timeframe = getattr(mt5, f"TIMEFRAME_{options.timeframe}")
        # Position 0 is the current incomplete candle. Position 1 is the most recent closed candle.
        rates = mt5.copy_rates_from_pos(options.symbol, timeframe, 1, options.count)
        if rates is None or len(rates) == 0:
            print(
                f"CHYBA: Pro {options.symbol} {options.timeframe} nejsou dostupné svíčky: {mt5.last_error()}",
                file=sys.stderr,
            )
            print("Zkontroluj symbol a nastavení Tools > Options > Charts > Max. bars in chart.", file=sys.stderr)
            return 6

        rows = sorted(rates, key=lambda item: int(item["time"]))
        safe_symbol = re.sub(r"[^A-Za-z0-9._-]+", "_", options.symbol)
        output = options.output or Path(f"stocktool_{safe_symbol}_{options.timeframe}.csv")
        output.parent.mkdir(parents=True, exist_ok=True)

        with output.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["<DATE>", "<TIME>", "<OPEN>", "<HIGH>", "<LOW>", "<CLOSE>", "<TICKVOL>", "<VOL>", "<SPREAD>"])
            for bar in rows:
                dt = datetime.fromtimestamp(int(bar["time"]), tz=timezone.utc)
                writer.writerow(
                    [
                        dt.strftime("%Y.%m.%d"),
                        dt.strftime("%H:%M:%S"),
                        float(bar["open"]),
                        float(bar["high"]),
                        float(bar["low"]),
                        float(bar["close"]),
                        int(bar["tick_volume"]),
                        float(bar["real_volume"]),
                        int(bar["spread"]),
                    ]
                )

        print(f"OK: exportováno {len(rows)} dokončených svíček ({options.symbol}, {options.timeframe}).")
        print(f"Soubor: {output.resolve()}")
        print(f"Období UTC: {datetime.fromtimestamp(int(rows[0]['time']), tz=timezone.utc)} – "
              f"{datetime.fromtimestamp(int(rows[-1]['time']), tz=timezone.utc)}")
        if len(rows) < options.count:
            print("Poznámka: broker/terminál poskytl méně svíček, než bylo požadováno.")
        print("CSV nyní otevři na stocktool.eu/test/data-manager/ a importuj.")
        return 0
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
