"""Versioned research screen, separate from production score and trade actions.

Uses dated statements and adjusted daily prices already collected by the pipeline.
No network, model fitting, orders or retrospective edits. Missing evidence stays missing.
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

from market_checker_app.analysis.buy_analysis import _price_frame, _atr, _percentile
from market_checker_app.analysis.financial_statements import number, timestamp

VERSION = "quality_drawdown_v3_attractiveness"
WEIGHTS = {"health": .30, "valuation": .30, "business": .25, "cause": .15}
ITEM_WEIGHTS = {
    "health": {"ocf_assets": .30, "debt_assets": .30, "interest_coverage": .25, "current_ratio": .15},
    "valuation": {"fcf_ev": .60, "ebit_ev": .40},
    "business": {"revenue_growth": .35, "ocf_growth": .40, "operating_margin_change": .25},
    "cause": {"cause_assessment": 1.0},
}


def _scale(value, low, high):
    return None if value is None else round(max(0., min(100., (value-low)/(high-low)*100)), 2)


def _group(items, name):
    weights = ITEM_WEIGHTS[name]
    coverage = sum(weights[k] for k in weights if items.get(k) is not None)
    contribution = sum(weights[k] * (items[k]-50) for k in weights if items.get(k) is not None)
    return {"score": (50+contribution/coverage) if coverage > 0 else None,
            "coverage_adjusted_score": 50+contribution if coverage > 0 else None,
            "coverage": coverage, "items": items, "item_weights": dict(weights),
            "effective_weight": WEIGHTS[name]*coverage,
            "missing_weight": WEIGHTS[name]*(1-coverage),
            "weighted_contribution": WEIGHTS[name]*contribution,
            "item_audit": {k: {"score": items.get(k), "weight_in_group": weights[k],
                "maximum_weight": WEIGHTS[name]*weights[k],
                "effective_weight": WEIGHTS[name]*weights[k] if items.get(k) is not None else 0.,
                "score_contribution": WEIGHTS[name]*weights[k]*(items[k]-50) if items.get(k) is not None else 0.,
                "status": "AVAILABLE" if items.get(k) is not None else "MISSING"} for k in weights}}


def evaluate_quality_drawdown(frame, source, statement, fundamentals, peers, as_of):
    result = {"version": VERSION, "as_of": as_of.isoformat(), "status": "INSUFFICIENT_DATA",
              "score": None, "attractiveness_score": None, "coverage_adjusted_score": None, "coverage": 0., "provisional": True, "weights": dict(WEIGHTS),
              "timing": "UNKNOWN", "reasons": [], "risk_flags": [], "components": {},
              "price_status": "UNVERIFIED", "drawdown_pct": None, "returns": {},
              "cause_status": "UNASSESSED", "affects_total_score": False,
              "statement_provider": statement.get("provider"),
              "statement_available_at": statement.get("available_at"),
              "statement_period_end": statement.get("period_end"),
              "statement_reports": statement.get("reports", []), "critical_missing": []}
    reasons, flags = result["reasons"], result["risk_flags"]

    # Require explicit adjusted observations; never combine MT5 and Yahoo endpoints.
    prices = None
    if (str(source).startswith("yfinance") and isinstance(frame, pd.DataFrame)
            and not frame.empty and {"Close", "Adj Close"}.issubset(frame.columns)):
        try:
            dates = pd.to_datetime(frame.index, utc=True, errors="coerce")
            numeric = frame[["Close", "Adj Close"]].apply(pd.to_numeric, errors="coerce")
            if (not dates.isna().any() and not dates.normalize().duplicated().any()
                    and (dates.max().date() <= as_of.date())
                    and (as_of.date()-dates.max().date()).days <= 7
                    and numeric.notna().all().all() and numeric.gt(0).all().all()
                    and numeric.lt(float("inf")).all().all()):
                dated = frame.copy()
                dated.index = dates
                prices = _price_frame(dated, source)
        except (ValueError, TypeError, OverflowError):
            prices = None
    if prices is not None and len(prices) >= 252:
        close = prices["Close"]
        latest = float(close.iloc[-1])
        result.update(price_status="ADJUSTED_SERIES", price_source=source,
                      price_as_of=prices.index[-1].isoformat(), price=latest,
                      drawdown_pct=round(100*(latest/float(close.tail(252).max())-1), 2))
        result["returns"] = {str(n): round(100*(latest/float(close.iloc[-n-1])-1), 4)
                             for n in (5, 10, 21, 63)}
        if close.tail(253).pct_change(fill_method=None).abs().gt(.35).any():
            result["price_status"] = "REVIEW_PRICE_JUMP"
            reasons.append("Adjusted series contains a daily move over 35%; verify corporate actions and ticker mapping.")
        ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
        atr = number(_atr(prices))
        result["timing_evidence"] = {"ema20": ema20, "atr_ratio": atr/latest if atr is not None else None,
                                     "five_session_return_pct": result["returns"]["5"]}
        if atr is not None and atr/latest > .05:
            result["timing"] = "HIGH_VOLATILITY"
        elif latest > ema20 and result["returns"]["5"] > 0:
            result["timing"] = "STABILIZING"
        else:
            result["timing"] = "WAITING_FOR_STABILIZATION"
    else:
        reasons.append("Need at least 252 fresh, positive, split/dividend-adjusted daily prices.")

    # SEC monitoring is evidence for review, not proof that the cause is harmless.
    monitor = statement.get("sec_events", {})
    result["sec_monitor_status"] = monitor.get("status", "NOT_CHECKED")
    result["sec_events"] = monitor.get("events", [])
    for event in result["sec_events"]:
        if any(item in {"1.03", "2.04", "4.02"} for item in event.get("items", [])):
            flags.append("MATERIAL_SEC_EVENT_REQUIRES_REVIEW")
    reasons.append("Cause of drawdown is not yet assessed; an empty SEC event list does not confirm safety.")

    available = timestamp(statement.get("available_at"))
    if (statement.get("status") not in {"OK", "PARTIAL"} or available is None or available > as_of):
        if statement.get("status") == "SECTOR_NOT_SUPPORTED":
            result["status"] = "NOT_APPLICABLE"
        reasons.append("Eligible dated statements unavailable: " + str(statement.get("status", "DATA_MISSING")))
        return result
    period = timestamp(statement.get("period_end"))
    max_age = 180 if statement.get("basis") == "TTM" else 550
    if period is None or not timedelta(0) <= as_of-period <= timedelta(days=max_age):
        reasons.append("Statement period is stale or in the future.")
        return result
    m = {k: number(v) for k, v in statement.get("metrics", {}).items()}
    result["input_metrics"] = m
    result["market_cap"] = number(fundamentals.get("market_cap"))
    result["currency"] = fundamentals.get("currency")
    health = _group({"ocf_assets": _scale(m.get("ocf_assets"), 0, .15),
                     "debt_assets": _scale(m.get("debt_assets"), .8, .1),
                     "current_ratio": _scale(m.get("current_ratio"), .5, 2),
                     "interest_coverage": _scale(m.get("interest_coverage"), 1, 8)}, "health")
    business = _group({"revenue_growth": _scale(m.get("revenue_growth"), -.15, .15),
                       "ocf_growth": _scale(m.get("ocf_growth"), -.25, .25),
                       "operating_margin_change": _scale(m.get("operating_margin_change"), -.05, .05)}, "business")

    # Reuse same-sector, currency and period inputs, but not B04's blended quality
    # score or EMA200 gate. Valuation freshness is checked for every peer.
    def yields(record):
        observed = timestamp(record.get("valuation_observed_at"))
        ev = number(record.get("enterprise_value"))
        if (observed is None or not timedelta(0) <= as_of-observed <= timedelta(days=7)
                or ev is None or ev <= 0):
            return {}
        return {key: number(record.get(field))/ev if number(record.get(field)) is not None else None
                for key, field in (("fcf_ev", "free_cash_flow"), ("ebit_ev", "ebit"))}
    own = yields(fundamentals)
    matched = [p for p in peers if all(p.get(k) == fundamentals.get(k)
               for k in ("sector", "currency", "period_basis"))]
    peer_yields = [yields(p) for p in matched]
    valuation = _group({key: _percentile(own[key], [p[key] for p in peer_yields if p.get(key) is not None], 5)
                        if own.get(key) is not None else None for key in ("fcf_ev", "ebit_ev")}, "valuation")
    result["valuation_evidence"] = {"yields": own, "peer_counts": {
        key: sum(p.get(key) is not None for p in peer_yields) for key in ("fcf_ev", "ebit_ev")},
        "observed_at": fundamentals.get("valuation_observed_at"),
        "method": "same-sector FCF/EV and EBIT/EV percentiles; not intrinsic fair value"}
    components = {"health": health, "valuation": valuation, "business": business,
                  "cause": _group({"cause_assessment": None}, "cause")}
    result["components"] = components
    result["missing_inputs"] = {key: [name for name, value in component["items"].items() if value is None]
                                for key, component in components.items()}
    coverage = sum(WEIGHTS[k]*v["coverage"] for k, v in components.items())
    result["coverage"] = round(coverage, 4)
    result["missing_weight"] = round(1-coverage, 4)
    # Financial attractiveness has fixed pillar proportions (30:30:25).
    # Cause is a separate, currently unassessed risk review, never an invented score.
    financial_groups = ("health", "valuation", "business")
    financial_weight = sum(WEIGHTS[k] for k in financial_groups)
    result["financial_coverage"] = round(coverage/financial_weight, 4)
    result["score_formula"] = "sum(fixed financial pillar weight * observed within-pillar average)"
    result["attractiveness_weights"] = {k: WEIGHTS[k]/financial_weight for k in financial_groups}
    if coverage > 0:
        result["coverage_adjusted_score"] = round(50+sum(v["weighted_contribution"] for v in components.values()), 2)
    # Enough independent evidence in every pillar; never let an absent pillar
    # transfer its weight to a different one. Minimums are pilot safeguards.
    sufficient = (coverage >= .50 and health["coverage"] >= .40
                  and valuation["coverage"] >= .40 and business["coverage"] >= .50
                  and sum(v is not None for v in health["items"].values()) >= 2
                  and sum(v is not None for v in business["items"].values()) >= 2)
    result["attractiveness_eligible"] = sufficient
    for key, component in components.items():
        for audit in component["item_audit"].values():
            normalized = (audit["weight_in_group"]/component["coverage"]
                          if audit["score"] is not None and component["coverage"] > 0 else 0.)
            audit["normalized_weight_in_group"] = normalized
            audit["attractiveness_weight"] = (WEIGHTS[key]/financial_weight*normalized
                                               if sufficient and key in financial_groups else None)
            audit["attractiveness_contribution"] = (audit["attractiveness_weight"]*audit["score"]
                if audit["attractiveness_weight"] is not None and audit["score"] is not None else None)
    if sufficient:
        result["attractiveness_score"] = round(sum(WEIGHTS[k]/financial_weight*components[k]["score"]
                                                   for k in financial_groups), 2)
        result["score"] = result["attractiveness_score"]
    else:
        reasons.append("Financial attractiveness withheld: require all three pillars, at least two health/business indicators, and 50% total weighted coverage. Partial pillar scores remain visible.")
    result["critical_missing"] = [k for k in ("debt_assets", "interest_coverage", "ocf_assets", "fcf_margin", "roa")
                                  if m.get(k) is None]
    if result["critical_missing"]:
        reasons.append("Critical unknowns remain; partial score is not confirmation of financial safety: "
                       + ", ".join(result["critical_missing"]))
    for key in ("ocf_assets", "fcf_margin", "roa"):
        if m.get(key) is None:
            reasons.append("Required health gate missing: " + key)
        elif m[key] <= 0:
            flags.append("NONPOSITIVE_" + key.upper())
    if m.get("current_ratio") is not None and m["current_ratio"] < 1:
        flags.append("CURRENT_RATIO_BELOW_ONE")
    if m.get("interest_coverage") is not None and m["interest_coverage"] < 1:
        flags.append("INTEREST_NOT_COVERED")
    if flags:
        result["status"] = "RISK_REVIEW"
    elif coverage <= 0:
        result["status"] = "INSUFFICIENT_DATA"
    elif result["price_status"] != "ADJUSTED_SERIES":
        result["status"] = "PRICE_REVIEW"
    elif result["drawdown_pct"] > -15:
        result["status"] = "OUTSIDE_DRAWDOWN"
    elif (sufficient and result["attractiveness_score"] >= 70
          and health["score"] >= 60 and valuation["score"] >= 60):
        result["status"] = "PARTIAL_CANDIDATE" if result["critical_missing"] or coverage < .849999 else "CANDIDATE_REVIEW"
    elif not sufficient or result["critical_missing"] or coverage < .849999:
        result["status"] = "PARTIAL_DATA"
    else:
        result["status"] = "WATCHLIST"
    return result
