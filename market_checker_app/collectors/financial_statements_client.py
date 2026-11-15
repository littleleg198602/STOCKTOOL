"""Explicit bounded HTTP access. Credentials and provider response bodies never enter errors/logs."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import hashlib
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from market_checker_app.analysis.financial_statements import normalize_sec, normalize_fmp, normalize_finnhub


def timestamp_order(value):
    return datetime.fromisoformat(value).timestamp()


class StatementsError(Exception):
    def __init__(self, code, stop_batch=False, retry_hours=1):
        super().__init__(code)
        self.code, self.stop_batch, self.retry_hours = code, stop_batch, retry_hours


class FinancialStatementsClient:
    def __init__(self, provider, credential="", sec_contact="", store=None, opener=None):
        if provider not in {"sec", "fmp", "finnhub"}:
            raise ValueError("Unknown financial statement provider")
        self.provider, self.credential, self.sec_contact = provider, credential.strip(), sec_contact.strip()
        self.store, self.opener = store, opener or urlopen
        self._last_request = 0.0

    def validate(self):
        if self.provider == "sec":
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", self.sec_contact):
                raise StatementsError("SEC_CONTACT_REQUIRED", True)
        elif not self.credential or self.credential.lower().startswith(("replace_", "your_", "example")):
            raise StatementsError("API_KEY_REQUIRED", True)

    def _get(self, url, params=None, *, document=False):
        # Sequential requests, <=1/s, no automatic retry storm.
        time.sleep(max(0.0, 1.05 - (time.monotonic() - self._last_request)))
        headers = {"Accept": "text/html" if document else "application/json", "User-Agent": "JOHNY-SKORE/1.1"}
        if self.provider == "sec":
            headers["User-Agent"] += " " + self.sec_contact
        if self.provider == "finnhub":
            headers["X-Finnhub-Token"] = self.credential
        if params:
            url += "?" + urlencode(params)
        try:
            self._last_request = time.monotonic()
            with self.opener(Request(url, headers=headers), timeout=25) as response:
                body = response.read(25_000_001)
                if len(body) > 25_000_000:
                    raise StatementsError("RESPONSE_TOO_LARGE")
            if document:
                return body
            payload = json.loads(body)
        except HTTPError as exc:
            # Never stringify HTTP errors: their URLs may contain the FMP key.
            code = int(exc.code)
            retry = exc.headers.get("Retry-After", "") if exc.headers else ""
            try:
                wait = max(1.0, min(168.0, float(retry) / 3600))
            except (TypeError, ValueError):
                wait = 1.0
            raise StatementsError(f"HTTP_{code}", code in {401, 402, 403, 429} or code >= 500,
                                  24 if code in {401, 402, 403} else wait) from None
        except (URLError, TimeoutError, OSError):
            raise StatementsError("NETWORK_ERROR", True) from None
        except (ValueError, UnicodeError):
            raise StatementsError("INVALID_JSON") from None
        if isinstance(payload, dict) and any(k in payload for k in ("error", "Error Message", "Information")):
            raise StatementsError("PROVIDER_REJECTED_REQUEST", True, 24)
        return payload

    def _sec_monitor(self, cik):
        from market_checker_app.analysis.sec_events import filing_candidates, extract_sec_item_excerpts, CATEGORIES
        now = datetime.now(timezone.utc)
        monitor = {"version": "sec_8k_review_v1", "status": "CHECKED", "events": [],
                   "lookback_days": 90, "max_documents": 3, "scoring_applied": False,
                   "coverage": "RECENT_SUBMISSIONS_ONLY", "errors": []}
        try:
            payload = self._get(f"https://data.sec.gov/submissions/CIK{cik}.json")
            filings = filing_candidates(payload, cik, now)
            monitor["eligible_filings"] = len(filings)
            selected = sorted(filings, key=lambda f: (not bool(set(f["items"]) & {"1.03", "2.04", "4.02"}), -timestamp_order(f["published_at"])))[:3]
            excerpts = {}
            for filing in selected:
                key = "sec_8k_document:" + cik + ":" + filing["accession"] + ":v1"
                cached = self.store.get_resource(key, max_age_days=3650) if self.store else None
                try:
                    if not isinstance(cached, dict):
                        body = self._get(filing["source_url"], document=True)
                        cached = {"sha256": hashlib.sha256(body).hexdigest(),
                                  "items": dict(extract_sec_item_excerpts(body, form=filing["form"]))}
                        if self.store:
                            self.store.put_resource(key, cached)
                    excerpts[filing["accession"]] = cached
                except StatementsError as exc:
                    monitor["status"] = "PARTIAL"
                    monitor["errors"].append(exc.code)
                    if exc.stop_batch:
                        monitor["source_blocked"] = True
                        if self.store:
                            self.store.record_status("*", "sec", "ERROR", error_code=exc.code, wait_hours=exc.retry_hours)
                        break
            if len(filings) > 3:
                monitor["status"] = "PARTIAL"
            chosen = {f["accession"] for f in selected}
            visible = selected + [f for f in filings if f["accession"] not in chosen]
            monitor["omitted_filings"] = max(0, len(filings)-12)
            for filing in visible[:12]:
                doc = excerpts.get(filing["accession"], {})
                for code in filing["items"]:
                    excerpt = doc.get("items", {}).get("Item " + code)
                    if not excerpt:
                        monitor["status"] = "PARTIAL"
                    monitor["events"].append({**filing, "item": code, "title": CATEGORIES[code][0],
                        "priority": CATEGORIES[code][1], "excerpt": excerpt,
                        "document_sha256": doc.get("sha256"),
                        "disclosure_status": "DOCUMENT_EXCERPT" if excerpt else "INDEX_ONLY",
                        "impact_status": "REVIEW_REQUIRED", "resolution_status": "UNKNOWN"})
        except StatementsError as exc:
            monitor.update(status="UNAVAILABLE", errors=[exc.code])
            if exc.stop_batch:
                monitor["source_blocked"] = True
            if exc.stop_batch and self.store:
                self.store.record_status("*", "sec", "ERROR", error_code=exc.code, wait_hours=exc.retry_hours)
        except (TypeError, ValueError, KeyError, AttributeError):
            monitor.update(status="UNAVAILABLE", errors=["INVALID_SUBMISSIONS"])
        monitor["observed_at"] = datetime.now(timezone.utc).isoformat()
        return monitor

    def fetch(self, ticker):
        self.validate()
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9.\-^=]{0,24}", ticker):
            raise StatementsError("INVALID_SYMBOL")
        if self.provider == "sec":
            mapping = self.store.get_resource("sec_company_tickers") if self.store else None
            if not mapping:
                raw_mapping = self._get("https://www.sec.gov/files/company_tickers.json")
                if not isinstance(raw_mapping, dict):
                    raise StatementsError("INVALID_SYMBOL_MAPPING", True)
                mapping = {str(v["ticker"]).upper(): str(v["cik_str"]).zfill(10)
                           for v in raw_mapping.values()
                           if isinstance(v, dict) and v.get("ticker") and str(v.get("cik_str", "")).isdigit()}
                if not mapping:
                    raise StatementsError("EMPTY_SYMBOL_MAPPING", True)
                if self.store:
                    self.store.put_resource("sec_company_tickers", mapping)
            cik = mapping.get(ticker) or mapping.get(ticker.replace(".", "-"))
            if not cik:
                raise StatementsError("SEC_TICKER_NOT_FOUND", retry_hours=168)
            raw = self._get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
            parser = normalize_sec
        elif self.provider == "fmp":
            raw = {}
            for kind, endpoint in (("income", "income-statement"), ("balance", "balance-sheet-statement"),
                                   ("cashflow", "cash-flow-statement")):
                raw[kind] = self._get("https://financialmodelingprep.com/stable/" + endpoint,
                                      {"symbol": ticker, "period": "annual", "limit": 6, "apikey": self.credential})
            parser = normalize_fmp
        else:
            raw = self._get("https://finnhub.io/api/v1/stock/financials-reported",
                            {"symbol": ticker, "freq": "annual"})
            parser = normalize_finnhub
        if not isinstance(raw, dict):
            raise StatementsError("INVALID_RESPONSE_SHAPE")
        monitor = self._sec_monitor(cik) if self.provider == "sec" else None
        if monitor is not None:
            raw["_sec_event_monitor"] = monitor
        fetched = datetime.now(timezone.utc).isoformat()
        try:
            reports = parser(raw, fetched)
        except (TypeError, ValueError, KeyError, AttributeError):
            raise StatementsError("UNSUPPORTED_STATEMENT_FORMAT") from None
        if not reports:
            raise StatementsError("NO_SUPPORTED_STATEMENTS", retry_hours=24)
        if monitor is not None:
            reports[0]["sec_events"] = monitor
        return reports, raw, fetched
