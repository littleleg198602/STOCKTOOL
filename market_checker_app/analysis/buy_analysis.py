"""Deterministic, point-in-time BUY strategy evaluation.

Unavailable observations are represented by DATA_MISSING and never by zero.
No trading orders are generated here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import floor, isfinite
from statistics import pstdev
from typing import Any, Mapping

import pandas as pd

DEFAULT_WEIGHTS = {
    "momentum": 0.35, "fundamental": 0.40, "event": 0.25,
    "B01": 0.65, "B02": 0.35,
    "B03": 0.35, "B04": 0.35, "B06": 0.30, "B05": 1.0,
}
GROUPS = {"momentum": ("B01", "B02"), "fundamental": ("B03", "B04", "B06"), "event": ("B05",)}
NAMES = {
    "B01": "Cross-sectional momentum", "B02": "52-week high breakout",
    "B03": "Quality / profitability", "B04": "Value + quality",
    "B05": "Positive earnings surprise / PEAD", "B06": "Piotroski F-score value",
}
TIMEFRAMES = {"B01": "1-6 months", "B02": "days-8 weeks", "B03": "3-12 months",
              "B04": "3-12 months", "B05": "5-60 days", "B06": "3-12 months"}
CONFIG = {
    "lookback_days": 252, "skip_days": 21, "enter_percentile": 80,
    "breakout_window": 20, "proximity_min": 0.97, "volume_window": 20,
    "min_volume_ratio": 1.5, "ema_fast": 50, "ema_slow": 200,
    "min_quality_percentile": 70, "min_value_percentile": 70,
    "min_f_score": 8, "min_sue": 1.0, "min_coverage": 0.70,
    "max_risk_penalty": 30, "risk_per_trade": 0.005,
    "max_position_pct": 0.10,
}


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)


def _strategy(sid: str, status: str = "DATA_MISSING", score: float | None = None,
              values: Mapping[str, Any] | None = None, passed: list[str] | None = None,
              failed: list[str] | None = None, source: str = "",
              entry: float | None = None, stop: float | None = None,
              exit_conditions: list[str] | None = None) -> dict[str, Any]:
    return {
        "strategy_id": sid, "strategy_name": NAMES[sid], "timeframe": TIMEFRAMES[sid],
        "score": score, "status": status, "signal_strength": score if status == "ACTIVE" else 0,
        "data_coverage": 1.0 if score is not None else 0.0,
        "confidence": 1.0 if score is not None else 0.0,
        "feature_values": dict(values or {}), "conditions_passed": passed or [],
        "conditions_failed": failed or [], "entry_trigger": entry,
        "invalidation_level": stop, "exit_conditions": exit_conditions or [],
        "as_of_timestamp": datetime.now(timezone.utc).isoformat(),
        "source_provenance": source,
    }


def _percentile(value: float, peers: list[float], minimum: int = 20) -> float | None:
    if len(peers) < minimum:
        return None
    return 100.0 * sum(peer <= value for peer in peers) / len(peers)


def _price_frame(frame: pd.DataFrame | None, source: str) -> pd.DataFrame | None:
    if frame is None or frame.empty or "Close" not in frame:
        return None
    data = frame.copy()
    # Yahoo Adj Close is split/dividend adjusted; MT5 prices lack that guarantee.
    if source.startswith("yfinance") and "Adj Close" in data:
        factor = pd.to_numeric(data["Adj Close"], errors="coerce") / pd.to_numeric(data["Close"], errors="coerce")
        for field in ("Open", "High", "Low", "Close"):
            if field in data:
                data[field] = pd.to_numeric(data[field], errors="coerce") * factor
    elif source == "mt5":
        return None
    data = data.sort_index()
    for field in ("Open", "High", "Low", "Close", "Volume"):
        if field in data:
            data[field] = pd.to_numeric(data[field], errors="coerce")
    return data.dropna(subset=["Close"])


def _atr(data: pd.DataFrame) -> float | None:
    if len(data) < 15 or not {"High", "Low", "Close"}.issubset(data):
        return None
    tr = pd.concat([
        data["High"] - data["Low"],
        (data["High"] - data["Close"].shift()).abs(),
        (data["Low"] - data["Close"].shift()).abs(),
    ], axis=1).max(axis=1)
    return _number(tr.tail(14).mean())


def evaluate_prices(frame: pd.DataFrame | None, source: str, peers: list[float],
                    sector_peers: list[float], benchmark_momentum: float | None,
                    config: Mapping[str, Any] = CONFIG) -> dict[str, dict[str, Any]]:
    result = {sid: _strategy(sid) for sid in ("B01", "B02")}
    data = _price_frame(frame, source)
    if data is None:
        return result
    close = data["Close"]
    latest = _number(close.iloc[-1])
    ema200 = _number(close.ewm(span=200, adjust=False, min_periods=200).mean().iloc[-1])
    if latest is None:
        return result
    atr = _atr(data)
    lookback = int(config["lookback_days"])
    skip = int(config["skip_days"])
    if len(close) > lookback and ema200 is not None:
        base = _number(close.iloc[-lookback - 1])
        skipped = _number(close.iloc[-skip - 1])
        momentum = skipped / base - 1 if base and skipped and base > 0 else None
        percentile = _percentile(momentum, peers) if momentum is not None else None
        sector_percentile = _percentile(momentum, sector_peers, 5) if momentum is not None else None
        if momentum is not None and percentile is not None and sector_percentile is not None and benchmark_momentum is not None:
            checks = {
                "universe_percentile": percentile >= float(config["enter_percentile"]),
                "sector_relative": momentum > sorted(sector_peers)[len(sector_peers) // 2],
                "benchmark_relative": momentum > benchmark_momentum,
                "above_ema200": latest > ema200,
            }
            score = _clamp(0.55 * percentile + 0.20 * sector_percentile +
                           15 * (momentum > benchmark_momentum) + 10 * (latest > ema200))
            result["B01"] = _strategy(
                "B01", "ACTIVE" if all(checks.values()) else "INACTIVE", score,
                {"mom_12_2": momentum, "percentile": percentile,
                 "sector_percentile": sector_percentile, "benchmark_momentum": benchmark_momentum,
                 "ema200": ema200, "atr14": atr},
                [k for k, v in checks.items() if v], [k for k, v in checks.items() if not v],
                source, latest, latest - 2.5 * atr if atr else None,
                ["percentile below 60", "ATR trailing stop", "126 trading days"],
            )
    high_window = int(config["lookback_days"])
    breakout_window = int(config["breakout_window"])
    if len(data) > high_window and {"High", "Volume"}.issubset(data):
        prev_high = _number(data["High"].iloc[-high_window - 1:-1].max())
        prev20 = _number(data["High"].iloc[-breakout_window - 1:-1].max())
        avg_volume = _number(data["Volume"].iloc[-int(config["volume_window"]) - 1:-1].mean())
        volume = _number(data["Volume"].iloc[-1])
        ema50 = _number(close.ewm(span=int(config["ema_fast"]), adjust=False, min_periods=int(config["ema_fast"])).mean().iloc[-1])
        ratio = volume / avg_volume if volume is not None and avg_volume and avg_volume > 0 else None
        if prev_high and prev20 and ema50 is not None and ema200 is not None and ratio is not None:
            checks = {
                "near_52week_high": latest / prev_high >= float(config["proximity_min"]),
                "breakout_20": latest > prev20,
                "volume_confirmation": ratio >= float(config["min_volume_ratio"]),
                "trend": latest > ema50 > ema200 if ema200 is not None else False,
            }
            breakout_score = _clamp(50 + 1000 * (latest / prev_high - 0.97))
            volume_score = _clamp(50 * ratio / float(config["min_volume_ratio"]))
            trend_score = 100.0 if checks["trend"] else 0.0
            score = _clamp(0.45 * breakout_score + 0.30 * volume_score + 0.25 * trend_score)
            result["B02"] = _strategy(
                "B02", "ACTIVE" if all(checks.values()) else "INACTIVE", score,
                {"high_ratio": latest / prev_high, "previous_252_high": prev_high,
                 "previous_20_high": prev20, "volume_ratio": ratio,
                 "ema50": ema50, "ema200": ema200, "atr14": atr,
                 "breakout_score": breakout_score, "volume_score": volume_score,
                 "trend_score": trend_score},
                [k for k, v in checks.items() if v], [k for k, v in checks.items() if not v],
                source, prev20, min(prev20, latest - 2 * atr) if atr else None,
                ["breakout failure", "ATR trailing stop", "60 trading days"],
            )
    return result


def evaluate_fundamentals(data: Mapping[str, Any] | None, sector_records: list[Mapping[str, Any]],
                          config: Mapping[str, Any] = CONFIG) -> dict[str, dict[str, Any]]:
    """Only dated, published statement records are eligible."""
    result = {sid: _strategy(sid) for sid in ("B03", "B04", "B06")}
    if not data or not data.get("published_at") or not data.get("prior_published_at"):
        return result
    try:
        published = pd.Timestamp(data["published_at"], tz="UTC") if pd.Timestamp(data["published_at"]).tzinfo is None else pd.Timestamp(data["published_at"]).tz_convert("UTC")
        prior_published = pd.Timestamp(data["prior_published_at"], tz="UTC") if pd.Timestamp(data["prior_published_at"]).tzinfo is None else pd.Timestamp(data["prior_published_at"]).tz_convert("UTC")
        if prior_published > published or published > pd.Timestamp.now(tz="UTC"):
            return result
    except (ValueError, TypeError):
        return result
    if data.get("period_end") and data.get("prior_period_end"):
        if str(data["prior_period_end"]) >= str(data["period_end"]):
            return result
    sector = str(data.get("sector", "")).lower()
    if any(token in sector for token in ("financial", "bank", "insurance", "real estate", "reit")):
        return {sid: _strategy(sid, "NOT_APPLICABLE") for sid in result}
    if len(sector_records) < 5 or data.get("price_above_ema200") is None:
        return result
    above_ema = bool(data["price_above_ema200"])
    assets = _number(data.get("assets"))
    old_assets = _number(data.get("prior_assets"))
    revenue = _number(data.get("revenue"))
    cogs = _number(data.get("cogs"))
    ocf = _number(data.get("operating_cash_flow"))
    income = _number(data.get("net_income"))
    if not all(v is not None for v in (assets, old_assets, revenue, cogs, ocf, income)) or assets + old_assets <= 0:
        return result
    avg_assets = (assets + old_assets) / 2
    gross = (revenue - cogs) / avg_assets
    roa = income / avg_assets
    ocf_assets = ocf / avg_assets
    accruals = (income - ocf) / avg_assets
    peers = []
    for peer in sector_records:
        pa, pb = _number(peer.get("assets")), _number(peer.get("prior_assets"))
        pr, pc = _number(peer.get("revenue")), _number(peer.get("cogs"))
        if None not in (pa, pb, pr, pc) and pa + pb > 0:
            peers.append((pr - pc) / ((pa + pb) / 2))
    gross_pct = _percentile(gross, peers, 5)
    # Missing EBITDA prevents quality scoring, but does not erase independent F-score inputs.
    debt, ebitda = _number(data.get("net_debt")), _number(data.get("ebitda"))
    quality, quality_pct = None, None
    if gross_pct is not None and debt is not None and ebitda is not None and ebitda > 0:
        safety = 100 if debt / ebitda <= 3 else 0
        quality = _clamp(.35 * gross_pct + .20 * _clamp(50 + 200 * roa) +
                         .20 * _clamp(50 + 200 * ocf_assets) +
                         .15 * _clamp(50 - 200 * accruals) + .10 * safety)
        quality_pct = _percentile(quality, [_number(p.get("quality_score")) for p in sector_records
                                             if _number(p.get("quality_score")) is not None], 5)
        if quality_pct is not None:
            checks = {"quality_percentile": quality_pct >= float(config["min_quality_percentile"]),
                      "gross_percentile": gross_pct >= 60, "positive_ocf": ocf > 0,
                      "above_ema200": above_ema}
            result["B03"] = _strategy("B03", "ACTIVE" if all(checks.values()) else "INACTIVE", quality,
                {"gross_profitability": gross, "roa": roa, "ocf_assets": ocf_assets,
                 "accruals": accruals, "net_debt_ebitda": debt / ebitda,
                 "gross_percentile": gross_pct, "quality_percentile": quality_pct},
                [k for k, v in checks.items() if v], [k for k, v in checks.items() if not v],
                str(data.get("source", "")), exit_conditions=["quality percentile below 50"])
    ev = _number(data.get("enterprise_value"))
    fcf = _number(data.get("free_cash_flow"))
    ebit = _number(data.get("ebit"))
    book = _number(data.get("book_equity"))
    cap = _number(data.get("market_cap"))
    if ev and ev > 0 and cap and cap > 0 and None not in (fcf, ebit, book) and quality_pct is not None:
        ratios = {"fcf_ev": fcf / ev, "ebit_ev": ebit / ev, "book_market": book / cap, "sales_ev": revenue / ev}
        weights = {"fcf_ev": .35, "ebit_ev": .30, "book_market": .20, "sales_ev": .15}
        percentiles = {}
        for key, value in ratios.items():
            observed = [_number(p.get(key)) for p in sector_records]
            percentile = _percentile(value, [v for v in observed if v is not None], 5)
            if percentile is None:
                break
            percentiles[key] = percentile
        if len(percentiles) == 4:
            value_score = sum(weights[k] * percentiles[k] for k in weights)
            value_pct = _percentile(value_score, [_number(p.get("value_score")) for p in sector_records
                                                   if _number(p.get("value_score")) is not None], 5)
            combined = .5 * value_score + .5 * quality
            combined_pct = _percentile(combined, [_number(p.get("combined_score")) for p in sector_records
                                                   if _number(p.get("combined_score")) is not None], 5)
            if value_pct is not None and combined_pct is not None:
                checks = {"value_percentile": value_pct >= float(config["min_value_percentile"]),
                          "quality_percentile": quality_pct >= 60, "combined_percentile": combined_pct >= 75,
                          "positive_fcf": fcf > 0, "above_ema200": above_ema}
                result["B04"] = _strategy("B04", "ACTIVE" if all(checks.values()) else "INACTIVE",
                    _clamp(combined), {**ratios, "value_percentile": value_pct,
                                       "quality_percentile": quality_pct, "combined_percentile": combined_pct},
                    [k for k, v in checks.items() if v], [k for k, v in checks.items() if not v],
                    str(data.get("source", "")), exit_conditions=["combined percentile below 50"])
    prior = data.get("prior") or {}
    keys = ("prior_roa", "prior_debt_ratio", "debt_ratio", "prior_current_ratio", "current_ratio",
            "prior_shares", "shares", "prior_gross_margin", "gross_margin",
            "prior_asset_turnover", "asset_turnover")
    values = {k: _number(data.get(k)) for k in keys}
    if all(v is not None for v in values.values()):
        points = {
            "positive_roa": roa > 0, "positive_ocf": ocf > 0,
            "roa_growth": roa > values["prior_roa"], "cash_flow_exceeds_roa": ocf_assets > roa,
            "debt_ratio_declines": values["debt_ratio"] < values["prior_debt_ratio"],
            "current_ratio_rises": values["current_ratio"] > values["prior_current_ratio"],
            "no_new_shares": values["shares"] <= values["prior_shares"],
            "gross_margin_rises": values["gross_margin"] > values["prior_gross_margin"],
            "asset_turnover_rises": values["asset_turnover"] > values["prior_asset_turnover"],
        }
        book_pct = _percentile(book / cap, [_number(p.get("book_market")) for p in sector_records
                                             if _number(p.get("book_market")) is not None], 5) if book is not None and cap and cap > 0 else None
        if book_pct is not None:
            f_score = sum(points.values())
            checks = {"book_to_market_percentile": book_pct >= 70,
                      "f_score": f_score >= int(config["min_f_score"]), "above_ema200": above_ema}
            result["B06"] = _strategy("B06", "ACTIVE" if all(checks.values()) else "INACTIVE",
                _clamp(f_score / 9 * 100), {"f_score": f_score, "points": points,
                                             "book_to_market_percentile": book_pct},
                [k for k, v in checks.items() if v], [k for k, v in checks.items() if not v],
                str(data.get("source", "")), exit_conditions=["F-score below 6"])
    return result


def evaluate_earnings(event: Mapping[str, Any] | None, config: Mapping[str, Any] = CONFIG) -> dict[str, Any]:
    if not event:
        return _strategy("B05")
    required = ("announced_at", "consensus_as_of", "actual_eps", "consensus_eps",
                "prior_surprises", "event_return", "entry_gap_pct", "volume_ratio")
    if any(event.get(k) is None for k in required):
        return _strategy("B05")
    announced = pd.Timestamp(event["announced_at"], tz="UTC") if pd.Timestamp(event["announced_at"]).tzinfo is None else pd.Timestamp(event["announced_at"]).tz_convert("UTC")
    consensus_at = pd.Timestamp(event["consensus_as_of"], tz="UTC") if pd.Timestamp(event["consensus_as_of"]).tzinfo is None else pd.Timestamp(event["consensus_as_of"]).tz_convert("UTC")
    if consensus_at >= announced:
        return _strategy("B05")
    prior = [_number(v) for v in event["prior_surprises"]]
    if len(prior) < 8 or any(v is None for v in prior):
        return _strategy("B05")
    deviation = pstdev(prior[-8:])
    if deviation <= 0:
        return _strategy("B05")
    surprise = float(event["actual_eps"]) - float(event["consensus_eps"])
    sue = surprise / deviation
    reaction = float(event["event_return"])
    gap = float(event["entry_gap_pct"])
    checks = {"sue": sue >= float(config["min_sue"]), "positive_reaction": reaction > 0,
              "gap": gap <= .08}
    score = _clamp(35 + 20 * sue + 200 * reaction + 5 * min(float(event["volume_ratio"]), 3) - 100 * max(0, gap - .08))
    return _strategy("B05", "ACTIVE" if all(checks.values()) else "INACTIVE", score,
        {"surprise": surprise, "sue": sue, "event_return": reaction, "entry_gap_pct": gap,
         "volume_ratio": event["volume_ratio"]},
        [k for k, v in checks.items() if v], [k for k, v in checks.items() if not v],
        str(event.get("source", "")), exit_conditions=["40 trading days", "2 ATR stop"])


def risk_penalty(frame: pd.DataFrame | None, source: str, market_cap: float | None,
                 config: Mapping[str, Any] = CONFIG) -> tuple[float, list[str]]:
    data = _price_frame(frame, source)
    if data is None or len(data) < 21:
        return 0.0, ["price risk data unavailable"]
    close = _number(data["Close"].iloc[-1])
    atr = _atr(data)
    if not close or not atr:
        return 0.0, ["ATR unavailable"]
    flags = []
    penalty = 0.0
    if atr / close > .05:
        penalty += 10
        flags.append("high ATR / close")
    returns = data["Close"].pct_change().dropna().tail(63)
    if len(returns) >= 20 and returns.std() * (252 ** .5) > .6:
        penalty += 8
        flags.append("high realized volatility")
    if {"Open", "Close"}.issubset(data):
        gaps = (data["Open"] / data["Close"].shift() - 1).abs().tail(63)
        if gaps.max() > .10:
            penalty += 5
            flags.append("large historical gap")
    if "Volume" in data:
        dollar_volume = (data["Close"] * data["Volume"]).tail(20).mean()
        if pd.notna(dollar_volume) and dollar_volume < 1_000_000:
            penalty += 7
            flags.append("low dollar volume")
    if market_cap is not None and market_cap < 300_000_000:
        penalty += 5
        flags.append("small market cap")
    return min(float(config["max_risk_penalty"]), penalty), flags


def combine(strategies: Mapping[str, Mapping[str, Any]], penalty: float,
            weights: Mapping[str, float] = DEFAULT_WEIGHTS,
            config: Mapping[str, Any] = CONFIG) -> dict[str, Any]:
    # Group caps remain fixed; missing groups do not transfer their full weight.
    effective = {}
    for group, members in GROUPS.items():
        inner_total = sum(max(0, float(weights.get(s, 0))) for s in members)
        for sid in members:
            effective[sid] = (max(0, float(weights.get(group, 0))) *
                              max(0, float(weights.get(sid, 0))) / inner_total) if inner_total else 0
    total_weight = sum(effective.values())
    if total_weight <= 0:
        raise ValueError("BUY strategy weights must contain a positive value")
    available = {sid: effective[sid] for sid in effective
                 if strategies[sid]["score"] is not None and strategies[sid]["status"] in ("ACTIVE", "INACTIVE")}
    coverage = sum(available.values()) / total_weight
    group_coverage = {group: (sum(available.get(sid, 0) for sid in members) /
                              max(sum(effective[sid] for sid in members), 1e-9))
                      for group, members in GROUPS.items()}
    enough = (coverage >= float(config["min_coverage"]) and
              group_coverage["momentum"] > 0 and group_coverage["fundamental"] > 0)
    if not enough:
        return {"buy_score": None, "buy_alpha": None, "risk_penalty": penalty,
                "data_coverage": round(coverage, 3), "group_coverage": group_coverage,
                "confidence": round(coverage, 3), "status": "INSUFFICIENT_DATA"}
    weighted = sum(effective[sid] * float(strategies[sid]["score"]) for sid in available)
    # Limited renormalization: at most 1 / minimum coverage.
    alpha = weighted / max(sum(available.values()), float(config["min_coverage"]) * total_weight)
    score = _clamp(alpha - penalty)
    status = "BUY_CANDIDATE" if score >= 70 else "WATCHLIST" if score >= 50 else "NO_TRADE"
    if status == "BUY_CANDIDATE" and not any(
        item["status"] == "ACTIVE" for item in strategies.values()
    ):
        status = "WATCHLIST"
    if penalty >= 20:
        status = "HIGH_RISK"
    return {"buy_score": score, "buy_alpha": round(alpha, 2), "risk_penalty": penalty,
            "data_coverage": round(coverage, 3), "group_coverage": group_coverage,
            "confidence": round(coverage, 3), "status": status,
            "provisional": coverage < 0.999}


def model_position(entry: float | None, stop: float | None, account_equity: float | None,
                   config: Mapping[str, Any] = CONFIG) -> dict[str, Any]:
    result = {"entry": entry, "stop": stop, "shares": None}
    if entry is None or stop is None or entry <= stop or stop < 0:
        return result
    result["stop_distance"] = entry - stop
    if account_equity is not None and account_equity > 0:
        by_risk = floor(account_equity * float(config["risk_per_trade"]) / (entry - stop))
        by_cap = floor(account_equity * float(config["max_position_pct"]) / entry)
        result["shares"] = max(0, min(by_risk, by_cap))
    return result
