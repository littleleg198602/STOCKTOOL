#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""StockTool MT5 bulk bridge: read candles DIRECTLY from a running MT5 terminal.

No CSV, no EA, no orders. One Python process for hundreds of symbols.
Push completed OHLCV bars to private StockTool API via HTTPS.

Examples:
    py -3 stocktool_mt5_sync.py --discover
    py -3 stocktool_mt5_sync.py --once --max-symbols 10
    py -3 stocktool_mt5_sync.py --loop --max-symbols 700 --timeframe D1
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import getpass
import json
import os
from pathlib import Path
import re
import ssl
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlparse

API_URL = "https://www.stocktool.eu/test/data-manager/api/ingest.php"
PRIVATE_FOLDER = Path.home() / ".stocktool"
SECRET_PATH = PRIVATE_FOLDER / "api_key.dpapi"
STATE_PATH = PRIVATE_FOLDER / "mt5_bulk_state.json"
TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1")
# Metadata path naming is defined by the broker. This is intentionally conservative.
STOCK_PATH = re.compile(r"stock|share|equit|equity|acciones|aktie|akcj", re.IGNORECASE)
NAME = re.compile(r"^[A-Za-z0-9._:-]{1,30}$")


def log(line: str) -> None:
    print(datetime.now().strftime("%H:%M:%S"), line, flush=True)


def protected_bytes(value: bytes, decrypt: bool) -> bytes:
    """Windows DPAPI: local key protected for the current Windows login."""
    if os.name != "nt":
        raise RuntimeError("Bezpečné uložení klíče v této verzi vyžaduje Windows.")
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    buffer = (ctypes.c_byte * len(value)).from_buffer_copy(value)
    source = DATA_BLOB(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    result = DATA_BLOB()
    operation = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    if not operation(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(result)):
        raise OSError("Windows nedovolil načíst/uložit šifrovaný API klíč.")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(result.pbData, ctypes.c_void_p))


def get_api_key(reset: bool = False) -> str:
    env = os.getenv("STOCKTOOL_API_KEY", "").strip()
    if env:
        if len(env) < 32:
            raise ValueError("STOCKTOOL_API_KEY musí mít alespoň 32 znaků.")
        return env
    if reset:
        SECRET_PATH.unlink(missing_ok=True)
    if SECRET_PATH.is_file():
        key = protected_bytes(SECRET_PATH.read_bytes(), decrypt=True).decode("utf-8")
        if len(key) >= 32:
            return key
        raise ValueError("Dříve uložený klíč je příliš krátký.")
    print("\nPRVNÍ SPUŠTĚNÍ: vlož soukromý StockTool API klíč z FORPSI.")
    print("Klíč se uloží šifrovaně pomocí Windows DPAPI, nikoliv do GitHubu.\n")
    key = getpass.getpass("StockTool API klíč: ").strip()
    if len(key) < 32 or "\r" in key or "\n" in key:
        raise ValueError("Klíč musí mít alespoň 32 znaků.")
    PRIVATE_FOLDER.mkdir(parents=True, exist_ok=True)
    SECRET_PATH.write_bytes(protected_bytes(key.encode("utf-8"), decrypt=False))
    log("API klíč bezpečně uložen pro tento Windows účet.")
    return key


def load_state() -> dict:
    if not STATE_PATH.is_file():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        log("UPOZORNĚNÍ: místní stav nelze načíst; bezpečně zopakujeme část historie.")
        return {}


def save_state(state: dict) -> None:
    PRIVATE_FOLDER.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, STATE_PATH)


def arguments() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="StockTool – automatická hromadná synchronizace MT5 (bez CSV).")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--discover", action="store_true", help="Vypíše detekované akcie u brokera, bez odesílání.")
    mode.add_argument("--once", action="store_true", help="Provede jednu synchronizaci a skončí.")
    mode.add_argument("--loop", action="store_true", help="Pravidelně synchronizuje, dokud běží počítač a MT5.")
    p.add_argument("--universe", choices=["stocks", "marketwatch", "file"], default="stocks",
                   help="stocks: akcie podle cesty brokera; marketwatch: viditelné symboly; file: vlastní TXT seznam")
    p.add_argument("--symbols-file", type=Path, default=None, help="TXT se symboly po řádcích (jen pro --universe file).")
    p.add_argument("--max-symbols", type=int, default=700, help="Maximum instrumentů. Výchozí: 700.")
    p.add_argument("--timeframe", choices=TIMEFRAMES, default="D1")
    p.add_argument("--initial-bars", type=int, default=300, help="Počet dokončených svíček při prvním importu (1..5000).")
    p.add_argument("--interval-minutes", type=float, default=15.0, help="Interval kontroly, pokud je --loop.")
    p.add_argument("--delay", type=float, default=0.3, help="Minimální prodleva mezi HTTPS požadavky v sekundách.")
    p.add_argument("--reset-key", action="store_true", help="Při dalším připojení zadat nový API klíč.")
    p.add_argument("--terminal-path", type=str, default=None, help="Volitelná cesta k terminal64.exe.")
    return p.parse_args()


