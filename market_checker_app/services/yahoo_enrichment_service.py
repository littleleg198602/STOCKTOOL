from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from time import sleep, time

from market_checker_app.collectors.yahoo_client import YahooClient
from market_checker_app.storage.yahoo_cache_store import YahooCacheCoverage, YahooCacheStore


YahooRefreshCallback = Callable[[int, int, str, str, YahooCacheCoverage], None]


@dataclass(frozen=True)
class YahooRefreshResult:
    candidates: int
    attempted: int
    succeeded: int
    partial: int
    failed: int
    rate_limited: bool
    remaining: int
    coverage: YahooCacheCoverage
    warnings: list[str]
    batches: int = 1


class YahooEnrichmentService:
    """Populate persistent Yahoo metadata and adjusted prices through separate refresh paths."""

    def __init__(
        self,
        cache: YahooCacheStore,
        client: YahooClient | None = None,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        self.cache = cache
        self.client = client or YahooClient()
        self._sleep = sleep_fn


    def refresh_price_history(
        self, watchlist: Iterable[str], *, max_items: int = 20,
        include_benchmark: bool = True, delay_seconds: float = 0.75,
        progress_callback: Callable[[int, int, str, str], None] | None = None,
    ) -> dict[str, object]:
        """One explicit bounded batch, persisted after each ticker; no metadata download."""
        if not 1 <= max_items <= 50:
            raise ValueError("Price refresh batch must contain 1 to 50 tickers")
        tickers = list(dict.fromkeys(
            (["SPY"] if include_benchmark else []) +
            [str(t).strip().upper() for t in watchlist if str(t).strip()]
        ))
        candidates = self.cache.price_refresh_candidates(tickers)[:max_items]
        attempted = succeeded = failed = 0
        warnings = []
        for ticker in candidates:
            if self.client.is_rate_limited():
                break
            symbol = self.client.normalize_yahoo_symbol(ticker)
            frame, warning = self.client.fetch_ohlc_only(symbol, period="2y", interval="1d")
            attempted += 1
            try:
                if frame is None or frame.empty:
                    raise ValueError(warning or "Price history unavailable")
                self.cache.upsert_price_success(ticker, frame, yahoo_ticker=symbol)
                succeeded += 1
                status = "saved"
            except ValueError as exc:
                failed += 1
                status = "failed"
                message = f"{ticker}: {exc}"
                if self.client.is_rate_limited():
                    self.cache.upsert_price_failure(
                        ticker, message, retry_after_seconds=self.client.rate_limit_remaining_seconds())
                else:
                    self.cache.upsert_price_failure(ticker, message)
                warnings.append(message)
            if progress_callback:
                progress_callback(attempted, len(candidates), ticker, status)
            if self.client.is_rate_limited():
                break
            if attempted < len(candidates):
                self._sleep(max(0.25, delay_seconds))
        coverage = self.cache.price_coverage(tickers)
        return {
            "attempted": attempted, "succeeded": succeeded, "failed": failed,
            "remaining": coverage["total"] - coverage["fresh"],
            "rate_limited": self.client.is_rate_limited(),
            "coverage": coverage, "warnings": warnings,
        }


    def start_price_refresh(self, watchlist: Iterable[str], *, include_benchmark: bool = True) -> dict:
        """Freeze the universe for this refresh, including tickers waiting after an earlier error."""
        tickers = list(dict.fromkeys(
            (["SPY"] if include_benchmark else []) +
            [str(t).strip().upper() for t in watchlist if str(t).strip()]
        ))
        schedule = self.cache.price_refresh_schedule(tickers)
        pending = [t for t in tickers if not schedule[t]["fresh"]]
        return {
            "tickers": tickers, "pending": pending, "active": bool(pending),
            "status": "running" if pending else "complete", "next_action_at": 0.0,
            "initial_fresh": len(tickers) - len(pending), "saved": 0, "reused": 0,
            "attempts": {}, "errors": {}, "failed": {}, "last_ticker": "",
            "rate_limit_events": 0, "started_at": time(),
        }

    def step_price_refresh(self, job: dict) -> dict:
        """One bounded work unit per UI tick; waiting never blocks the Streamlit session.

        At most two failed downloads per ticker, and five rate-limit responses per
        run. Persistence is performed by refresh_price_history before advancing.
        """
        if not job["active"]:
            return job
        now = time()
        if now < job["next_action_at"]:
            return job
        schedule = self.cache.price_refresh_schedule(job["pending"])
        for ticker in list(job["pending"]):
            if schedule[ticker]["fresh"]:
                job["pending"].remove(ticker)
                job["reused"] += 1
                job["errors"].pop(ticker, None)
        if not job["pending"]:
            job.update(active=False, status="complete_with_errors" if job["failed"] else "complete")
            return job
        pause = self.client.rate_limit_remaining_seconds()
        if pause > 0:
            job.update(status="waiting_yahoo", next_action_at=now + pause)
            return job
        eligible = [t for t in job["pending"] if schedule[t]["retry_at"] <= now]
        if not eligible:
            job.update(status="waiting_retry", next_action_at=min(
                schedule[t]["retry_at"] for t in job["pending"]))
            return job
        ticker = eligible[0]
        job.update(status="running", last_ticker=ticker)
        result = self.refresh_price_history([ticker], max_items=1, include_benchmark=False)
        now = time()
        job["next_action_at"] = now + 1.0
        if result["attempted"]:
            job["attempts"][ticker] = job["attempts"].get(ticker, 0) + 1
            if result["succeeded"]:
                job["saved"] += 1
                job["pending"].remove(ticker)
                job["errors"].pop(ticker, None)
            elif result["failed"]:
                error = "; ".join(result["warnings"]) or "Price history unavailable"
                job["errors"][ticker] = error
                if job["attempts"][ticker] >= 2:
                    job["failed"][ticker] = error
                    job["pending"].remove(ticker)
        if result["rate_limited"]:
            if result["attempted"]:
                job["rate_limit_events"] += 1
            job.update(status="waiting_yahoo",
                       next_action_at=now + max(60.0, self.client.rate_limit_remaining_seconds()))
            if job["rate_limit_events"] >= 5:
                job.update(active=False, status="source_unavailable")
        if not job["pending"]:
            job.update(active=False, status="complete_with_errors" if job["failed"] else "complete")
        return job

    def refresh(
        self,
        watchlist: Iterable[str],
        *,
        max_items: int | None = None,
        delay_seconds: float = 0.75,
        progress_callback: YahooRefreshCallback | None = None,
    ) -> YahooRefreshResult:
        tickers = list(dict.fromkeys(str(ticker).strip().upper() for ticker in watchlist if str(ticker).strip()))
        candidates = self.cache.list_tickers_needing_refresh(tickers)
        if max_items is not None:
            if max_items < 1:
                raise ValueError("max_items must be at least 1 or None")
            candidates = candidates[:max_items]

        attempted = succeeded = partial = failed = 0
        warnings: list[str] = []
        was_rate_limited = False

        for ticker in candidates:
            if self.client.is_rate_limited():
                was_rate_limited = True
                break

            snapshot, warning = self.client.fetch_metadata(ticker)
            attempted += 1
            yahoo_ticker = snapshot.ticker or self.client.normalize_yahoo_symbol(ticker)

            if snapshot.status in {"ok", "partial"} and snapshot.data:
                payload = dict(snapshot.data)
                payload["_market_checker_yahoo_quality"] = snapshot.status
                self.cache.upsert_success(
                    ticker,
                    payload,
                    yahoo_ticker=yahoo_ticker,
                )
                succeeded += 1
                partial += int(snapshot.status == "partial")
                status = snapshot.status
            else:
                message = warning or f"Yahoo metadata nejsou dostupná pro {yahoo_ticker}."
                self.cache.upsert_failure(
                    ticker,
                    message,
                    yahoo_ticker=yahoo_ticker,
                )
                warnings.append(message)
                failed += 1
                status = "failed"

            coverage = self.cache.coverage(tickers)
            if progress_callback:
                progress_callback(attempted, len(candidates), ticker, status, coverage)

            if self.client.is_rate_limited():
                was_rate_limited = True
                break
            if delay_seconds > 0 and attempted < len(candidates):
                self._sleep(delay_seconds)

        coverage = self.cache.coverage(tickers)
        # Report all symbols that still lack a fresh snapshot. Failed entries
        # may be in their retry cooldown and therefore absent from the next
        # immediate candidate list, but they must not be presented as done.
        remaining = coverage.total - coverage.fresh - coverage.unsupported
        return YahooRefreshResult(
            candidates=len(candidates),
            attempted=attempted,
            succeeded=succeeded,
            partial=partial,
            failed=failed,
            rate_limited=was_rate_limited,
            remaining=remaining,
            coverage=coverage,
            warnings=warnings,
        )

    def refresh_all(
        self,
        watchlist: Iterable[str],
        *,
        batch_size: int = 100,
        delay_seconds: float = 0.75,
        progress_callback: YahooRefreshCallback | None = None,
    ) -> YahooRefreshResult:
        """Refresh every currently eligible ticker in automatic batches.

        A batch boundary is only a checkpoint; it does not require another UI
        click.  The loop stops when no ticker is immediately refreshable or
        Yahoo activates its rate-limit guard.  Failed tickers remain stored
        with their retry deadline and are not hammered repeatedly in the same
        run.
        """

        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")

        tickers = list(
            dict.fromkeys(
                str(ticker).strip().upper()
                for ticker in watchlist
                if str(ticker).strip()
            )
        )
        initial_candidates = self.cache.list_tickers_needing_refresh(tickers)
        total_candidates = len(initial_candidates)
        attempted = succeeded = partial = failed = batches = 0
        warnings: list[str] = []
        rate_limited = False

        while self.cache.list_tickers_needing_refresh(tickers):
            attempted_before_batch = attempted

            def _on_batch_progress(
                completed: int,
                _batch_total: int,
                ticker: str,
                status: str,
                coverage: YahooCacheCoverage,
            ) -> None:
                if progress_callback:
                    progress_callback(
                        attempted_before_batch + completed,
                        total_candidates,
                        ticker,
                        status,
                        coverage,
                    )

            result = self.refresh(
                tickers,
                max_items=batch_size,
                delay_seconds=delay_seconds,
                progress_callback=_on_batch_progress,
            )
            if result.candidates == 0 or result.attempted == 0:
                rate_limited = rate_limited or result.rate_limited
                break

            batches += 1
            attempted += result.attempted
            succeeded += result.succeeded
            partial += result.partial
            failed += result.failed
            warnings.extend(result.warnings)
            rate_limited = rate_limited or result.rate_limited
            if rate_limited:
                break

            if self.cache.list_tickers_needing_refresh(tickers) and delay_seconds > 0:
                self._sleep(delay_seconds)

        coverage = self.cache.coverage(tickers)
        remaining = coverage.total - coverage.fresh - coverage.unsupported
        return YahooRefreshResult(
            candidates=total_candidates,
            attempted=attempted,
            succeeded=succeeded,
            partial=partial,
            failed=failed,
            rate_limited=rate_limited,
            remaining=remaining,
            coverage=coverage,
            warnings=warnings,
            batches=batches,
        )
