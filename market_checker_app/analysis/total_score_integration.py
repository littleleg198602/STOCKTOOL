"""Versioned evidence integration for the existing bull/bear decision engine.

Policy weights are explicit engineering defaults, not empirically optimized claims.
No downloads, training or orders occur here.
"""
from __future__ import annotations

from dataclasses import replace
from math import isfinite

from market_checker_app.models import ModuleAxisResult

VERSION = "v2.5_uceni_score_audit"
MOMENTUM_SHARE = 0.35  # within existing technical module
EARNINGS_SHARE = 0.25  # within existing news module
FUNDAMENTAL_SHARE = 0.25  # maximum share of total deterministic evidence
LEARNING_SHARE = 0.05  # maximum replacement share of total bull/bear evidence


def usable_price_history(frame, source, as_of):
    import pandas as pd
    if (frame is None or frame.empty or not source.startswith("yfinance")
            or not {"Close", "Adj Close"}.issubset(frame.columns)):
        return False
    dates = pd.to_datetime(frame.index, errors="coerce", utc=True)
    if dates.isna().any() or dates.has_duplicates:
        return False
    latest = dates.max().date()
    if not 0 <= (as_of.date() - latest).days <= 7:
        return False
    prices = frame[["Close", "Adj Close"]].apply(pd.to_numeric, errors="coerce")
    return bool(prices.apply(lambda column: column.map(lambda value: _number(value) is not None and value > 0)).all().all())


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if isfinite(value) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _group(strategies, weights):
    observed = {}
    for sid, weight in weights.items():
        item = strategies.get(sid, {})
        score = _number(item.get("score"))
        if item.get("status") in {"ACTIVE", "INACTIVE"} and score is not None and 0 <= score <= 100:
            observed[sid] = (score, weight)
    coverage = sum(w for _, w in observed.values()) / sum(weights.values())
    score = sum(v * w for v, w in observed.values()) / sum(w for _, w in observed.values()) if observed else None
    return score, coverage, {sid: value[0] for sid, value in observed.items()}


def _blend(module, score, share, explanation, confidence):
    bull = (1-share) * module.bull_contribution + share * score
    bear = (1-share) * module.bear_contribution + share * (100-score)
    spread = bull - bear
    return replace(module, bull_contribution=round(bull, 4), bear_contribution=round(bear, 4),
                   direction="bullish" if spread >= 12 else "bearish" if spread <= -12 else "neutral",
                   confidence=(1-share) * module.confidence + share * confidence,
                   explanation=module.explanation + " " + explanation)


