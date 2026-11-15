"""Experimental BUY learning from recorded, dated inputs; no score/order updates.

Labels use the next completed daily close after the signal and the Hth close
after that entry, both from ONE verified adjusted-price snapshot. Training
purges outcomes unavailable before each validation period. No downloads occur.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
from typing import Any, Callable
from uuid import uuid4

import numpy as np

from market_checker_app.analysis.financial_statements import (
    BUY_SCORING_VERSION, FEATURE_NAMES as STATEMENT_FEATURE_NAMES, METRICS as STATEMENT_METRICS,
    feature_vector as statement_feature_vector,
)

VERSION = "buy_learning_v7_sec_mapping"
STRATEGIES = ("B01", "B02", "B03", "B04", "B05", "B06")
BASE_FEATURE_NAMES = tuple(
    [f"{s.lower()}_score" for s in STRATEGIES]
    + [f"{s.lower()}_available" for s in STRATEGIES]
    + ["risk_penalty", "risk_available", "coverage", "coverage_available"]
)

FEATURE_NAMES = BASE_FEATURE_NAMES + STATEMENT_FEATURE_NAMES


def feature_names(config):
    return FEATURE_NAMES if config.include_statements else BASE_FEATURE_NAMES


@dataclass(frozen=True)
class LearningConfig:
    horizon_sessions: int = 20
    target: str = "absolute_return"
    benchmark: str = "SPY"
    scoring_version: str = BUY_SCORING_VERSION
    include_statements: bool = True
    min_statement_metrics: int = 4
    round_trip_cost_bps: float = 10.0
    min_samples: int = 200
    min_train_samples: int = 100
    min_validation_samples: int = 50
    min_train_dates: int = 15
    min_validation_dates: int = 5
    min_class_samples: int = 10
    min_available_strategies: int = 1
    embargo_days: int = 5
    max_feature_age_days: int = 7
    max_price_gap_days: int = 10
    min_validation_blocks: int = 3
    min_brier_improvement: float = 0.02
    model_max_age_days: int = 30
    l2: float = 0.02
    epochs: int = 700
    learning_rate: float = 0.08

    def validate(self) -> None:
        for name in ("horizon_sessions", "min_samples", "min_train_samples",
                     "min_validation_samples", "min_train_dates", "min_validation_dates",
                     "min_class_samples", "max_feature_age_days", "max_price_gap_days",
                     "min_validation_blocks", "model_max_age_days", "epochs"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not isinstance(self.include_statements, bool):
            raise ValueError("include_statements must be boolean")
        if not isinstance(self.min_statement_metrics, int) or not 1 <= self.min_statement_metrics <= len(STATEMENT_METRICS) - 1:
            raise ValueError("Invalid minimum statement metric count")
        if self.target not in {"absolute_return", "benchmark_excess_return"}:
            raise ValueError("Unknown learning target")
        if not self.benchmark.strip() or not self.scoring_version:
            raise ValueError("Benchmark and scoring version are required")
        if not 1 <= self.min_available_strategies <= len(STRATEGIES):
            raise ValueError("Invalid minimum strategy count")
        if not isinstance(self.embargo_days, int) or self.embargo_days < 0:
            raise ValueError("embargo_days must be a nonnegative integer")
        for value in (self.round_trip_cost_bps, self.l2, self.learning_rate,
                      self.min_brier_improvement):
            if _number(value) is None:
                raise ValueError("Learning parameters must be finite")
        if not 0 <= self.round_trip_cost_bps < 10000 or self.l2 < 0:
            raise ValueError("Invalid cost or regularization")
        if not 0 < self.learning_rate <= 0.1 or not 0 <= self.min_brier_improvement < 1:
            raise ValueError("Invalid learning rate or improvement threshold")


@dataclass(frozen=True)
class TrainingExample:
    as_of: datetime
    ticker: str
    features: tuple[float, ...]
    entry_day: date
    exit_day: date
    outcome_known_at: datetime
    label: int
    forward_return: float
    net_return: float
    target_return: float


@dataclass(frozen=True)
class _Snapshot:
    ticker: str
    observed: datetime
    signal_time: datetime
    payload: dict[str, Any]
    scoring_version: str
    prices: tuple[tuple[date, float], ...]
    verified_prices: bool


@dataclass(frozen=True)
class LearnedBUYModel:
    version: str
    model_id: str
    dataset_fingerprint: str
    config: dict[str, Any]
    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    supported_strategies: tuple[str, ...]
    trained_at: str
    trained_through: str
    evaluated_through: str
    training_samples: int
    holdout_samples: int
    holdout_brier: float
    baseline_brier: float
    holdout_log_loss: float
    status: str = "READY"

    @property
    def horizon_sessions(self) -> int:
        return int(self.config["horizon_sessions"])

    @property
    def target(self) -> str:
        return str(self.config["target"])

    def predict(self, payload: dict[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        result = {"probability": None, "status": "MODEL_UNAVAILABLE",
                  "horizon_sessions": self.horizon_sessions, "target": self.target}
        config = LearningConfig(**self.config)
        now = _utc(now) if now is not None else datetime.now(timezone.utc)
        if self.status != "READY" or self.version != VERSION:
            return result
        trained = _timestamp(self.trained_at)
        if trained is None or trained > now or now - trained > timedelta(days=config.model_max_age_days):
            return {**result, "status": "MODEL_STALE"}
        vector = _features(payload, config.include_statements)
        if config.include_statements:
            offset = len(BASE_FEATURE_NAMES) + len(STATEMENT_METRICS)
            supported_metrics = sum(v > 0 and self.means[i] > 0 for i, v in enumerate(vector)
                                    if offset <= i < offset + len(STATEMENT_METRICS) - 1)
            if supported_metrics < config.min_statement_metrics:
                return {**result, "status": "STATEMENTS_UNAVAILABLE"}
        supported = sum(vector[6 + STRATEGIES.index(s)] for s in self.supported_strategies)
        if supported < config.min_available_strategies:
            return {**result, "status": "INSUFFICIENT_FEATURES"}
        signal_time = _signal_time(payload)
        if signal_time is None or signal_time > now:
            return {**result, "status": "SIGNAL_TIME_MISSING"}
        evaluated = _timestamp(self.evaluated_through)
        if evaluated is None or signal_time <= evaluated:
            return {**result, "status": "HISTORICAL_INPUT"}
        price_days = [d for d, _ in _prices(payload) if d <= signal_time.date()]
        if (not price_days or (now.date() - price_days[-1]).days > config.max_feature_age_days
                or now - signal_time > timedelta(days=config.max_feature_age_days)):
            return {**result, "status": "STALE_INPUT"}
        if payload.get("scoring_version", config.scoring_version) != config.scoring_version:
            return {**result, "status": "SCORING_VERSION_MISMATCH"}
        z = self.intercept + sum(
            c * (v - m) / s
            for c, v, m, s in zip(self.coefficients, vector, self.means, self.scales)
        )
        return {**result, "status": "READY", "probability": round(_sigmoid(z), 6)}

    def predict_probability(self, payload: dict[str, Any]) -> float | None:
        return self.predict(payload)["probability"]


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return _utc(parsed)
    except (ValueError, TypeError):
        return None


def _signal_time(payload: dict[str, Any]) -> datetime | None:
    if "signal_as_of" in payload:
        return _timestamp(payload["signal_as_of"])
    strategies = payload.get("strategies")
    if not isinstance(strategies, dict):
        return None
    times = [_timestamp(v.get("as_of_timestamp")) for v in strategies.values() if isinstance(v, dict)]
    return max((t for t in times if t is not None), default=None)


def _features(payload: dict[str, Any], include_statements: bool = False) -> tuple[float, ...]:
    strategies = payload.get("strategies")
    strategies = strategies if isinstance(strategies, dict) else {}
    values, masks = [], []
    for sid in STRATEGIES:
        item = strategies.get(sid)
        item = item if isinstance(item, dict) else {}
        score = _number(item.get("score"))
        present = score is not None and 0 <= score <= 100 and item.get("status") in {"ACTIVE", "INACTIVE"}
        values.append(score / 100 if present else 0.5)
        masks.append(float(present))
    summary = payload.get("summary")
    summary = summary if isinstance(summary, dict) else {}
    risk, coverage = _number(summary.get("risk_penalty")), _number(summary.get("data_coverage"))
    risk_ok = risk is not None and 0 <= risk <= 100
    coverage_ok = coverage is not None and 0 <= coverage <= 1
    base = tuple(values + masks + [
        min(risk / 30, 1.0) if risk_ok else 0.5, float(risk_ok),
        coverage if coverage_ok else sum(masks) / 6, float(coverage_ok),
    ])
    return base + statement_feature_vector(payload.get("financial_statements"), _signal_time(payload)) if include_statements else base


def _prices(payload: dict[str, Any]) -> tuple[tuple[date, float], ...]:
    history = payload.get("price_history")
    if not isinstance(history, list):
        return ()
    result = {}
    for item in history:
        if not isinstance(item, dict):
            continue
        try:
            day = date.fromisoformat(str(item["date"])[:10])
        except (KeyError, TypeError, ValueError):
            continue
        close = _number(item.get("close"))
        if close is not None and close > 0:
            if day in result and result[day] != close:
                return ()  # ambiguous duplicate sessions
            result[day] = close
    return tuple(sorted(result.items()))


def _connection(db_path: str | Path, *, writable: bool = False) -> sqlite3.Connection:
    path = Path(db_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return sqlite3.connect(path.as_uri() + ("?mode=rw" if writable else "?mode=ro"), uri=True, timeout=15)


def _read_snapshots(db_path: str | Path, cutoff: datetime) -> tuple[list[_Snapshot], dict[str, Any]]:
    counts: Counter = Counter()
    try:
        with closing(_connection(db_path)) as connection:
            tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {"buy_history", "runs"}.issubset(tables):
                return [], {"status": "BUY_HISTORY_NOT_AVAILABLE"}
            rows = connection.execute(
                "SELECT b.ticker,b.payload_json,r.finished_at,b.scoring_version "
                "FROM buy_history b JOIN runs r ON b.run_id=r.run_id "
                "ORDER BY r.finished_at DESC,b.run_id DESC,b.ticker"
            )
            snapshots = []
            price_buckets = set()
            for ticker, raw, observed_text, scoring_version in rows:
                counts["raw_rows"] += 1
                observed = _timestamp(observed_text)
                if observed is None or observed > cutoff:
                    counts["invalid_or_future_timestamps"] += 1
                    continue
                try:
                    payload = json.loads(raw)
                except (TypeError, ValueError):
                    counts["invalid_payloads"] += 1
                    continue
                if not isinstance(payload, dict):
                    counts["invalid_payloads"] += 1
                    continue
                signal_time = _signal_time(payload)
                if signal_time is None and "signal_as_of" in payload:
                    counts["invalid_or_future_timestamps"] += 1
                    continue
                signal_time = signal_time or observed
                if signal_time > observed:
                    counts["invalid_or_future_timestamps"] += 1
                    continue
                all_prices = _prices(payload)
                prices = tuple((d, p) for d, p in all_prices if d < observed.date())
                verified = (payload.get("price_adjustment") == "split_and_dividend"
                            and payload.get("price_interval") == "1d"
                            and str(payload.get("price_source", "")).startswith("yfinance"))
                ticker = str(ticker).strip().upper()
                if not verified:
                    counts["snapshots_without_price_provenance"] += 1
                # Retain the latest verified price vintage per ticker/quarter.
                # Every retained vintage still supplies both endpoints of a label.
                # Historical feature rows remain available even when their
                # redundant multi-year price path is released from memory.
                bucket = (ticker, observed.year, (observed.month - 1) // 3)
                if verified and prices and bucket not in price_buckets:
                    price_buckets.add(bucket)
                else:
                    prices = ()
                feature_prices = [(d, v) for d, v in all_prices if d <= signal_time.date()]
                vector = _features(payload)
                compact = {
                    "signal_as_of": signal_time.isoformat(),
                    # The immutable BUY row retains full quarterly provenance. Training
                    # needs only validated feature values and report availability metadata.
                    "financial_statements": ({
                        key: payload["financial_statements"].get(key) for key in
                        ("schema", "status", "as_of", "available_at", "period_end", "basis",
                         "metrics", "reports")
                    } if isinstance(payload.get("financial_statements"), dict) else None),
                    "strategies": {
                        sid: {"score": vector[i] * 100 if vector[6+i] else None,
                              "status": "INACTIVE" if vector[6+i] else "DATA_MISSING"}
                        for i, sid in enumerate(STRATEGIES)
                    },
                    "summary": {"risk_penalty": vector[12] * 30 if vector[13] else None,
                                "data_coverage": vector[14] if vector[15] else None},
                    "price_history": ([{"date": feature_prices[-1][0].isoformat(),
                                        "close": feature_prices[-1][1]}] if feature_prices else []),
                }
                snapshots.append(_Snapshot(ticker, observed, signal_time,
                                           compact, str(scoring_version), prices, verified))
        snapshots.sort(key=lambda item: (item.signal_time, item.observed, item.ticker))
        counts["stored_signal_dates"] = len({item.signal_time.date() for item in snapshots})
        counts["stored_run_times"] = len({item.observed for item in snapshots})
        return snapshots, {"status": "OK", "counts": dict(counts)}
    except FileNotFoundError:
        return [], {"status": "HISTORY_DATABASE_MISSING"}
    except sqlite3.Error as exc:
        return [], {"status": "HISTORY_READ_FAILED", "error": str(exc)}


def _stock_outcome(signal: _Snapshot, paths: list[_Snapshot], config: LearningConfig):
    for snapshot in paths:
        prices = snapshot.prices
        if not prices or prices[0][0] > signal.signal_time.date():
            continue
        days = [d for d, _ in prices]
        entry = bisect_right(days, signal.signal_time.date())
        end = entry + config.horizon_sessions
        if end >= len(prices):
            continue
        if (days[entry] - signal.signal_time.date()).days > config.max_price_gap_days:
            continue
        if any((days[i] - days[i-1]).days > config.max_price_gap_days for i in range(entry+1, end+1)):
            continue
        return prices[end][1] / prices[entry][1] - 1.0, days[entry], days[end]
    return None


def _benchmark_return(paths: list[_Snapshot], entry: date, end: date) -> float | None:
    for snapshot in paths:
        values = dict(snapshot.prices)
        if entry in values and end in values:
            return values[end] / values[entry] - 1.0
    return None


def _collect(db_path: str | Path, config: LearningConfig, cutoff: datetime):
    snapshots, report = _read_snapshots(db_path, cutoff)
    report.update({"horizon_sessions": config.horizon_sessions, "target": config.target,
                   "benchmark": config.benchmark, "round_trip_cost_bps": config.round_trip_cost_bps,
                   "collected_at": cutoff.isoformat(), "version": VERSION})
    if report["status"] != "OK":
        return [], report
    counts = Counter(report.get("counts", {}))
    paths = defaultdict(list)
    for snapshot in snapshots:
        if snapshot.verified_prices and snapshot.prices:
            paths[snapshot.ticker].append(snapshot)
    for series in paths.values():
        series.sort(key=lambda s: s.observed, reverse=True)
    examples, seen = [], set()
    for signal in snapshots:
        if signal.ticker == config.benchmark.upper():
            continue
        if signal.scoring_version != config.scoring_version:
            counts["scoring_version_mismatch"] += 1
            continue
        vector = _features(signal.payload, config.include_statements)
        if config.include_statements and sum(vector[len(BASE_FEATURE_NAMES)+len(STATEMENT_METRICS):-1]) < config.min_statement_metrics:
            counts["insufficient_statement_metrics"] += 1
            continue
        if sum(vector[6:12]) < config.min_available_strategies:
            counts["insufficient_features"] += 1
            continue
        feature_prices = [(d, p) for d, p in _prices(signal.payload) if d <= signal.signal_time.date()]
        if (not feature_prices or
                (signal.signal_time.date() - feature_prices[-1][0]).days > config.max_feature_age_days):
            counts["stale_feature_prices"] += 1
            continue
        identity = (signal.ticker, signal.signal_time.date())
        if identity in seen:
            counts["duplicate_ticker_days"] += 1
            continue
        seen.add(identity)
        counts["eligible_signal_days"] += 1
        if not paths.get(signal.ticker):
            counts["missing_verified_price_paths"] += 1
            continue
        outcome = _stock_outcome(signal, paths[signal.ticker], config)
        if outcome is None:
            counts["pending_or_incomplete_outcomes"] += 1
            continue
        gross, entry, end = outcome
        net = gross - config.round_trip_cost_bps / 10000
        target_return = net
        if config.target == "benchmark_excess_return":
            benchmark = _benchmark_return(paths.get(config.benchmark.upper(), []), entry, end)
            if benchmark is None:
                counts["missing_benchmark_outcomes"] += 1
                continue
            target_return -= benchmark
        known_at = datetime.combine(end + timedelta(days=1), time(), tzinfo=timezone.utc)
        if known_at > cutoff:
            counts["pending_or_incomplete_outcomes"] += 1
            continue
        examples.append(TrainingExample(
            signal.signal_time, signal.ticker, vector, entry, end, known_at,
            int(target_return > 0), gross, net, target_return,
        ))
    examples.sort(key=lambda e: (e.as_of, e.ticker))
    counts["verified_price_snapshots"] = sum(len(v) for v in paths.values())
    report.update({
        "counts": dict(counts), "matured_examples": len(examples),
        "signal_dates": len({e.as_of.date() for e in examples}),
        "tickers": len({e.ticker for e in examples}),
        "positive_examples": sum(e.label for e in examples),
        "first_signal": examples[0].as_of.isoformat() if examples else None,
        "last_signal": examples[-1].as_of.isoformat() if examples else None,
        "feature_coverage": {sid: sum(e.features[6+i] for e in examples) / max(1, len(examples))
                             for i, sid in enumerate(STRATEGIES)},
    })
    if not examples:
        report["status"] = ("PRICE_PROVENANCE_MISSING" if snapshots and not paths
                            else "NO_MATURED_EXAMPLES")
    return examples, report


def inspect_history(db_path: str | Path, config: LearningConfig | None = None) -> dict[str, Any]:
    config = config or LearningConfig()
    config.validate()
    _, report = _collect(db_path, config, datetime.now(timezone.utc))
    return report


def collect_examples(db_path: str | Path, *, horizon_sessions: int = 20):
    config = LearningConfig(horizon_sessions=horizon_sessions)
    config.validate()
    examples, report = _collect(db_path, config, datetime.now(timezone.utc))
    return examples, report["status"]



def _sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-35.0, min(35.0, value))))


def _weights(examples: list[TrainingExample]) -> np.ndarray:
    # Equal mass per signal day; a large watchlist day cannot dominate the fit.
    counts = Counter(e.as_of.date() for e in examples)
    weights = np.array([1 / counts[e.as_of.date()] for e in examples], dtype=float)
    return weights / weights.sum()


def _fit(examples: list[TrainingExample], config: LearningConfig):
    raw = np.asarray([e.features for e in examples], dtype=float)
    labels = np.asarray([e.label for e in examples], dtype=float)
    weights = _weights(examples)
    means = weights @ raw
    scales = np.sqrt(weights @ ((raw - means) ** 2))
    scales[scales < 1e-8] = 1.0
    x = (raw - means) / scales
    rate = float(np.clip(weights @ labels, 1e-6, 1 - 1e-6))
    intercept = math.log(rate / (1 - rate))
    coefficients = np.zeros(raw.shape[1], dtype=float)
    previous = math.inf
    converged = False
    for epoch in range(config.epochs):
        logits = x @ coefficients + intercept
        probabilities = 1 / (1 + np.exp(-np.clip(logits, -35, 35)))
        error = weights * (probabilities - labels)
        loss = float(weights @ (np.logaddexp(0, logits) - labels * logits)
                     + config.l2 * (coefficients @ coefficients) / 2)
        if not math.isfinite(loss):
            raise ValueError("Non-finite training objective")
        if abs(previous - loss) < 1e-8:
            converged = True
            break
        previous = loss
        coefficients -= config.learning_rate * (x.T @ error + config.l2 * coefficients)
        intercept -= config.learning_rate * float(error.sum())
    return coefficients, float(intercept), means, scales, rate, epoch + 1, converged


def _probabilities(examples: list[TrainingExample], fit) -> np.ndarray:
    coefficients, intercept, means, scales = fit[:4]
    x = np.asarray([e.features for e in examples], dtype=float)
    return 1 / (1 + np.exp(-np.clip(((x - means) / scales) @ coefficients + intercept, -35, 35)))


def _metrics(examples: list[TrainingExample], probabilities: np.ndarray, base_rate: float):
    labels = np.asarray([e.label for e in examples], dtype=float)
    w = _weights(examples)
    p = np.clip(probabilities, 1e-9, 1 - 1e-9)
    base_rate = max(1e-9, min(1 - 1e-9, base_rate))
    brier = float(w @ ((p - labels) ** 2))
    baseline = float(w @ ((base_rate - labels) ** 2))
    log_loss = float(-w @ (labels * np.log(p) + (1-labels) * np.log1p(-p)))
    baseline_loss = float(-w @ (labels * math.log(base_rate) + (1-labels) * math.log1p(-base_rate)))
    bins = []
    bin_indices = np.minimum((p * 5).astype(int), 4)
    for index in range(5):
        low = index / 5
        mask = bin_indices == index
        mass = float(w[mask].sum())
        if mass:
            bins.append({"from": round(float(low), 2), "to": round(float(low + .2), 2),
                         "samples": int(mask.sum()),
                         "predicted": float(w[mask] @ p[mask] / mass),
                         "observed": float(w[mask] @ labels[mask] / mass)})
    return {
        "brier": brier, "baseline_brier": baseline,
        "relative_brier_improvement": 1 - brier / baseline if baseline > 0 else 0.0,
        "log_loss": log_loss, "baseline_log_loss": baseline_loss,
        "positive_rate": float(w @ labels),
        "mean_net_return": float(w @ np.asarray([e.net_return for e in examples])),
        "reliability_bins": bins,
    }


def _validation_blocks(examples: list[TrainingExample]) -> int:
    # Approximate disjoint outcome windows; row count is not an independent sample count.
    ends = {}
    for example in examples:
        day = example.as_of.date()
        ends[day] = max(ends.get(day, day), example.exit_day)
    blocks, current_end = 0, date.min
    for day, end in sorted(ends.items()):
        if day > current_end:
            blocks += 1
            current_end = end
    return blocks


def _fingerprint(examples: list[TrainingExample], config: LearningConfig) -> str:
    digest = hashlib.sha256(config_key(config).encode("ascii"))
    for e in examples:
        digest.update(json.dumps(
            [e.as_of.isoformat(), e.ticker, e.features, e.entry_day.isoformat(),
             e.exit_day.isoformat(), e.label, e.net_return, e.target_return],
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8"))
    return digest.hexdigest()


def config_key(config: LearningConfig) -> str:
    config.validate()
    content = json.dumps({"version": VERSION, "config": asdict(config),
                          "features": feature_names(config)}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def train_from_history(
    db_path: str | Path, *, horizon_sessions: int = 20, min_samples: int | None = None,
    config: LearningConfig | None = None, progress_callback: Callable[[str], None] | None = None,
) -> tuple[LearnedBUYModel | None, dict[str, Any]]:
    """Explicit training only. Returns the exact final-fold fit, never a refit on holdout."""
    config = config or LearningConfig(horizon_sessions=horizon_sessions)
    if min_samples is not None:
        config = replace(config, min_samples=min_samples)
    config.validate()
    progress = progress_callback or (lambda message: None)
    progress("Reading historical BUY inputs")
    cutoff = datetime.now(timezone.utc)
    examples, report = _collect(db_path, config, cutoff)
    report.update({"config": asdict(config), "config_key": config_key(config),
                   "required_samples": config.min_samples, "experimental": True})
    if report["status"] != "OK":
        return None, report
    fingerprint = _fingerprint(examples, config)
    report["dataset_fingerprint"] = fingerprint
    try:
        cached = load_model(db_path, config)
        if cached is not None and cached.dataset_fingerprint == fingerprint:
            previous = load_learning_report(db_path, config, model_id=cached.model_id) or {}
            report.update(previous)
            report["cached"] = True
            trained_at = _timestamp(cached.trained_at)
            if trained_at is None or cutoff - trained_at > timedelta(days=config.model_max_age_days):
                return None, {**report, "status": "MODEL_STALE"}
            report.update({"status": "READY", "model_id": cached.model_id})
            return cached, report
    except (ValueError, sqlite3.Error) as exc:
        report["model_cache_warning"] = str(exc)
    if len(examples) < config.min_samples:
        return None, {**report, "status": "NOT_ENOUGH_HISTORY"}
    dates = sorted({e.as_of.date() for e in examples})
    cuts = [int(len(dates) * f) for f in (.4, .6, .8)] + [len(dates)]
    if len(set(cuts)) != 4 or cuts[0] < config.min_train_dates:
        return None, {**report, "status": "INSUFFICIENT_TIME_PERIODS"}

    fold_reports, evaluated = [], []
    final_fit, final_training, final_validation = None, [], []
    for fold, (start_index, end_index) in enumerate(zip(cuts[:-1], cuts[1:]), 1):
        start = dates[start_index]
        end = dates[end_index] if end_index < len(dates) else date.max
        before = datetime.combine(start, time(), tzinfo=timezone.utc) - timedelta(days=config.embargo_days)
        candidates = [e for e in examples if e.as_of.date() < start]
        training = [e for e in candidates if e.outcome_known_at < before]
        validation = [e for e in examples if start <= e.as_of.date() < end]
        detail = {
            "fold": fold, "validation_start": start.isoformat(),
            "training_samples": len(training), "validation_samples": len(validation),
            "purged_samples": len(candidates) - len(training),
            "training_dates": len({e.as_of.date() for e in training}),
            "validation_dates": len({e.as_of.date() for e in validation}),
            "validation_end": validation[-1].as_of.date().isoformat() if validation else None,
        }
        if (len(training) < config.min_train_samples or len(validation) < config.min_validation_samples
                or detail["training_dates"] < config.min_train_dates
                or detail["validation_dates"] < config.min_validation_dates):
            fold_reports.append({**detail, "status": "INSUFFICIENT_FOLD_HISTORY"})
            continue
        if any(min(sum(e.label for e in rows), sum(1-e.label for e in rows)) < config.min_class_samples
               for rows in (training, validation)):
            fold_reports.append({**detail, "status": "INSUFFICIENT_CLASSES"})
            continue
        progress(f"Fitting chronological period {fold}/3")
        try:
            fit = _fit(training, config)
            metrics = _metrics(validation, _probabilities(validation, fit), fit[4])
            if config.include_statements:
                # Same dates, labels, costs, purge and hyperparameters; only direct statement features differ.
                base_train = [replace(e, features=e.features[:len(BASE_FEATURE_NAMES)]) for e in training]
                base_validation = [replace(e, features=e.features[:len(BASE_FEATURE_NAMES)]) for e in validation]
                base_fit = _fit(base_train, config)
                base_metrics = _metrics(base_validation, _probabilities(base_validation, base_fit), base_fit[4])
                metrics.update({
                    "without_statements_brier": base_metrics["brier"],
                    "without_statements_log_loss": base_metrics["log_loss"],
                    "statement_brier_improvement": 1 - metrics["brier"] / base_metrics["brier"] if base_metrics["brier"] > 0 else 0.0,
                })
        except (ValueError, FloatingPointError) as exc:
            fold_reports.append({**detail, "status": "NUMERICAL_FAILURE", "error": str(exc)})
            continue
        fold_reports.append({**detail, **metrics, "status": "EVALUATED",
                             "epochs": fit[5], "converged": fit[6]})
        evaluated.extend(validation)
        if fold == 3:
            final_fit, final_training, final_validation = fit, training, validation

    report["folds"] = fold_reports
    report["validation_blocks"] = _validation_blocks(evaluated)
    complete = [f for f in fold_reports if f["status"] == "EVALUATED"]
    if len(complete) != 3 or final_fit is None:
        return None, {**report, "status": "INSUFFICIENT_TEMPORAL_VALIDATION"}
    if report["validation_blocks"] < config.min_validation_blocks:
        return None, {**report, "status": "INSUFFICIENT_OUTCOME_WINDOWS"}
    final = complete[-1]
    improvements = sum(f["relative_brier_improvement"] >= config.min_brier_improvement for f in complete)
    report.update({
        "training_samples": len(final_training), "holdout_samples": len(final_validation),
        "holdout_start": final["validation_start"],
        "holdout_brier": final["brier"], "baseline_brier": final["baseline_brier"],
        "holdout_log_loss": final["log_loss"], "improved_periods": improvements,
    })
    if (improvements < 2 or final["relative_brier_improvement"] < config.min_brier_improvement
            or final["log_loss"] > final["baseline_log_loss"]):
        return None, {**report, "status": "NOT_BETTER_THAN_BASELINE"}

    if config.include_statements:
        statement_improvements = sum(f["statement_brier_improvement"] >= config.min_brier_improvement for f in complete)
        report["statement_improved_periods"] = statement_improvements
        report["without_statements_brier"] = final["without_statements_brier"]
        report["statement_brier_improvement"] = final["statement_brier_improvement"]
        if (statement_improvements < 2
                or final["statement_brier_improvement"] < config.min_brier_improvement
                or final["log_loss"] > final["without_statements_log_loss"]):
            return None, {**report, "status": "STATEMENTS_NOT_BETTER"}

    coefficients, intercept, means, scales = final_fit[:4]
    trained_through = max(e.outcome_known_at for e in final_training)
    evaluated_through = max(e.outcome_known_at for e in evaluated)
    model = LearnedBUYModel(
        version=VERSION, model_id=fingerprint[:24], dataset_fingerprint=fingerprint,
        config=asdict(config), feature_names=feature_names(config),
        means=tuple(map(float, means)), scales=tuple(map(float, scales)),
        coefficients=tuple(map(float, coefficients)), intercept=intercept,
        supported_strategies=tuple(sid for i, sid in enumerate(STRATEGIES)
                                   if any(e.features[6+i] for e in final_training)),
        trained_at=cutoff.isoformat(), trained_through=trained_through.isoformat(),
        evaluated_through=evaluated_through.isoformat(),
        training_samples=len(final_training), holdout_samples=len(final_validation),
        holdout_brier=final["brier"], baseline_brier=final["baseline_brier"],
        holdout_log_loss=final["log_loss"],
    )
    report.update({"status": "READY", "model_id": model.model_id,
                   "evaluated_through": model.evaluated_through,
                   "feature_coefficients": dict(zip(feature_names(config), model.coefficients))})
    progress("Training finished; experimental model passed configured gates")
    return model, report


def save_learning_result(db_path: str | Path, config: LearningConfig,
                         model: LearnedBUYModel | None, report: dict[str, Any]) -> None:
    """Append an audit record and retain accepted JSON models in the existing DB."""
    key = config_key(config)
    if report.get("config_key") != key:
        raise ValueError("Report/config mismatch")
    if model is not None and (model.status != "READY" or model.config != asdict(config)
                              or model.version != VERSION):
        raise ValueError("Cannot persist incompatible learning model")
    created_at = datetime.now(timezone.utc).isoformat()
    report_json = json.dumps(report, ensure_ascii=False, allow_nan=False)
    with closing(_connection(db_path, writable=True)) as connection, connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS buy_learning_models (model_id TEXT PRIMARY KEY, "
            "config_key TEXT NOT NULL, created_at TEXT NOT NULL, model_json TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS buy_learning_attempts (attempt_id TEXT PRIMARY KEY, "
            "config_key TEXT NOT NULL, created_at TEXT NOT NULL, status TEXT NOT NULL, "
            "model_id TEXT, report_json TEXT NOT NULL)"
        )
        if model is not None:
            connection.execute(
                "INSERT OR IGNORE INTO buy_learning_models VALUES (?,?,?,?)",
                (model.model_id, key, model.trained_at,
                 json.dumps(asdict(model), ensure_ascii=False, allow_nan=False)),
            )
        connection.execute(
            "INSERT INTO buy_learning_attempts VALUES (?,?,?,?,?,?)",
            (uuid4().hex, key, created_at, str(report.get("status", "UNKNOWN")),
             model.model_id if model else None, report_json),
        )


def load_model(db_path: str | Path, config: LearningConfig) -> LearnedBUYModel | None:
    key = config_key(config)
    try:
        with closing(_connection(db_path)) as connection:
            if not connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='buy_learning_models'"
            ).fetchone():
                return None
            row = connection.execute(
                "SELECT model_json FROM buy_learning_models WHERE config_key=? "
                "ORDER BY created_at DESC LIMIT 1", (key,),
            ).fetchone()
    except FileNotFoundError:
        return None
    if row is None:
        return None
    try:
        values = json.loads(row[0])
        if not isinstance(values, dict):
            raise ValueError("Invalid model document")
        if values.get("version") != VERSION or values.get("config") != asdict(config):
            raise ValueError("Incompatible model schema")
        for field in ("feature_names", "means", "scales", "coefficients", "supported_strategies"):
            values[field] = tuple(values[field])
        if values["feature_names"] != feature_names(config):
            raise ValueError("Feature schema mismatch")
        for field in ("means", "scales", "coefficients"):
            if len(values[field]) != len(feature_names(config)) or any(_number(v) is None for v in values[field]):
                raise ValueError("Invalid numeric model parameters")
            values[field] = tuple(float(v) for v in values[field])
        if any(v <= 0 for v in values["scales"]) or _number(values["intercept"]) is None:
            raise ValueError("Invalid model scale/intercept")
        values["intercept"] = float(values["intercept"])
        for field in ("holdout_brier", "baseline_brier", "holdout_log_loss"):
            if _number(values.get(field)) is None or float(values[field]) < 0:
                raise ValueError("Invalid evaluation metrics")
            values[field] = float(values[field])
        if (any(s not in STRATEGIES for s in values["supported_strategies"])
                or not all(_timestamp(values.get(k)) for k in
                           ("trained_at", "trained_through", "evaluated_through"))):
            raise ValueError("Invalid model provenance")
        return LearnedBUYModel(**values)
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("Stored learning model is invalid; retraining is required") from exc


def load_learning_report(db_path: str | Path, config: LearningConfig,
                         *, model_id: str | None = None) -> dict[str, Any] | None:
    """Recover the last attempt or a particular accepted model's evaluation."""
    key = config_key(config)
    try:
        with closing(_connection(db_path)) as connection:
            if not connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='buy_learning_attempts'"
            ).fetchone():
                return None
            query = "SELECT report_json FROM buy_learning_attempts WHERE config_key=?"
            args = [key]
            if model_id is not None:
                query += " AND model_id=? AND status='READY'"
                args.append(model_id)
            row = connection.execute(query + " ORDER BY created_at DESC LIMIT 1", args).fetchone()
    except FileNotFoundError:
        return None
    if row is None:
        return None
    report = json.loads(row[0])
    if not isinstance(report, dict) or report.get("config_key") != key:
        raise ValueError("Invalid saved learning report")
    return report
