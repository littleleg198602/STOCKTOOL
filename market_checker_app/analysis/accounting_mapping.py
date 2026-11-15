"""Explicit accounting bases; no missing component is inferred as zero."""
from __future__ import annotations
from math import isclose

from market_checker_app.analysis.financial_statements import number


def resolve_accounting(values):
    result = dict(values)
    sources, notes = {}, []
    plain = [number(values.get(k)) for k in ("debt_current", "debt_long", "short_borrowings")]
    lease = [number(values.get(k)) for k in ("debt_lease_current", "debt_lease_noncurrent")]
    aggregate = number(values.get("debt_lease_total"))
    short = number(values.get("short_borrowings"))
    conflict = (aggregate is not None and all(v is not None for v in lease)
                and not isclose(aggregate, sum(lease), rel_tol=1e-6, abs_tol=1.0))
    lease_long = lease[1]
    if aggregate is None and all(v is not None for v in lease):
        aggregate = sum(lease)
    elif aggregate is not None and lease_long is None and lease[0] is not None:
        remainder = aggregate - lease[0]
        if remainder >= 0:
            lease_long = remainder
        else:
            conflict = True
    if (aggregate is not None and all(v is not None for v in plain[:2])
            and aggregate + max(1.0, abs(aggregate)*1e-6) < sum(plain[:2])):
        conflict = True

    result["debt_basis"] = "unavailable"
    result["effective_debt_long"] = None
    result["debt_includes_leases"] = None
    if number(values.get("debt")) is not None:
        # Existing vendor total is not added to its own components.
        result["debt_basis"] = "vendor_reported_total"
        result["effective_debt_long"] = number(values.get("debt_long"))
        sources["debt"] = {"method": "reported_vendor_total", "fields": ["debt"]}
    elif conflict:
        result["debt"] = None
        notes.append("CONFLICTING_DEBT_COMPONENTS")
        sources["debt"] = {"status": "CONFLICTING_DEBT_COMPONENTS"}
    elif aggregate is not None and short is not None:
        result["debt"] = aggregate + short
        result["debt_basis"] = "including_finance_capital_leases"
        result["debt_includes_leases"] = 1.0
        result["effective_debt_long"] = lease_long
        fields = (["debt_lease_total"] if number(values.get("debt_lease_total")) is not None
                  else ["debt_lease_current", "debt_lease_noncurrent"])
        sources["debt"] = {"method": "long_debt_and_leases_plus_short_borrowings",
                           "fields": fields + ["short_borrowings"]}
    elif all(v is not None for v in plain):
        result["debt"] = sum(plain)
        result["debt_basis"] = "excluding_finance_capital_leases"
        result["debt_includes_leases"] = 0.0
        result["effective_debt_long"] = plain[1]
        sources["debt"] = {"method": "current_plus_noncurrent_plus_short",
                           "fields": ["debt_current", "debt_long", "short_borrowings"]}
    else:
        result["debt"] = None
        notes.append("INCOMPLETE_DEBT_COMPONENTS")
        sources["debt"] = {"status": "INCOMPLETE_DEBT_COMPONENTS"}
        if short is None and number(values.get("commercial_paper")) is not None:
            notes.append("COMMERCIAL_PAPER_IS_NOT_TOTAL_SHORT_BORROWINGS")

    # SEC normalization keeps these flows within the same accession, period and unit.
    # Consolidated profit includes noncontrolling interests; never alias it to parent profit.
    consolidated = number(values.get("consolidated_net_income"))
    noncontrolling = number(values.get("noncontrolling_net_income"))
    if number(values.get("net_income")) is None and consolidated is not None:
        if noncontrolling is not None:
            result["net_income"] = consolidated - noncontrolling
            sources["net_income"] = {"method": "consolidated_minus_noncontrolling",
                                     "fields": ["consolidated_net_income", "noncontrolling_net_income"]}
        else:
            notes.append("CONSOLIDATED_PROFIT_REQUIRES_NONCONTROLLING_COMPONENT")
    if number(values.get("capex")) is None and number(values.get("productive_asset_purchases")) is not None:
        notes.append("PRODUCTIVE_ASSET_PURCHASES_BROADER_THAN_PPE_CAPEX")
    if number(values.get("interest_expense")) is None and number(values.get("interest_and_debt_expense")) is not None:
        notes.append("INTEREST_AND_DEBT_EXPENSE_REQUIRES_BASIS_REVIEW")

    revenue, gross = number(values.get("revenue")), number(values.get("gross_profit"))
    if number(values.get("cogs")) is None and revenue is not None and gross is not None and revenue >= gross:
        result["cogs"] = revenue - gross
        sources["cogs"] = {"method": "revenue_minus_gross_profit",
                           "fields": ["revenue", "gross_profit"]}
    result["interest_basis"] = "reported_interest_expense" if number(values.get("interest_expense")) is not None else "unavailable"
    if result["interest_basis"] == "unavailable" and number(values.get("interest_expense_debt")) is not None:
        notes.append("DEBT_ONLY_INTEREST_NOT_SUBSTITUTED_FOR_TOTAL")
    if number(values.get("interest_expense")) == 0:
        notes.append("ZERO_INTEREST_EXPENSE_NO_INFINITE_COVERAGE")
    result["accounting_sources"] = sources
    result["accounting_notes"] = notes
    return result


def coverage_details(report, resolved):
    from market_checker_app.analysis.financial_statements import TAGS, AVERAGE_FIELDS, SHARE_FIELDS
    rows = []
    keys = list(dict.fromkeys([*TAGS, "debt", "net_debt", "free_cash_flow", "ebitda"]))
    formulas = {
        "net_debt": ["debt", "cash"], "free_cash_flow": ["operating_cash_flow", "capex"],
        "ebitda": ["operating_income", "depreciation"],
    }
    for key in keys:
        evidence = report.get("evidence", {}).get(key, {})
        derivation = resolved.get("accounting_sources", {}).get(key, {})
        value = number(resolved.get(key))
        status = evidence.get("status") or derivation.get("status")
        if value is not None:
            status = "DERIVED" if derivation or key in formulas else "AVAILABLE"
        elif not status:
            status = "NOT_AGGREGATED" if key in AVERAGE_FIELDS and report.get("period") == "TTM" else "MISSING"
        rows.append({
            "field": key, "value": value, "status": status,
            "concept": evidence.get("concept"),
            "method": derivation.get("method") or evidence.get("method"),
            "required_fields": derivation.get("fields") or formulas.get(key, []),
            "other_observation_dates": evidence.get("observed_dates", []),
            "unit": evidence.get("unit") or ("shares" if key in SHARE_FIELDS else report.get("currency")),
            "period_end": report.get("period_end"),
        })
    return rows
