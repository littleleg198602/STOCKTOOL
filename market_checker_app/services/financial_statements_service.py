"""Resumable statement refresh and deterministic linkage to existing BUY strategies."""
from __future__ import annotations

from collections import defaultdict
from time import time
from datetime import datetime, timezone

from market_checker_app.analysis.buy_analysis import _clamp, _percentile
from market_checker_app.analysis.financial_statements import SCHEMA, normalize_sec, analyze_reports, number, ratio, timestamp
from market_checker_app.collectors.financial_statements_client import FinancialStatementsClient, StatementsError
from market_checker_app.storage.financial_statements_store import FinancialStatementsStore


class FinancialStatementsService:
    def __init__(self, db_path):
        self.store = FinancialStatementsStore(db_path)

    def refresh(self, tickers, provider="sec", credential="", sec_contact="", max_items=5,
                progress_callback=None):
        if not 1 <= max_items <= 20:
            raise ValueError("Statement batch must contain 1 to 20 tickers")
        client = FinancialStatementsClient(provider, credential, sec_contact, self.store)
        client.validate()  # no database changes when settings are missing
        self.store.ensure_schema()
        normalized = list(dict.fromkeys(str(t).strip().upper() for t in tickers if str(t).strip()))
        candidates = self.store.candidates(normalized, provider, max_items)
        result = {"attempted": 0, "succeeded": 0, "failed": 0, "stopped": False, "items": []}
        for ticker in candidates:
            result["attempted"] += 1
            try:
                remapped = False
                cached = self.store.raw_for_sec_remap(ticker) if provider == "sec" else None
                if cached is not None:
                    raw = cached["raw"]
                    try:
                        reports = normalize_sec(raw, cached["source_fetched_at"])
                    except (TypeError, ValueError, KeyError, AttributeError):
                        reports = []
                    if reports:
                        remapped = True
                        fetched = datetime.now(timezone.utc).isoformat()
                        for report in reports:
                            report["normalizer_version"] = SCHEMA
                            report["source_fetched_at"] = cached["source_fetched_at"]
                            report["remapped_from_snapshot"] = cached["source_snapshot_id"]
                        if isinstance(raw.get("_sec_event_monitor"), dict):
                            reports[0]["sec_events"] = raw["_sec_event_monitor"]
                if not remapped:
                    reports, raw, fetched = client.fetch(ticker)
                    for report in reports:
                        report["normalizer_version"] = SCHEMA
                self.store.save(ticker, provider, reports, raw, fetched)
                # Remapping is not a new download and must not extend source TTL.
                remaining_hours = (max(0., 24-(datetime.now(timezone.utc)-timestamp(
                    cached["source_fetched_at"])).total_seconds()/3600) if remapped else 24)
                self.store.record_status(ticker, provider, "OK", wait_hours=remaining_hours)
                if remapped:
                    result["remapped_from_cache"] = result.get("remapped_from_cache", 0) + 1
                status = "OK"
                result["succeeded"] += 1
                monitor = raw.get("_sec_event_monitor", {})
                if monitor.get("source_blocked") and not remapped:
                    result["stopped"] = True
                    result["source_error_code"] = (monitor.get("errors") or ["SEC_EVENT_SOURCE_UNAVAILABLE"])[-1]
            except StatementsError as exc:
                status = exc.code
                self.store.record_status(ticker, provider, "ERROR", error_code=exc.code, wait_hours=exc.retry_hours)
                result["failed"] += 1
                if exc.stop_batch:
                    self.store.record_status("*", provider, "ERROR", error_code=exc.code, wait_hours=exc.retry_hours)
                    result["stopped"] = True
            result["items"].append({"ticker": ticker, "status": status})
            if progress_callback:
                progress_callback(result["attempted"], len(candidates), ticker, status)
            if result["stopped"]:
                break
        return result

    ACCESS_ERRORS = ("HTTP_401", "HTTP_402", "HTTP_403", "PROVIDER_REJECTED_REQUEST")
    UNSUPPORTED_ERRORS = {
        "SEC_TICKER_NOT_FOUND", "INVALID_SYMBOL", "NO_SUPPORTED_ANNUAL_STATEMENTS", "NO_SUPPORTED_STATEMENTS",
        "UNSUPPORTED_STATEMENT_FORMAT", "INVALID_RESPONSE_SHAPE", "RESPONSE_TOO_LARGE",
        "HTTP_404", "HTTP_422",
    }

    @staticmethod
    def _deadline(state):
        value = timestamp(state.get("next_attempt_at"))
        return value.timestamp() if value is not None else 0.0

    def start_refresh(self, tickers, provider="sec", credential="", sec_contact=""):
        """One user-authorized run; credentials remain outside the job/report document."""
        FinancialStatementsClient(provider, credential, sec_contact, self.store).validate()
        self.store.ensure_schema()
        # A new explicit click permits a single recheck after correcting credentials.
        # Do not reset transient rate-limit/network cooldowns.
        self.store.retry_access_errors(provider, self.ACCESS_ERRORS)
        tickers = list(dict.fromkeys(str(t).strip().upper() for t in tickers if str(t).strip()))
        states, now = self.store.statuses(provider), time()
        pending = [t for t in tickers if not (
            states.get(t, {}).get("status") == "OK" and self._deadline(states[t]) > now)]
        return {
            "provider": provider, "tickers": tickers, "pending": pending,
            "active": bool(pending), "status": "running" if pending else "complete",
            "initial_fresh": len(tickers) - len(pending), "saved": 0, "reused": 0,
            "attempts": {}, "errors": {}, "failed": {}, "last_ticker": "",
            "next_action_at": 0.0, "source_failures": 0, "error_code": "",
        }

    def step_refresh(self, job, credential="", sec_contact=""):
        """Advance one ticker, keeping the UI responsive between requests and waits."""
        if not job["active"] or time() < job["next_action_at"]:
            return job
        states, now = self.store.statuses(job["provider"]), time()
        for ticker in list(job["pending"]):
            state = states.get(ticker, {})
            deadline = self._deadline(state)
            if state.get("status") == "OK" and deadline > now:
                job["pending"].remove(ticker)
                job["reused"] += 1
                job["errors"].pop(ticker, None)
            elif state.get("error_code") in self.UNSUPPORTED_ERRORS and deadline > now:
                job["pending"].remove(ticker)
                job["failed"][ticker] = state["error_code"]
                job["errors"][ticker] = state["error_code"]
        if not job["pending"]:
            job.update(active=False, status="complete_with_errors" if job["failed"] else "complete")
            return job
        global_state = states.get("*", {})
        if self._deadline(global_state) > now:
            code = global_state.get("error_code", "")
            if code in self.ACCESS_ERRORS or code in {"INVALID_SYMBOL_MAPPING", "EMPTY_SYMBOL_MAPPING"}:
                job.update(active=False, status="access_blocked", error_code=code)
            else:
                job.update(status="waiting_source", error_code=code,
                           next_action_at=self._deadline(global_state))
            return job
        eligible = [t for t in job["pending"] if self._deadline(states.get(t, {})) <= now]
        if not eligible:
            job.update(status="waiting_retry",
                       next_action_at=min(self._deadline(states.get(t, {})) for t in job["pending"]))
            return job
        ticker = eligible[0]
        job.update(status="running", last_ticker=ticker)
        outcome = self.refresh([ticker], job["provider"], credential, sec_contact, max_items=1)
        job["next_action_at"] = time() + 1.1
        if outcome["attempted"]:
            job["attempts"][ticker] = job["attempts"].get(ticker, 0) + 1
            code = outcome["items"][0]["status"]
            if outcome["succeeded"]:
                job["saved"] += 1
                job["pending"].remove(ticker)
                job["errors"].pop(ticker, None)
            else:
                job["errors"][ticker] = code
                if code in self.UNSUPPORTED_ERRORS or job["attempts"][ticker] >= 2:
                    job["failed"][ticker] = code
                    job["pending"].remove(ticker)
            if outcome["stopped"]:
                code = outcome.get("source_error_code", code)
                job["error_code"] = code
                if code in self.ACCESS_ERRORS or code in {"INVALID_SYMBOL_MAPPING", "EMPTY_SYMBOL_MAPPING"}:
                    job.update(active=False, status="access_blocked")
                    return job
                job["source_failures"] += 1
                if job["source_failures"] >= 5:
                    job.update(active=False, status="source_unavailable")
                    return job
                updated = self.store.statuses(job["provider"])
                job.update(status="waiting_source", next_action_at=max(
                    time() + 1.1, self._deadline(updated.get("*", {}))))
        if not job["pending"]:
            job.update(active=False, status="complete_with_errors" if job["failed"] else "complete")
        return job

    def analyze(self, metadata, market_caps, as_of=None):
        as_of = as_of or datetime.now(timezone.utc)
        cached = self.store.reports_at(list(metadata), as_of)
        details, inputs = {}, {}
        for ticker, data in metadata.items():
            observed = timestamp(data.get("_metadata_fetched_at"))
            fresh_valuation = (observed is not None and observed <= as_of
                               and (as_of - observed).total_seconds() <= 7 * 86400
                               and data.get("currency") == "USD")
            cap = number(data.get("marketCap")) if fresh_valuation else None
            detail = analyze_reports(cached.get(ticker, []), as_of, str(data.get("sector") or ""), cap)
            record = detail["fundamental_inputs"]
            # Current valuation is shared by eligible TTM and annual inputs, never stale prices.
            for candidate in (record, detail.get("annual_fundamental_inputs", {})):
                if candidate and fresh_valuation and candidate.get("currency") == "USD":
                    ev = number(data.get("enterpriseValue"))
                    if ev is not None and ev > 0:
                        candidate["enterprise_value"] = ev
                        detail["valuation_source"] = "Yahoo metadata; USD"
                        detail["valuation_observed_at"] = observed.isoformat()
                        candidate["valuation_observed_at"] = observed.isoformat()
            details[ticker], inputs[ticker] = detail, record
        prepare_peer_scores(inputs)
        annual_inputs = {t: d.get("annual_fundamental_inputs", {}) for t, d in details.items()}
        prepare_peer_scores(annual_inputs)
        for ticker, record in inputs.items():
            if record and record.get("period_basis", "FY") == "FY":
                record.update(annual_inputs.get(ticker, {}))
        return details, inputs