def get_symbols(mt5, cfg: argparse.Namespace) -> list[str]:
    symbols = mt5.symbols_get()
    if symbols is None:
        raise RuntimeError("Nelze načíst symboly z MT5: " + str(mt5.last_error()))
    if cfg.universe == "file":
        if not cfg.symbols_file or not cfg.symbols_file.is_file():
            raise ValueError("Zadej --symbols-file CESTA_K_TXT.")
        lines = cfg.symbols_file.read_text(encoding="utf-8-sig").splitlines()
        requested = list(dict.fromkeys(x.strip() for x in lines if x.strip() and not x.lstrip().startswith("#")))
        available = {s.name for s in symbols}
        missing = [s for s in requested if s not in available]
        if missing:
            log(f"CHYBÍ u brokera ({len(missing)}): " + ", ".join(missing[:15]) + ("..." if len(missing) > 15 else ""))
        found = [s for s in requested if s in available and NAME.fullmatch(s)]
    else:
        found = sorted({
            s.name for s in symbols
            if NAME.fullmatch(s.name) and (
                bool(getattr(s, "visible", False)) if cfg.universe == "marketwatch" else
                bool(STOCK_PATH.search(str(getattr(s, "path", ""))))
            )
        })
    if len(found) > cfg.max_symbols:
        log(f"POZOR: nalezeno {len(found)} symbolů, limit je {cfg.max_symbols}. "
            "Pro kompletní pokrytí zvyš --max-symbols nebo použij --universe file.")
        found = found[:cfg.max_symbols]
    return found


def rates_to_bars(rates, before_time: int) -> list[dict]:
    out = []
    for row in rates:
        t = int(row["time"])
        if t >= before_time:
            continue  # Exclude still-open candle.
        out.append({
            "t": t, "o": float(row["open"]), "h": float(row["high"]),
            "l": float(row["low"]), "c": float(row["close"]),
            "v": int(row["tick_volume"])
        })
    # Deduplicate by timestamp; sorted oldest first, safe for incremental batches.
    return list({bar["t"]: bar for bar in sorted(out, key=lambda b: b["t"])}.values())


def post_chunk(api_key: str, symbol: str, timeframe: str, bars: list[dict], delay: float) -> None:
    payload = json.dumps({"symbol": symbol, "timeframe": timeframe, "bars": bars}, separators=(",", ":")).encode("utf-8")
    if len(payload) > 500000:
        raise ValueError("Dávka překračuje maximální velikost serverového požadavku.")
    req = Request(API_URL, payload, {
        "Content-Type": "application/json",
        "X-StockTool-Key": api_key,
        "Accept": "application/json",
        "User-Agent": "StockToolMT5Bulk/1.0"
    }, method="POST")
    last_error = None
    for attempt in range(3):
        try:
            with urlopen(req, timeout=25, context=ssl.create_default_context()) as response:
                data = json.loads(response.read(100000).decode("utf-8"))
                if not data.get("ok"):
                    raise RuntimeError("Server vrátil neúspěšnou odpověď.")
            if delay:
                time.sleep(delay)
            return
        except HTTPError as exc:
            last_error = f"HTTP {exc.code}"
            if exc.code in (400, 401, 403, 405, 413, 422):
                raise RuntimeError(f"Server odmítl data ({last_error}); ověř nastavení/klíč.") from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = type(exc).__name__
        time.sleep(min(2 ** attempt * 2, 8))
    raise RuntimeError(f"Synchronizace se serverem selhala ({last_error}).")


