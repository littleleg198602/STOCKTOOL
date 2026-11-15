"""Dated annual and quarterly statements. Missing fields stay None; currencies are never converted implicitly."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import math
from typing import Any

SCHEMA = "financial_statements_v5_sec_mapping"
EVENTS_SCHEMA = "financial_statements_v4_events_metrics"
MAPPING_SCHEMA = "financial_statements_v3_mapping"
PERIODS_SCHEMA = "financial_statements_v2_periods"
LEGACY_SCHEMA = "financial_statements_v1"
BUY_SCORING_VERSION = "buy_v1.5_sec_mapping"
METRICS = (
    "revenue_growth", "gross_margin", "operating_margin", "roa", "ocf_assets",
    "accruals_assets", "fcf_margin", "debt_assets", "current_ratio", "interest_coverage",
    "stock_compensation_revenue", "annual_share_growth",
    'net_income_growth', 'ocf_growth', 'ocf_margin', 'net_debt_assets', 'cash_ratio', 'working_capital_assets', 'gross_margin_change', 'operating_margin_change', 'weighted_diluted_share_growth', 'dilution_gap',
    "debt_includes_leases",
)
CORE_METRICS = METRICS[:10]
FEATURE_NAMES = tuple("fs_" + k for k in METRICS) + tuple("fs_" + k + "_available" for k in METRICS)
# Standard US-GAAP concepts only. Custom issuer tags need a reviewed mapping.
TAGS = {
    "revenue": ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"),
    "cogs": ("CostOfRevenue", "CostOfGoodsAndServicesSold"),
    "net_income": ("NetIncomeLoss",),
    "consolidated_net_income": ("ProfitLoss",),
    "noncontrolling_net_income": ("NetIncomeLossAttributableToNoncontrollingInterest",),
    "operating_income": ("OperatingIncomeLoss",),
    "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
    "capex": ("PaymentsToAcquirePropertyPlantAndEquipment",),
    "depreciation": ("DepreciationDepletionAndAmortization", "DepreciationDepletionAndAmortizationPropertyPlantAndEquipment"),
    "assets": ("Assets",),
    "book_equity": ("StockholdersEquity",),
    "current_assets": ("AssetsCurrent",),
    "current_liabilities": ("LiabilitiesCurrent",),
    "cash": ("CashAndCashEquivalentsAtCarryingValue",),
    "debt_current": ("LongTermDebtCurrent",),
    "debt_long": ("LongTermDebtNoncurrent",),
    "short_borrowings": ("ShortTermBorrowings",),
    "shares": ("CommonStockSharesOutstanding", "dei:EntityCommonStockSharesOutstanding"),
    "shares_issued": ("CommonStockSharesIssued",),
    "treasury_shares": ("TreasuryStockShares",),
    "weighted_basic_shares": ("WeightedAverageNumberOfSharesOutstandingBasic",),
    "weighted_diluted_shares": ("WeightedAverageNumberOfDilutedSharesOutstanding",),
    "gross_profit": ("GrossProfit",),
    "stock_compensation": ("ShareBasedCompensation",),
    "debt_lease_current": ("LongTermDebtAndCapitalLeaseObligationsCurrent",),
    "debt_lease_noncurrent": ("LongTermDebtAndCapitalLeaseObligations",),
    "debt_lease_total": ("LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",),
    "commercial_paper": ("CommercialPaper",),
    "interest_expense_debt": ("InterestExpenseDebt",),
    "interest_expense": ("InterestExpenseNonoperating", "InterestExpense", "InterestExpenseNonOperating"),
    "interest_and_debt_expense": ("InterestAndDebtExpense",),
    "productive_asset_purchases": ("PaymentsToAcquireProductiveAssets",),
}
INSTANT = {"assets", "book_equity", "current_assets", "current_liabilities", "cash",
           "debt_current", "debt_long", "short_borrowings", "shares",
           "shares_issued", "treasury_shares", "debt_lease_current", "debt_lease_noncurrent",
           "debt_lease_total", "commercial_paper"}
AVERAGE_FIELDS = {"weighted_basic_shares", "weighted_diluted_shares"}
SHARE_FIELDS = {"shares", "shares_issued", "treasury_shares"} | AVERAGE_FIELDS
QUARTERLY_FORMS = {"10-Q", "10-Q/A"}
ANNUAL_FORMS = {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}


def number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def timestamp(value: Any) -> datetime | None:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def day(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def publication(value: Any) -> str | None:
    # Vendor timestamps without a documented timezone are not treated as intraday precision.
    parsed = day(value)
    return datetime.combine(parsed + timedelta(days=1), datetime.min.time(), timezone.utc).isoformat() if parsed else None


def ratio(a, b):
    a, b = number(a), number(b)
    return a / b if a is not None and b is not None and b > 0 else None


def _report(provider, start, end, published, retrieved, currency, values, evidence, accession="", url="", period="FY"):
    pub, got = timestamp(published), timestamp(retrieved)
    end_day = day(end)
    if not pub or not got or not end_day or pub.date() <= end_day or pub > got:
        return None
    if start:
        start_day = day(start)
        limits = {"FY": (300, 380), "Q": (60, 110), "YTD": (150, 299)}
        if period not in limits or start_day is None:
            return None
        low, high = limits[period]
        if not low <= (end_day - start_day).days + 1 <= high:
            return None
    if not currency or not any(number(v) is not None for v in values.values()):
        return None
    clean = {k: number(v) for k, v in values.items()}
    evidence = {k: dict(v) for k, v in evidence.items()}
    for key in ("assets", "current_assets", "current_liabilities", "cash", "shares", "debt",
                "debt_current", "debt_long", "short_borrowings", "capex", "depreciation", "revenue", "cogs",
                "debt_lease_current", "debt_lease_noncurrent", "debt_lease_total", "commercial_paper",
                "shares_issued", "treasury_shares", "weighted_basic_shares", "weighted_diluted_shares",
                "productive_asset_purchases"):
        if clean.get(key) is not None and clean[key] < 0:
            clean[key] = None
            evidence[key] = {**evidence.get(key, {}), "status": "INVALID_NEGATIVE"}
    return {
        "provider": provider, "period": period, "period_start": start, "period_end": end_day.isoformat(),
        "published_at": pub.isoformat(), "retrieved_at": got.isoformat(),
        "available_at": max(pub, got).isoformat(), "currency": currency,
        "accession": str(accession), "url": url, "values": clean, "evidence": evidence,
    }


def normalize_sec(payload: dict, retrieved_at: str) -> list[dict]:
    facts = payload.get("facts", {}).get("us-gaap", {})
    if not isinstance(facts, dict):
        return []
    # Never aggregate across filings, units or duration contexts.
    flows, balances = defaultdict(dict), defaultdict(dict)
    conflicts = set()
    for metric, concepts in TAGS.items():
        for priority, concept in enumerate(concepts):
            unit = "shares" if metric in SHARE_FIELDS else "USD"
            namespace, local = concept.split(":", 1) if ":" in concept else ("us-gaap", concept)
            concepts_by_namespace = payload.get("facts", {}).get(namespace, {})
            for fact in concepts_by_namespace.get(local, {}).get("units", {}).get(unit, []):
                if not isinstance(fact, dict) or fact.get("form") not in ANNUAL_FORMS | QUARTERLY_FORMS:
                    continue
                value, end = number(fact.get("val")), day(fact.get("end"))
                accn, filed = fact.get("accn"), publication(fact.get("filed"))
                if value is None or not end or not accn or not filed:
                    continue
                if metric in INSTANT:
                    if fact.get("start"):
                        continue
                    key = (str(accn), end.isoformat(), filed)
                    target = balances[key]
                else:
                    start = day(fact.get("start"))
                    if not start:
                        continue
                    duration = (end - start).days + 1
                    if not (60 <= duration <= 110 or 150 <= duration <= 380):
                        continue
                    key = (str(accn), start.isoformat(), end.isoformat(), filed)
                    target = flows[key]
                existing = target.get(metric)
                ident = (key, metric)
                if existing and existing[1] == priority and existing[0] != value:
                    conflicts.add(ident)
                if existing is None or priority < existing[1]:
                    target[metric] = (value, priority, concept)
                    conflicts.discard(ident)
    reports = []
    cik = str(payload.get("cik", "")).lstrip("0")
    for key, values in flows.items():
        accn, start, end, filed = key
        balance_key = (accn, end, filed)
        merged = {**values, **balances.get(balance_key, {})}
        data, evidence = {}, {}
        for metric, (value, _, concept) in merged.items():
            unit = "shares" if metric in SHARE_FIELDS else "USD"
            if ((balance_key if metric in INSTANT else key), metric) in conflicts:
                evidence[metric] = {"status": "CONFLICTING_FACTS", "concept": concept, "unit": unit}
                continue
            data[metric] = value
            evidence[metric] = {"concept": concept, "unit": unit}
        if "shares" not in data and "shares" not in evidence:
            dates = sorted({k[1] for k, entries in balances.items()
                            if k[0] == accn and k[1] != end and "shares" in entries})
            if dates:
                evidence["shares"] = {"status": "OTHER_DATE_ONLY", "observed_dates": dates[-8:],
                                      "unit": "shares"}
        url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}/{accn}-index.html"
               if cik.isdigit() else "")
        duration = (day(end) - day(start)).days + 1
        period = "FY" if duration >= 300 else "Q" if duration <= 110 else "YTD"
        report = _report("sec", start, end, filed, retrieved_at, "USD", data, evidence, accn, url, period)
        if report:
            reports.append(report)
    return reports


FMP_FIELDS = {
    "income": {"revenue": "revenue", "cogs": "costOfRevenue", "net_income": "netIncome",
               "operating_income": "operatingIncome", "interest_expense": "interestExpense"},
    "balance": {"assets": "totalAssets", "book_equity": "totalStockholdersEquity",
                "current_assets": "totalCurrentAssets", "current_liabilities": "totalCurrentLiabilities",
                "cash": "cashAndCashEquivalents", "debt": "totalDebt",
                "debt_long": "longTermDebt"},
    "cashflow": {"operating_cash_flow": "operatingCashFlow", "capex": "capitalExpenditure",
                 "depreciation": "depreciationAndAmortization", "stock_compensation": "stockBasedCompensation"},
}


def normalize_fmp(payload: dict, retrieved_at: str) -> list[dict]:
    by_kind = {}
    for kind in FMP_FIELDS:
        records = payload.get(kind, [])
        if not isinstance(records, list):
            return []
        grouped = defaultdict(list)
        for row in records:
            if isinstance(row, dict) and row.get("period") == "FY" and day(row.get("date")):
                grouped[str(row["date"])[:10]].append(row)
        by_kind[kind] = grouped
    reports = []
    for end, income_rows in by_kind["income"].items():
        # Ambiguous duplicates are not silently selected.
        groups = [income_rows, by_kind["balance"].get(end, []), by_kind["cashflow"].get(end, [])]
        if any(len(rows) != 1 for rows in groups):
            continue
        rows = [rows[0] for rows in groups]
        currencies = {r.get("reportedCurrency") for r in rows}
        dates = [publication(r.get("filingDate") or r.get("fillingDate") or r.get("acceptedDate")) for r in rows]
        if len(currencies) != 1 or None in currencies or not all(dates):
            continue
        # Mismatched filings can combine a revised statement with an unrevised one.
        if len(set(dates)) != 1:
            continue
        values, evidence = {}, {}
        for (kind, mapping), row in zip(FMP_FIELDS.items(), rows):
            for metric, field in mapping.items():
                value = number(row.get(field))
                if metric == "capex" and value is not None:
                    value = abs(value)  # FMP capitalExpenditure is an outflow.
                values[metric] = value
                evidence[metric] = {"field": field, "statement": kind}
        # Weighted-average EPS shares are NOT end-of-period outstanding shares.
        report = _report("fmp", None, end, max(dates), retrieved_at, next(iter(currencies)),
                         values, evidence, url="https://site.financialmodelingprep.com/developer/docs/stable/income-statement")
        if report:
            reports.append(report)
    return reports


def normalize_finnhub(payload: dict, retrieved_at: str) -> list[dict]:
    reports = []
    for row in payload.get("data", []):
        if not isinstance(row, dict) or row.get("form") not in ANNUAL_FORMS:
            continue
        items = [item for kind in ("bs", "ic", "cf") for item in row.get("report", {}).get(kind, [])
                 if isinstance(item, dict)]
        values, evidence = {}, {}
        for metric, concepts in TAGS.items():
            unit = "shares" if metric in SHARE_FIELDS else "usd"
            for concept in concepts:
                matches = [item for item in items
                           if str(item.get("concept", "")).replace(":", "_") == "us-gaap_" + concept
                           and str(item.get("unit", "")).lower() == unit]
                nums = {number(item.get("value")) for item in matches}
                nums.discard(None)
                if len(nums) == 1:
                    values[metric] = nums.pop()
                    evidence[metric] = {"concept": concept, "unit": unit}
                    break
        report = _report("finnhub", str(row.get("startDate", ""))[:10], str(row.get("endDate", ""))[:10],
                         publication(row.get("filedDate") or row.get("acceptedDate")),
                         retrieved_at, "USD", values, evidence, row.get("accessNumber", ""),
                         "https://finnhub.io/docs/api/financials-reported")
        if report:
            reports.append(report)
    return reports


def _derived(values):
    from market_checker_app.analysis.accounting_mapping import resolve_accounting
    result = resolve_accounting(values)
    result["net_debt"] = (result["debt"] - result["cash"]
                          if result.get("debt") is not None and result.get("cash") is not None else None)
    result["free_cash_flow"] = (result["operating_cash_flow"] - result["capex"]
                                if result.get("operating_cash_flow") is not None and result.get("capex") is not None else None)
    result["ebit"] = result.get("operating_income")
    result["ebitda"] = (result["ebit"] + result["depreciation"]
                        if result.get("ebit") is not None and result.get("depreciation") is not None else None)
    result["gross_margin"] = (1 - result["cogs"] / result["revenue"]
                              if result.get("revenue", 0) and result["revenue"] > 0 and result.get("cogs") is not None else None)
    result["current_ratio"] = ratio(result.get("current_assets"), result.get("current_liabilities"))
    result["debt_ratio"] = ratio(result.get("effective_debt_long"), result.get("assets"))
    result["asset_turnover"] = ratio(result.get("revenue"), result.get("assets"))
    return result


def _analyze_period_reports(reports: list[dict], as_of: datetime, sector: str = "",
                    market_cap_usd: float | None = None) -> dict:
    as_of = timestamp(as_of)
    if as_of is None:
        raise ValueError("Invalid statement observation time")
    result = {"schema": SCHEMA, "status": "DATA_MISSING", "as_of": as_of.isoformat(),
              "metrics": {}, "fundamental_inputs": {}, "reports": [], "warnings": []}
    valid = []
    for r in reports:
        times = [timestamp(r.get(k)) for k in ("published_at", "retrieved_at", "available_at")]
        if (r.get("period") in {"FY", "TTM"} and day(r.get("period_end"))
                and isinstance(r.get("values"), dict) and isinstance(r.get("evidence"), dict)
                and all(t is not None and t <= as_of for t in times)
                and times[2] >= max(times[0], times[1])):
            valid.append(r)
    if not valid:
        return result
    # A complete pair from a single source; no Frankenstein statement across providers/currencies.
    options = []
    for provider in ("sec", "fmp", "finnhub"):
        for currency in sorted({str(r["currency"]) for r in valid if r["provider"] == provider}):
            latest = {}
            for r in sorted((r for r in valid if r["provider"] == provider and r["currency"] == currency),
                            key=lambda r: (r["published_at"], r["retrieved_at"])):
                latest[r["period_end"]] = r
            ordered = sorted(latest.values(), key=lambda r: r["period_end"], reverse=True)
            if ordered:
                selected = [ordered[0]]
                for _ in range(2):
                    previous = next((r for r in ordered
                                     if 330 <= (day(selected[-1]["period_end"])
                                                - day(r["period_end"])).days <= 400), None)
                    if previous is None:
                        break
                    selected.append(previous)
                options.append(selected)
    if not options:
        return result
    # An old complete provider must not hide a usable refreshed alternative.
    fresh = [rows for rows in options
             if as_of - timestamp(rows[0]["retrieved_at"]) <= timedelta(days=30)
             and (as_of.date() - day(rows[0]["period_end"])).days <= (180 if rows[0].get("period") == "TTM" else 550)]
    if fresh:
        options = fresh
    # Prefer latest fiscal period, then most usable fields, then SEC on ties.
    options.sort(key=lambda rows: (rows[0]["period_end"], sum(
        number(v) is not None for r in rows[:2] for v in r["values"].values())), reverse=True)
    selected = options[0]
    current = selected[0]
    result.update({"provider": current["provider"], "currency": current["currency"],
                   "period_end": current["period_end"], "available_at": current["available_at"],
                   "basis": current.get("period", "FY")})
    result["reports"] = [{k: r.get(k) for k in ("provider", "period_start", "period_end", "published_at",
                         "retrieved_at", "available_at", "accession", "url", "currency", "snapshot_id",
                         "period", "source_reports", "normalizer_version", "source_fetched_at")}
                         for r in selected[:3]]
    result["warnings"].extend(current.get("warnings", []))
    if (as_of.date() - day(current["period_end"])).days > (180 if current.get("period") == "TTM" else 550):
        return {**result, "status": "STALE_STATEMENTS"}
    if as_of - timestamp(current["retrieved_at"]) > timedelta(days=30):
        return {**result, "status": "CACHE_STALE"}
    vals = _derived(current["values"])
    prior = selected[1] if len(selected) > 1 else None
    if prior and not 330 <= (day(current["period_end"]) - day(prior["period_end"])).days <= 400:
        prior = None
    old = _derived(prior["values"]) if prior else {}
    older = selected[2] if prior and len(selected) > 2 else None
    if older and not 330 <= (day(prior["period_end"]) - day(older["period_end"])).days <= 400:
        older = None
    avg = (vals["assets"] + old["assets"]) / 2 if all(
        number(v) is not None and v > 0 for v in (vals.get("assets"), old.get("assets"))) else None
    previous_avg = (old["assets"] + older["values"]["assets"]) / 2 if older and all(
        number(v) is not None and v > 0 for v in (old.get("assets"), older["values"].get("assets"))) else None
    growth = ratio(vals.get("revenue"), old.get("revenue"))
    accrual = (vals["net_income"] - vals["operating_cash_flow"]
               if vals.get("net_income") is not None and vals.get("operating_cash_flow") is not None else None)
    metrics = {
        "revenue_growth": growth - 1 if growth is not None else None,
        "gross_margin": vals.get("gross_margin"),
        "operating_margin": ratio(vals.get("ebit"), vals.get("revenue")),
        "roa": ratio(vals.get("net_income"), avg),
        "ocf_assets": ratio(vals.get("operating_cash_flow"), avg),
        "accruals_assets": ratio(accrual, avg),
        "fcf_margin": ratio(vals.get("free_cash_flow"), vals.get("revenue")),
        "debt_assets": ratio(vals.get("debt"), vals.get("assets")),
        "current_ratio": vals.get("current_ratio"),
        "interest_coverage": ratio(vals.get("ebit"), vals.get("interest_expense")),
        "stock_compensation_revenue": ratio(vals.get("stock_compensation"), vals.get("revenue")),
        "annual_share_growth": None,
        "debt_includes_leases": vals.get("debt_includes_leases"),
    }
    from market_checker_app.analysis.statement_extensions import extended_metrics
    extra, extra_audit = extended_metrics(vals, old, current, prior)
    metrics.update(extra)
    result["extended_metric_details"] = extra_audit
    from market_checker_app.analysis.accounting_mapping import coverage_details
    result.update({"status": "OK" if all(metrics[k] is not None for k in CORE_METRICS) else "PARTIAL",
                   "metrics": metrics, "coverage": sum(metrics[k] is not None for k in CORE_METRICS) / len(CORE_METRICS),
                   "values": vals, "evidence": current["evidence"],
                   "accounting_basis": {"debt": vals.get("debt_basis"), "interest": vals.get("interest_basis")},
                   "field_coverage": coverage_details(current, vals)})
    result["warnings"].extend(vals.get("accounting_notes", []))
    sector = str(sector).strip()
    if not sector:
        return {**result, "status": "SECTOR_MISSING"}
    if any(word in sector.lower() for word in ("financial", "bank", "insurance", "real estate", "reit")):
        return {**result, "status": "SECTOR_NOT_SUPPORTED"}
    if prior:
        inputs = {**vals, "sector": sector, "currency": current["currency"],
                  "period_basis": current.get("period", "FY"),
                  "published_at": current["published_at"], "prior_published_at": prior["published_at"],
                  "period_end": current["period_end"], "prior_period_end": prior["period_end"],
                  "source": current["provider"], "prior_assets": old.get("assets"),
                  "prior_roa": ratio(old.get("net_income"), previous_avg)}
        for key in ("debt_ratio", "current_ratio", "shares", "gross_margin", "asset_turnover"):
            inputs["prior_" + key] = old.get(key)
        if vals.get("debt_basis") != old.get("debt_basis"):
            inputs["prior_debt_ratio"] = None
            result["warnings"].append("F-score debt comparison requires the same accounting basis")
        # Share counts from different filing vintages may straddle a stock split.
        # Use comparative end-of-period counts only from the SAME annual filing.
        same_filing = bool(current.get("accession") and current.get("accession") == prior.get("accession"))
        if not same_filing:
            inputs["shares"] = inputs["prior_shares"] = None
            result["warnings"].append("F-score share comparison requires both years in the same filing")
        result["share_comparison_basis"] = "same_filing" if same_filing else "unverified"
        if same_filing and current.get("period") == "FY":
            share_ratio = ratio(vals.get("shares"), old.get("shares"))
            result["metrics"]["annual_share_growth"] = share_ratio - 1 if share_ratio is not None else None
        cap = number(market_cap_usd) if current["currency"] == "USD" else None
        # EV cannot be approximated by ignoring minority/preferred interests.
        # A current, currency-checked vendor EV may be supplied by the pipeline.
        inputs["market_cap"] = cap if cap and cap > 0 else None
        result["fundamental_inputs"] = inputs
    else:
        result["warnings"].append("No comparable previous fiscal year")
    return result


def analyze_reports(reports: list[dict], as_of: datetime, sector: str = "",
                    market_cap_usd: float | None = None) -> dict:
    from market_checker_app.analysis.statement_periods import build_period_views
    annual = _analyze_period_reports([r for r in reports if r.get("period") == "FY"],
                                    as_of, sector, market_cap_usd)
    quarters, trailing = build_period_views(reports, as_of)
    # Do not replace a usable annual result with a TTM made only of balance-sheet data.
    complete = [r for r in trailing if all(number(r["values"].get(k)) is not None
                                          for k in ("revenue", "net_income", "operating_cash_flow"))]
    ttm = _analyze_period_reports(complete, as_of, sector, market_cap_usd)
    annual_usable = annual.get("status") in {"OK", "PARTIAL"} and bool(annual.get("fundamental_inputs"))
    ttm_end, annual_end = str(ttm.get("period_end", "")), str(annual.get("period_end", ""))
    usable = (ttm.get("status") in {"OK", "PARTIAL"} and bool(ttm.get("fundamental_inputs"))
              and (ttm_end > annual_end or (ttm_end == annual_end and not annual_usable)))
    result = dict(ttm if usable else annual)
    from market_checker_app.analysis.sec_events import events_at
    result["sec_events"] = events_at(reports, as_of)
    result["basis"] = result.get("basis", "FY")
    result["annual_fundamental_inputs"] = dict(annual.get("fundamental_inputs", {}))
    result["annual_source"] = {k: annual.get(k) for k in
                               ("status", "provider", "period_end", "available_at", "reports")}
    if usable and annual.get("metrics", {}).get("annual_share_growth") is not None:
        result["metrics"] = dict(result["metrics"])
        result["metrics"]["annual_share_growth"] = annual["metrics"]["annual_share_growth"]
        result["reports"] = result["reports"] + annual.get("reports", [])[:2]
        result["available_at"] = max(result["available_at"], annual["available_at"])
    result["quarterly_status"] = ("TTM_APPLIED" if usable else
                                  "ANNUAL_IS_CURRENT" if annual_usable and ttm.get("period_end") and
                                  ttm.get("period_end") == annual.get("period_end") else
                                  "ANNUAL_FALLBACK")
    result["ttm_status"] = ttm.get("status", "DATA_MISSING")
    result["ttm_period_end"] = ttm.get("period_end")
    result["ttm_metrics"] = ttm.get("metrics", {})
    result["ttm_requires_prior_year"] = not bool(ttm.get("fundamental_inputs"))
    result["quarterly_reports"] = [
        {**_quarter_summary(r), "source_reports": r.get("source_reports", [])}
        for r in quarters[:12]
    ]
    if not usable and quarters:
        result["warnings"] = list(result.get("warnings", [])) + [
            "Annual basis retained: current TTM and comparable prior TTM required; see quarterly_status/ttm_status."]
    return result


def _quarter_summary(report):
    values = _derived(report["values"])
    return {
        **{k: report.get(k) for k in ("provider", "period_start", "period_end", "currency",
                                     "published_at", "retrieved_at", "available_at")},
        "revenue": values.get("revenue"), "net_income": values.get("net_income"),
        "operating_income": values.get("operating_income"),
        "operating_cash_flow": values.get("operating_cash_flow"), "capex": values.get("capex"),
        "free_cash_flow": values.get("free_cash_flow"), "assets": values.get("assets"),
        "operating_margin": ratio(values.get("operating_income"), values.get("revenue")),
        "evidence": report.get("evidence", {}), "warnings": report.get("warnings", []),
    }


def feature_vector(statement: Any, signal_time: Any) -> tuple[float, ...]:
    empty = (0.0,) * len(FEATURE_NAMES)
    signal = timestamp(signal_time)
    if not isinstance(statement, dict) or statement.get("schema") != SCHEMA or not signal:
        return empty
    if statement.get("status") not in {"OK", "PARTIAL"}:
        return empty
    observed = timestamp(statement.get("as_of"))
    available = timestamp(statement.get("available_at"))
    if not observed or not available or available > observed or observed > signal:
        return empty
    reports = statement.get("reports", [])
    if not isinstance(reports, list) or not reports or not isinstance(statement.get("metrics"), dict):
        return empty
    for report in reports:
        if not isinstance(report, dict):
            return empty
        times = [timestamp(report.get(k)) for k in ("published_at", "retrieved_at", "available_at")]
        if any(t is None or t > observed for t in times) or times[2] < max(times[0], times[1]):
            return empty
        if report.get("period") == "TTM":
            dependencies = report.get("source_reports")
            if not isinstance(dependencies, list) or not dependencies:
                return empty
            for source in dependencies:
                if not isinstance(source, dict):
                    return empty
                source_times = [timestamp(source.get(k)) for k in
                                ("published_at", "retrieved_at", "available_at")]
                if (any(t is None or t > observed for t in source_times)
                        or source_times[2] < max(source_times[:2]) or source_times[2] > times[2]):
                    return empty
    period_end = day(statement.get("period_end"))
    max_age = 180 if statement.get("basis") == "TTM" else 550
    if not period_end or period_end > observed.date() or (observed.date() - period_end).days > max_age:
        return empty
    limits = ((-1, 3), (-2, 1), (-2, 2), (-2, 2), (-2, 2), (-2, 2), (-2, 2),
              (0, 5), (0, 10), (-50, 50), (-1, 2), (-1, 3),
              (-5, 5), (-5, 5), (-2, 2), (-5, 5), (0, 10), (-5, 5),
              (-2, 2), (-2, 2), (-1, 3), (0, 3), (0, 1))
    values, masks = [], []
    for key, (low, high) in zip(METRICS, limits):
        value = number(statement.get("metrics", {}).get(key))
        values.append(max(low, min(high, value)) if value is not None else 0.0)
        masks.append(float(value is not None))
    return tuple(values + masks)
