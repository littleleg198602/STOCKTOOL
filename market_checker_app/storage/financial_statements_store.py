"""Append-only statement snapshots and bounded refresh state in the application's SQLite DB."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

from market_checker_app.analysis.financial_statements import SCHEMA, EVENTS_SCHEMA, LEGACY_SCHEMA, PERIODS_SCHEMA, MAPPING_SCHEMA, timestamp


class FinancialStatementsStore:
    def __init__(self, db_path):
        self.db_path = Path(db_path)

    def _connect(self, writable=False):
        if writable:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            return sqlite3.connect(self.db_path, timeout=15)
        return sqlite3.connect(self.db_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=15)

    def ensure_schema(self):
        with closing(self._connect(True)) as conn, conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS financial_statement_snapshots (
                    snapshot_id TEXT PRIMARY KEY, ticker TEXT NOT NULL, provider TEXT NOT NULL,
                    fetched_at TEXT NOT NULL, schema_version TEXT NOT NULL,
                    reports_json TEXT NOT NULL, raw_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS financial_statement_lookup
                    ON financial_statement_snapshots(ticker, fetched_at);
                CREATE TABLE IF NOT EXISTS financial_statement_refresh (
                    ticker TEXT NOT NULL, provider TEXT NOT NULL, checked_at TEXT NOT NULL,
                    next_attempt_at TEXT NOT NULL, status TEXT NOT NULL, error_code TEXT,
                    PRIMARY KEY(ticker, provider)
                );
                CREATE TABLE IF NOT EXISTS financial_statement_resources (
                    resource_key TEXT PRIMARY KEY, fetched_at TEXT NOT NULL, payload_json TEXT NOT NULL
                );
            """)
            columns = {r[1] for r in conn.execute("PRAGMA table_info(financial_statement_snapshots)")}
            if "content_hash" not in columns:
                conn.execute("ALTER TABLE financial_statement_snapshots ADD COLUMN content_hash TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS financial_statement_content "
                         "ON financial_statement_snapshots(ticker,provider,content_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS financial_statement_vintages "
                         "ON financial_statement_snapshots(ticker,provider,fetched_at)")

    def statuses(self, provider):
        if not self.db_path.is_file():
            return {}
        with closing(self._connect()) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='financial_statement_refresh'").fetchone():
                return {}
            rows = conn.execute(
                "SELECT r.ticker,r.checked_at,r.next_attempt_at,r.status,r.error_code,"
                "(SELECT s.schema_version FROM financial_statement_snapshots s "
                "WHERE s.ticker=r.ticker AND s.provider=r.provider "
                "ORDER BY s.fetched_at DESC,s.snapshot_id LIMIT 1) "
                "FROM financial_statement_refresh r WHERE r.provider=?", (provider,))
            result = {}
            for ticker, checked, deadline, status, error, schema in rows:
                # Old annual cache remains readable, but an explicit refresh must not
                # skip it merely because the old parser downloaded it today.
                upgrade = provider == "sec" and status == "OK" and schema != SCHEMA
                result[ticker] = {"checked_at": checked,
                                  "next_attempt_at": None if upgrade else deadline,
                                  "status": "SCHEMA_REFRESH_REQUIRED" if upgrade else status,
                                  "error_code": error, "schema_version": schema}
            return result

    def candidates(self, tickers, provider, limit, now=None):
        now = now or datetime.now(timezone.utc)
        states = self.statuses(provider)
        global_state = states.get("*", {})
        if (timestamp(global_state.get("next_attempt_at")) or now) > now:
            return []
        eligible = []
        for ticker in dict.fromkeys(tickers):
            state = states.get(ticker, {})
            if (timestamp(state.get("next_attempt_at")) or now) <= now:
                eligible.append(ticker)
        return sorted(eligible, key=lambda t: (states.get(t, {}).get("status") == "OK",
                                               states.get(t, {}).get("checked_at", "")))[:limit]

    def retry_access_errors(self, provider, codes):
        """An explicit new start can recheck corrected access settings; keep all snapshots."""
        if not codes:
            return
        with closing(self._connect(True)) as conn, conn:
            marks = ",".join("?" for _ in codes)
            conn.execute(
                f"UPDATE financial_statement_refresh SET next_attempt_at=? "
                f"WHERE provider=? AND error_code IN ({marks})",
                (datetime.now(timezone.utc).isoformat(), provider, *codes),
            )

    def record_status(self, ticker, provider, status, *, error_code=None, wait_hours=24):
        now = datetime.now(timezone.utc)
        with closing(self._connect(True)) as conn, conn:
            conn.execute(
                "INSERT INTO financial_statement_refresh VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(ticker,provider) DO UPDATE SET checked_at=excluded.checked_at,"
                "next_attempt_at=excluded.next_attempt_at,status=excluded.status,error_code=excluded.error_code",
                (ticker, provider, now.isoformat(), (now + timedelta(hours=wait_hours)).isoformat(), status, error_code),
            )

    def save(self, ticker, provider, reports, raw, fetched_at):
        # Snapshot identity includes fetch time: repeated downloads retain their own evidence.
        raw_json = json.dumps(raw, ensure_ascii=False, sort_keys=True, allow_nan=False)
        content_hash = hashlib.sha256(raw_json.encode("utf-8")).hexdigest()
        snapshot_id = hashlib.sha256((ticker + provider + fetched_at + content_hash).encode("utf-8")).hexdigest()
        with closing(self._connect(True)) as conn, conn:
            previous = conn.execute(
                "SELECT snapshot_id FROM financial_statement_snapshots WHERE ticker=? AND provider=? "
                "AND content_hash=? ORDER BY fetched_at,snapshot_id LIMIT 1",
                (ticker, provider, content_hash),
            ).fetchone()
            # Unchanged source bodies reference the first immutable snapshot.
            # The new observation still retains its own timestamp and normalized inputs.
            stored_raw = json.dumps({"same_source_as": previous[0], "sha256": content_hash}) if previous else raw_json
            conn.execute(
                "INSERT OR IGNORE INTO financial_statement_snapshots "
                "(snapshot_id,ticker,provider,fetched_at,schema_version,reports_json,raw_json,content_hash) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (snapshot_id, ticker, provider, fetched_at, SCHEMA,
                 json.dumps(reports, ensure_ascii=False, allow_nan=False), stored_raw, content_hash),
            )
        return snapshot_id

    def raw_for_sec_remap(self, ticker, now=None):
        """Read a fresh older-schema SEC body, resolving immutable dedup references.

        Does not change history or renew source freshness. Missing/invalid bodies
        fall back to the existing network refresh, not invented statement values.
        """
        now = now or datetime.now(timezone.utc)
        if not self.db_path.is_file():
            return None
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT snapshot_id,fetched_at,schema_version,raw_json,reports_json "
                "FROM financial_statement_snapshots WHERE ticker=? AND provider='sec' "
                "ORDER BY fetched_at DESC,snapshot_id LIMIT 1", (ticker,),
            ).fetchone()
            if row is None or row[2] == SCHEMA:
                return None
            try:
                reports = json.loads(row[4])
                observed = [timestamp(r.get("retrieved_at")) for r in reports if isinstance(r, dict)]
                observed = [t for t in observed if t is not None]
                source_time = min(observed) if observed else timestamp(row[1])
                if source_time is None or not timedelta(0) <= now-source_time < timedelta(hours=24):
                    return None
                raw = json.loads(row[3])
                seen = {row[0]}
                for _ in range(8):
                    if not isinstance(raw, dict):
                        return None
                    reference = raw.get("same_source_as")
                    if reference is None:
                        if not isinstance(raw.get("facts"), dict):
                            return None
                        return {"raw": raw, "source_fetched_at": source_time.isoformat(),
                                "source_snapshot_id": row[0]}
                    if reference in seen:
                        return None
                    seen.add(reference)
                    referenced = conn.execute(
                        "SELECT raw_json FROM financial_statement_snapshots "
                        "WHERE snapshot_id=? AND ticker=? AND provider='sec'",
                        (reference, ticker),
                    ).fetchone()
                    if referenced is None:
                        return None
                    body = json.loads(referenced[0])
                    # Current storage references the first full body directly.
                    if isinstance(body, dict) and "same_source_as" not in body:
                        digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
                                                          allow_nan=False).encode("utf-8")).hexdigest()
                        if digest != raw.get("sha256"):
                            return None
                    raw = body
            except (ValueError, TypeError, AttributeError):
                return None
        return None

    def reports_at(self, tickers, as_of):
        result = {t: [] for t in tickers}
        if not self.db_path.is_file():
            return result
        with closing(self._connect()) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='financial_statement_snapshots'").fetchone():
                return result
            # Bounded batches avoid SQLite's parameter limit; historical vintages remain unchanged.
            items = list(result)
            for offset in range(0, len(items), 300):
                batch = items[offset:offset+300]
                placeholders = ",".join("?" for _ in batch)
                rows = conn.execute(
                    "SELECT snapshot_id,ticker,provider,reports_json FROM financial_statement_snapshots "
                    "WHERE snapshot_id IN (SELECT snapshot_id FROM ("
                    "SELECT snapshot_id,ROW_NUMBER() OVER (PARTITION BY ticker,provider "
                    "ORDER BY fetched_at DESC,snapshot_id) AS position FROM financial_statement_snapshots "
                    f"WHERE ticker IN ({placeholders}) AND fetched_at<=? AND schema_version IN (?,?,?,?,?)"
                    ") WHERE position=1)",
                    (*batch, as_of.isoformat(), SCHEMA, LEGACY_SCHEMA, PERIODS_SCHEMA, MAPPING_SCHEMA, EVENTS_SCHEMA),
                )
                seen = set()
                for snapshot_id, ticker, provider, raw in rows:
                    key = (ticker, provider)
                    if key in seen:
                        continue
                    try:
                        reports = json.loads(raw)
                        if not isinstance(reports, list):
                            continue
                        result[ticker].extend({**r, "snapshot_id": snapshot_id} for r in reports if isinstance(r, dict))
                        seen.add(key)
                    except (ValueError, TypeError):
                        continue
        return result

    def get_resource(self, key, max_age_days=7):
        if not self.db_path.is_file():
            return None
        with closing(self._connect()) as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='financial_statement_resources'").fetchone():
                return None
            row = conn.execute("SELECT fetched_at,payload_json FROM financial_statement_resources WHERE resource_key=?", (key,)).fetchone()
        if row and timestamp(row[0]) and datetime.now(timezone.utc) - timestamp(row[0]) < timedelta(days=max_age_days):
            return json.loads(row[1])
        return None

    def put_resource(self, key, payload):
        with closing(self._connect(True)) as conn, conn:
            conn.execute(
                "INSERT INTO financial_statement_resources VALUES(?,?,?) ON CONFLICT(resource_key) "
                "DO UPDATE SET fetched_at=excluded.fetched_at,payload_json=excluded.payload_json",
                (key, datetime.now(timezone.utc).isoformat(), json.dumps(payload, allow_nan=False)),
            )