def sync_one(mt5, symbol: str, cfg: argparse.Namespace, key: str, state: dict) -> tuple[str, int]:
    timeframe = getattr(mt5, "TIMEFRAME_" + cfg.timeframe)
    state_id = symbol + "|" + cfg.timeframe
    last_time = int(state.get(state_id, 0))
    info = mt5.symbol_info(symbol)
    was_selected = bool(info and getattr(info, "select", False))
    if not mt5.symbol_select(symbol, True):
        return ("symbol nedostupný v Market Watch", 0)
    try:
        latest = mt5.copy_rates_from_pos(symbol, timeframe, 1, 1)
        if latest is None or len(latest) == 0:
            return ("bez dostupné historie", 0)
        latest_closed = int(latest[0]["time"])
        if last_time >= latest_closed:
            return ("beze změny", 0)

        # The open candle time is the upper bound. On closed markets, there is
        # no newer bar; use server time. copy_rates_range includes endpoints.
        current = mt5.copy_rates_from_pos(symbol, timeframe, 0, 1)
        upper = int(current[0]["time"]) if current is not None and len(current) else int(time.time())
        if last_time > 0:
            # Include the last successful candle; server deduplicates overlap.
            dt_from = datetime.fromtimestamp(last_time, tz=timezone.utc)
            dt_to = datetime.fromtimestamp(int(time.time()), tz=timezone.utc)
            rates = mt5.copy_rates_range(symbol, timeframe, dt_from, dt_to)
        else:
            rates = mt5.copy_rates_from_pos(symbol, timeframe, 1, cfg.initial_bars)
        if rates is None or len(rates) == 0:
            return ("historie se nenačetla", 0)
        bars = rates_to_bars(rates, upper)
        if not bars:
            return ("bez nových uzavřených svíček", 0)
        total = 0
        for pos in range(0, len(bars), 150):
            chunk = bars[pos:pos + 150]
            post_chunk(key, symbol, cfg.timeframe, chunk, cfg.delay)
            # State is persisted AFTER each acknowledged chunk so a failure
            # never silently skips untransferred candles.
            state[state_id] = chunk[-1]["t"]
            save_state(state)
            total += len(chunk)
        return ("synchronizováno", total)
    finally:
        # Do not leave 700 additional symbols in the user's Market Watch.
        if not was_selected:
            mt5.symbol_select(symbol, False)


def run_cycle(mt5, cfg: argparse.Namespace, key: str, state: dict, symbols: list[str]) -> None:
    stats = {"ok": 0, "unchanged": 0, "failed": 0, "bars": 0}
    started = time.monotonic()
    for i, symbol in enumerate(symbols, 1):
        try:
            status, count = sync_one(mt5, symbol, cfg, key, state)
            if status == "synchronizováno":
                stats["ok"] += 1
                stats["bars"] += count
            elif status == "beze změny":
                stats["unchanged"] += 1
            else:
                stats["failed"] += 1
                log(f"[{i}/{len(symbols)}] {symbol}: {status}")
        except Exception as error:
            stats["failed"] += 1
            log(f"[{i}/{len(symbols)}] {symbol}: CHYBA {error}")
        if i % 25 == 0 or i == len(symbols):
            log(f"Průběh {i}/{len(symbols)} | nové {stats['ok']} | "
                f"beze změny {stats['unchanged']} | problémy {stats['failed']} | "
                f"odesláno svíček {stats['bars']:,}")
    log(f"Cyklus dokončen: {len(symbols)} instrumentů, {stats['bars']:,} svíček, "
        f"{stats['failed']} problémů. Doba {round(time.monotonic()-started)} s.")


def main() -> int:
    cfg = arguments()
    if not 1 <= cfg.max_symbols <= 20000 or not 1 <= cfg.initial_bars <= 5000:
        print("Chyba: --max-symbols 1..20000, --initial-bars 1..5000.", file=sys.stderr)
        return 2
    if cfg.delay < 0.1 or not 1 <= cfg.interval_minutes <= 1440:
        print("Chyba: --delay nejméně 0.1 s; --interval-minutes 1..1440.", file=sys.stderr)
        return 2
    try:
        import MetaTrader5 as mt5
    except ImportError:
        log("CHYBA: chybí knihovna MetaTrader5. Nainstaluj: py -3 -m pip install MetaTrader5")
        return 3
    initialized = mt5.initialize(path=cfg.terminal_path) if cfg.terminal_path else mt5.initialize()
    if not initialized:
        log(f"CHYBA: MT5 není dostupný. Otevři přihlášený terminál. Detail: {mt5.last_error()}")
        return 4
    try:
        symbols = get_symbols(mt5, cfg)
        log(f"Broker: {getattr(mt5.account_info(), 'server', 'nezjištěn')} | "
            f"nalezeno {len(symbols)} symbolů | zdroj: {cfg.universe}")
        if not symbols:
            log("Nenalezeny žádné symboly. Broker může mít jiný název složky akcií; "
                "zkus --universe marketwatch nebo --universe file.")
            return 5
        if cfg.discover:
            log("PŘEHLED SYMBOLŮ (bez stahování a odesílání dat):")
            for symbol in symbols: print(symbol)
            return 0
        key = get_api_key(cfg.reset_key)
        state = load_state()
        while True:
            run_cycle(mt5, cfg, key, state, symbols)
            if not cfg.loop:
                return 0
            log(f"Další kontrola nejdříve za {cfg.interval_minutes:g} minut. Ukončení: Ctrl+C.")
            time.sleep(cfg.interval_minutes * 60)
    except KeyboardInterrupt:
        log("Ukončeno uživatelem.")
        return 0
    except Exception as exc:
        log(f"CHYBA: {exc}")
        return 1
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