def prepare_peer_scores(records):
    """Three passes remove the old circular dependency on precomputed peer quality/value."""
    groups = defaultdict(list)
    for record in records.values():
        if record:
            groups[(record.get("sector"), record.get("currency"), record.get("period_basis", "FY"))].append(record)
    for peers in groups.values():
        if len(peers) < 5:
            continue
        gross = {}
        for index, p in enumerate(peers):
            a, b = number(p.get("assets")), number(p.get("prior_assets"))
            rev, cogs = number(p.get("revenue")), number(p.get("cogs"))
            if None not in (a, b, rev, cogs) and a > 0 and b > 0:
                gross[index] = (rev - cogs) / ((a + b) / 2)
        for index, p in enumerate(peers):
            if index not in gross:
                continue
            pct = _percentile(gross[index], list(gross.values()), 5)
            debt, ebitda = number(p.get("net_debt")), number(p.get("ebitda"))
            avg = (p["assets"] + p["prior_assets"]) / 2
            ni, cf = number(p.get("net_income")), number(p.get("operating_cash_flow"))
            if None in (pct, debt, ebitda, ni, cf) or ebitda <= 0:
                continue
            p["quality_score"] = _clamp(
                .35 * pct + .20 * _clamp(50 + 200 * ni / avg)
                + .20 * _clamp(50 + 200 * cf / avg)
                + .15 * _clamp(50 - 200 * (ni - cf) / avg)
                + .10 * (100 if debt / ebitda <= 3 else 0))
        for p in peers:
            p["book_market"] = ratio(p.get("book_equity"), p.get("market_cap"))
            for field, key in (("fcf_ev", "free_cash_flow"), ("ebit_ev", "ebit"), ("sales_ev", "revenue")):
                p[field] = ratio(p.get(key), p.get("enterprise_value"))
        for p in peers:
            percentiles = {}
            for key in ("fcf_ev", "ebit_ev", "book_market", "sales_ev"):
                if p.get(key) is not None:
                    percentiles[key] = _percentile(p[key], [q[key] for q in peers if q.get(key) is not None], 5)
            if len(percentiles) == 4 and all(v is not None for v in percentiles.values()):
                p["value_score"] = sum(w * percentiles[k] for k, w in
                                       (("fcf_ev", .35), ("ebit_ev", .30), ("book_market", .20), ("sales_ev", .15)))
                if p.get("quality_score") is not None:
                    p["combined_score"] = .5 * p["quality_score"] + .5 * p["value_score"]
