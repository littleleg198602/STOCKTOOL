"""Additional dated metrics on the existing FY/TTM basis; no new data source."""
from market_checker_app.analysis.financial_statements import number, ratio


def extended_metrics(values, previous, current, prior):
    result, audit = {}, {}
    sources = [r for r in (current, prior) if r]
    def save(name, value, formula, reason="MISSING_COMPARABLE_INPUT", comparative=False):
        value = number(value)
        result[name] = value
        audit[name] = {"value": value, "formula": formula,
                       "status": "AVAILABLE" if value is not None else reason,
                       "basis": current.get("period", "FY"),
                       "sources": [{k: r.get(k) for k in
                           ("accession", "snapshot_id", "url", "period_start", "period_end", "available_at")}
                           for r in (sources if comparative else [current])]}
    def subtract(a, b):
        return a-b if a is not None and b is not None else None
    def divide(a, b):
        return ratio(a, b) if b is not None and b > 0 else None
    for metric, key in (("net_income_growth", "net_income"), ("ocf_growth", "operating_cash_flow")):
        growth = divide(values.get(key), previous.get(key))
        save(metric, growth-1 if growth is not None else None,
             key+" / prior_year_"+key+" - 1", "MISSING_OR_NONPOSITIVE_PRIOR_BASE", True)
    save("ocf_margin", divide(values.get("operating_cash_flow"), values.get("revenue")), "operating_cash_flow / revenue")
    save("net_debt_assets", divide(values.get("net_debt"), values.get("assets")), "net_debt / assets")
    save("cash_ratio", divide(values.get("cash"), values.get("current_liabilities")), "cash / current_liabilities")
    working = subtract(values.get("current_assets"), values.get("current_liabilities"))
    save("working_capital_assets", divide(working, values.get("assets")), "(current_assets - current_liabilities) / assets")
    for name, field in (("gross_margin_change", "gross_profit"), ("operating_margin_change", "operating_income")):
        now = values.get("gross_margin") if field == "gross_profit" else divide(values.get(field), values.get("revenue"))
        old = previous.get("gross_margin") if field == "gross_profit" else divide(previous.get(field), previous.get("revenue"))
        save(name, subtract(now, old), "current_margin - prior_year_margin", comparative=True)
    # Weighted counts cannot be summed or differenced into TTM. This preserves
    # the existing annual-only availability; never invent split adjustments.
    same_filing = bool(prior and current.get("accession") and
                       current["accession"] == prior.get("accession"))
    diluted, basic = values.get("weighted_diluted_shares"), values.get("weighted_basic_shares")
    growth = divide(diluted, previous.get("weighted_diluted_shares")) if same_filing else None
    save("weighted_diluted_share_growth", growth-1 if growth is not None else None,
         "weighted_diluted_shares / comparable_prior_year - 1", "SAME_FILING_SHARE_COMPARISON_REQUIRED", True)
    gap = divide(diluted, basic) if diluted is not None and basic is not None and diluted >= basic else None
    save("dilution_gap", gap-1 if gap is not None else None,
         "weighted_diluted_shares / weighted_basic_shares - 1", "MISSING_OR_INCOMPARABLE_SHARE_COUNTS")
    return result, audit