def integrate_evidence(modules, weights, buy_payload, prediction, analyst_only=None):
    result = list(modules)
    by_name = {m.module: i for i, m in enumerate(result)}
    effective = dict(weights)
    audit = {"version": VERSION, "momentum": {"status": "DATA_MISSING"},
             "fundamentals": {"status": "DATA_MISSING"}, "earnings": {"status": "DATA_MISSING"},
             "learning": {"status": (prediction or {}).get("status", "MODEL_UNAVAILABLE"), "weight": 0.0},
             "module_weights": effective}
    payload = buy_payload or {}
    strategies = payload.get("strategies", {})
    statement = payload.get("financial_statements", {})
    audit["sec_events"] = statement.get("sec_events", {"status": "NOT_CHECKED", "scoring_applied": False})
    audit["extended_metric_usage"] = {
        name: ("SHAREHOLDER_COST_ADJUSTMENT_WHEN_FUNDAMENTALS_APPLY" if name == "dilution_gap"
               else "LEARNING_INPUT_AND_DIAGNOSTIC_NO_EXTRA_VOTE")
        for name in statement.get("extended_metric_details", {})}
    audit["statement_data"] = {
        "basis": statement.get("basis"), "accounting_basis": statement.get("accounting_basis", {}),
        "field_coverage": statement.get("field_coverage", []),
        "core_metric_coverage": statement.get("coverage"),
        "extended_metric_details": statement.get("extended_metric_details", {}),
    }
    for group, proportions, slot, maximum in (
        ("momentum", {"B01": .65, "B02": .35}, "technical", MOMENTUM_SHARE),
        ("earnings", {"B05": 1.0}, "news", EARNINGS_SHARE),
    ):
        score, coverage, used = _group(strategies, proportions)
        if score is not None:
            share = maximum * coverage
            index = by_name[slot]
            result[index] = _blend(result[index], score, share,
                                   f"{group}: score={score:.2f}, replacement_share={share:.3f}.", coverage)
            audit[group] = {"status": "APPLIED", "score": score, "coverage": coverage,
                            "share_in_module": share, "strategies": used}
    score, coverage, used = _group(strategies, {"B03": .35, "B04": .35, "B06": .30})
    if score is not None and statement.get("status") in {"OK", "PARTIAL"}:
        # B03/B04/B06 already use growth, margins, debt and F-score signals.
        # Only additional shareholder costs enter here, once, with a fixed cap.
        costs = {}
        for name, maximum, budget in (("stock_compensation_revenue", .20, .5), ("dilution_gap", .10, .5)):
            value = _number(statement.get("metrics", {}).get(name))
            if value is not None and value >= 0:
                costs[name] = min(1.0, value/maximum) * budget * 3.0
        original_score = score
        score = max(0.0, score-sum(costs.values()))
        audit["shareholder_costs"] = {"status": "APPLIED" if costs else "DATA_MISSING",
                                     "penalty_in_fundamental_score": sum(costs.values()),
                                     "components": costs, "maximum_penalty": 3.0,
                                     "fundamental_score_before": original_score}
        share = FUNDAMENTAL_SHARE * coverage
        # When real statements contribute, use only analyst opinions/targets in
        # the Yahoo slot, replacing its overlapping fundamental/valuation mix.
        if analyst_only is not None:
            result[by_name["analysts"]] = analyst_only
        effective = {name: weight * (1-share) for name, weight in effective.items()}
        effective["fundamentals"] = share
        result.append(ModuleAxisResult(
            module="fundamentals", direction="bullish" if score >= 56 else "bearish" if score <= 44 else "neutral",
            bull_contribution=score, bear_contribution=100-score,
            confidence=min(coverage, max(0.0, min(1.0, _number(statement.get("coverage")) or 0.0))),
            explanation=f"Dated statements ({statement.get('provider', '')}); B03/B04/B06={used}; coverage={coverage:.3f}.",
        ))
        audit["fundamentals"] = {
            "status": "APPLIED", "score": score, "coverage": coverage, "weight": share, "strategies": used,
            "provider": statement.get("provider"), "period_end": statement.get("period_end"),
            "basis": statement.get("basis", "FY"), "quarterly_status": statement.get("quarterly_status"),
            "strategy_periods": {sid: strategies[sid].get("statement_basis") for sid in used},
            "available_at": statement.get("available_at"),
            "snapshot_ids": [r.get("snapshot_id") for r in statement.get("reports", [])],
            "yahoo_fundamentals_replaced": analyst_only is not None,
        }
    else:
        audit["fundamentals"]["statement_status"] = statement.get("status", "DATA_MISSING")
    probability = _number((prediction or {}).get("probability"))
    if (prediction and prediction.get("status") == "READY" and prediction.get("main_eligible") is True
            and prediction.get("target") == "absolute_return"
            and probability is not None and 0 <= probability <= 1):
        audit["learning"] = {
            "status": "APPLIED", "weight": LEARNING_SHARE, "probability": probability,
            "model_id": prediction.get("model_id"), "target": prediction.get("target"),
            "horizon_sessions": prediction.get("horizon_sessions"),
            "validation": prediction.get("validation"),
        }
    audit["module_weights"] = effective
    # Price risks overlap existing ATR/volatility risk. Use the larger risk, never add both penalties.
    penalty = _number(payload.get("summary", {}).get("risk_penalty"))
    audit["buy_risk_floor"] = penalty / 30 * 100 if penalty is not None and 0 <= penalty <= 30 else None
    audit["buy_risk_flags"] = list(payload.get("risk_flags", []))
    return result, effective, audit


def load_validated_model(db_path, config):
    """Only persisted accepted models with matching three-period validation are eligible."""
    from market_checker_app.analysis.buy_learning import load_model, load_learning_report, config_key
    if config.target != "absolute_return":
        return None, "TARGET_NOT_DIRECTIONAL", {}
    model = load_model(db_path, config)
    if model is None:
        return None, "MODEL_UNAVAILABLE", {}
    report = load_learning_report(db_path, config, model_id=model.model_id) or {}
    folds = report.get("folds", [])
    valid = (
        report.get("status") == "READY" and report.get("model_id") == model.model_id
        and report.get("config_key") == config_key(config)
        and report.get("dataset_fingerprint") == model.dataset_fingerprint
        and isinstance(folds, list) and len(folds) == 3
        and all(isinstance(f, dict) and f.get("status") == "EVALUATED" for f in folds)
        and (_number(report.get("validation_blocks")) or 0) >= config.min_validation_blocks
    )
    if valid:
        for improvement, reference_loss in (
            ("relative_brier_improvement", "baseline_log_loss"),
            *((("statement_brier_improvement", "without_statements_log_loss"),) if config.include_statements else ()),
        ):
            improvements = [_number(f.get(improvement)) for f in folds]
            final_loss, base_loss = _number(folds[-1].get("log_loss")), _number(folds[-1].get(reference_loss))
            valid = (all(v is not None for v in improvements)
                     and sum(v >= config.min_brier_improvement for v in improvements) >= 2
                     and improvements[-1] >= config.min_brier_improvement
                     and final_loss is not None and base_loss is not None and final_loss <= base_loss)
            if not valid:
                break
    if not valid:
        return None, "MODEL_VALIDATION_MISSING", {}
    return model, "READY", {
        "holdout_brier": report.get("holdout_brier"), "baseline_brier": report.get("baseline_brier"),
        "without_statements_brier": report.get("without_statements_brier"),
        "evaluated_through": model.evaluated_through,
    }
