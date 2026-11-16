#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""StockTool Market MT5 bridge — SEPARATE from the Equity MT5 bridge.

Reads index/FX/metal/energy/commodity/crypto instruments from a SPECIFIC
second MetaTrader 5 terminal; uploads to a different authenticated endpoint
and tracks state in a file isolated from the equities synchronization.

Usage:
  py -3 stocktool_mt5_market_sync.py --terminal-path "C:\MT5-MARKET\terminal64.exe" --discover
  py -3 stocktool_mt5_market_sync.py --terminal-path "C:\MT5-MARKET\terminal64.exe" --once --initial-bars 1200 --timeframes H1,H4,D1,W1
  py -3 stocktool_mt5_market_sync.py --terminal-path "C:\MT5-MARKET\terminal64.exe" --universe file --symbols-file instruments.txt --once
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import sys

import stocktool_mt5_sync as bridge


MARKET_URL = "https://www.stocktool.eu/test/market-data/api/ingest.php"


def get_terminal_path(args: list[str]) -> str | None:
    for index, value in enumerate(args):
        if value == "--terminal-path":
            return args[index + 1] if index + 1 < len(args) else None
        if value.startswith("--terminal-path="):
            return value.split("=", 1)[1]
    return os.getenv("STOCKTOOL_MARKET_MT5", "").strip() or None


def main() -> int:
    argv = sys.argv[1:]
    path = get_terminal_path(argv)
    check_only = "--check-api" in argv
    if not path and not check_only:
        print("CHYBA: u Market MT5 konektoru je povinná cesta k DRUHÉMU terminal64.exe.", file=sys.stderr)
        print('Použij --terminal-path "C:\\Cesta\\DruhyMT5\\terminal64.exe".', file=sys.stderr)
        return 2
    if path and not check_only:
        terminal = Path(path.strip().strip('"')).expanduser()
        if not terminal.is_file() or terminal.name.lower() != "terminal64.exe":
            print("CHYBA: zadaný druhý terminál neexistuje: " + str(terminal), file=sys.stderr)
            return 2
        path = str(terminal.resolve())
        # Prevent accidentally reading the default account if a path was not
        # passed through to MetaTrader5.initialize(path=...).
        if not any(s == "--terminal-path" or s.startswith("--terminal-path=") for s in argv):
            sys.argv.extend(["--terminal-path", path])
    explicit_universe = any(
        x == "--universe" or x.startswith("--universe=") for x in argv
    )
    if not explicit_universe:
        sys.argv.extend(["--universe", "markets"])
    elif "--universe=stocks" in argv or any(
        x == "--universe" and i + 1 < len(argv) and argv[i + 1] == "stocks"
        for i, x in enumerate(argv)
    ):
        print("CHYBA: akcie patří do původního Equity Data Manageru; Market konektor je nesynchronizuje.", file=sys.stderr)
        return 2

    # Different state file per chosen terminal installation, so the account
    # of the second terminal never reuses acknowledged equity timestamps.
    identity = (path or "market-check").casefold()
    state_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12]
    bridge.API_URL = MARKET_URL
    bridge.STATE_PATH = bridge.PRIVATE_FOLDER / ("mt5_market_state_" + state_id + ".json")
    bridge.MARKET_SYNC = True
    bridge.log("Market bridge: oddělené úložiště, akcie zůstávají beze změny.")
    return bridge.main()


if __name__ == "__main__":
    raise SystemExit(main())
