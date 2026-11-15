"""Pure SEC period arithmetic. No IO, training, or historical snapshot updates."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from market_checker_app.analysis.financial_statements import INSTANT, TAGS, AVERAGE_FIELDS, day, number, timestamp

FLOW_KEYS = tuple(key for key in TAGS if key not in INSTANT and key not in AVERAGE_FIELDS)
NONNEGATIVE_FLOWS = {"revenue", "cogs", "capex", "depreciation"}


def _reference(report):
    return {key: report.get(key) for key in (
        "provider", "currency", "period", "period_start", "period_end",
        "published_at", "retrieved_at", "available_at", "accession", "url", "snapshot_id",
        "normalizer_version", "source_fetched_at",
    )}


def _sources(report):
    return report.get("source_reports") or [_reference(report)]


def _unique_sources(reports):
    result = {}
    for report in reports:
        for source in _sources(report):
            key = tuple(str(source.get(k)) for k in (
                "snapshot_id", "accession", "period_start", "period_end", "published_at",
            ))
            result[key] = source
    return list(result.values())


def _dated(report, as_of):
    times = [timestamp(report.get(k)) for k in ("published_at", "retrieved_at", "available_at")]
    return (all(t is not None and t <= as_of for t in times)
            and times[2] >= max(times[0], times[1]))


def _latest(rows):
    """Do not silently select between contradictory filings accepted on the same day."""
    if not rows:
        return None
    latest = max(r["published_at"] for r in rows)
    candidates = [r for r in rows if r["published_at"] == latest]
    chosen = max(candidates, key=lambda r: (
        r["retrieved_at"], sum(number(v) is not None for v in r["values"].values()),
        str(r.get("accession", "")),
    ))
    result = {**chosen, "values": dict(chosen["values"]), "evidence": dict(chosen["evidence"])}
    conflicts = []
    for key in result["values"]:
        values = {number(r["values"].get(key)) for r in candidates}
        values.discard(None)
        if len(values) > 1:
            result["values"][key] = None
            result["evidence"][key] = {"status": "CONFLICTING_SAME_DAY_FILINGS"}
            conflicts.append(key)
    if conflicts:
        result["warnings"] = list(result.get("warnings", [])) + [
            "Conflicting same-day filings: " + ", ".join(conflicts)]
    return result


def _difference(current, previous):
    """Q2/Q3/Q4 = later cumulative flow - previous cumulative flow, never balances."""
    start = day(previous["period_end"]) + timedelta(days=1)
    values = {key: value for key, value in current["values"].items() if key in INSTANT}
    evidence = {key: current["evidence"].get(key, {}) for key in values}
    for key in FLOW_KEYS:
        a, b = number(current["values"].get(key)), number(previous["values"].get(key))
        ca = current["evidence"].get(key, {}).get("concept")
        cb = previous["evidence"].get(key, {}).get("concept")
        # A taxonomy change must not silently be treated as comparable subtraction.
        if a is None or b is None or not ca or ca != cb:
            continue
        value = a - b
        if key in NONNEGATIVE_FLOWS and value < 0:
            continue
        values[key] = value
        evidence[key] = {
            "method": "cumulative_difference", "concept": ca, "unit": "USD",
            "formula": "later cumulative - previous cumulative",
            "operands": [
                {**_reference(current), "value": a},
                {**_reference(previous), "value": b},
            ],
        }
    if not any(key in values for key in FLOW_KEYS):
        return None
    return {
        **current, "period": "Q", "period_start": start.isoformat(), "accession": "",
        "values": values, "evidence": evidence, "derived": True,
        "published_at": max(current["published_at"], previous["published_at"]),
        "retrieved_at": max(current["retrieved_at"], previous["retrieved_at"]),
        "available_at": max(current["available_at"], previous["available_at"]),
        "source_reports": _unique_sources([current, previous]),
        "warnings": ["Quarter derived across filings; unreported revisions cannot be detected."]
        if current.get("accession") != previous.get("accession") else [],
    }


def _merge_quarter(rows):
    """A direct reported value takes precedence over arithmetic for the same vintage."""
    base = _latest(rows)
    values, evidence, used = {}, {}, []
    balance_rows = [r for r in rows if any(number(r["values"].get(k)) is not None for k in INSTANT)]
    balance = _latest(balance_rows) if balance_rows else None
    for key in TAGS:
        # A total debt calculation must not mix components from different balance sheets.
        available_rows = ([balance] if balance is not None else []) if key in INSTANT else rows
        candidates = [r for r in available_rows if number(r["values"].get(key)) is not None]
        problem_rows = [r for r in available_rows
                        if r.get("evidence", {}).get(key, {}).get("status")]
        latest_problem = max(problem_rows, key=lambda r: r["published_at"]) if problem_rows else None
        if latest_problem and (not candidates or
                               latest_problem["published_at"] >= max(r["published_at"] for r in candidates)):
            evidence[key] = dict(latest_problem["evidence"][key])
            used.append(latest_problem)
            continue
        if not candidates:
            continue
        newest = max(r["published_at"] for r in candidates)
        candidates = [r for r in candidates if r["published_at"] == newest]
        direct = [r for r in candidates if not r.get("derived")]
        chosen = _latest(direct or candidates)
        if number(chosen["values"].get(key)) is not None:
            values[key] = chosen["values"][key]
            evidence[key] = {**chosen["evidence"].get(key, {}),
                             "source_reports": _sources(chosen)}
            used.append(chosen)
    if not used:
        return None
    return {
        **base, "period": "Q", "accession": "", "values": values, "evidence": evidence,
        "published_at": max(r["published_at"] for r in used),
        "retrieved_at": max(r["retrieved_at"] for r in used),
        "available_at": max(r["available_at"] for r in used),
        "source_reports": _unique_sources(used),
        "warnings": sorted({w for r in used for w in r.get("warnings", [])}),
    }


def build_period_views(reports, as_of):
    """Return known-at-observation quarters and trailing four-quarter windows for SEC."""
    as_of = timestamp(as_of)
    if as_of is None:
        return [], []
    groups = defaultdict(list)
    for report in reports:
        start, end = day(report.get("period_start")), day(report.get("period_end"))
        if (report.get("provider") != "sec" or report.get("period") not in {"FY", "Q", "YTD"}
                or not start or not end or end > as_of.date()
                or not _dated(report, as_of) or not isinstance(report.get("values"), dict)
                or not isinstance(report.get("evidence"), dict)):
            continue
        # Keep enough history for current/prior/older TTM without quadratic work over decades.
        if (as_of.date() - end).days > 6 * 366:
            continue
        groups[(report["provider"], report["currency"])].append(report)
    quarters, trailing = [], []
    for _, records in groups.items():
        candidates = defaultdict(list)
        cumulative = defaultdict(list)
        for r in records:
            duration = (day(r["period_end"]) - day(r["period_start"])).days + 1
            if 60 <= duration <= 110:
                candidates[(r["period_start"], r["period_end"])].append(r)
            if 60 <= duration <= 380:
                cumulative[r["period_start"]].append(r)
        for fiscal_records in cumulative.values():
            for current in fiscal_records:
                if (day(current["period_end"]) - day(current["period_start"])).days + 1 < 150:
                    continue
                possible = [p for p in fiscal_records
                            if 60 <= (day(current["period_end"]) - day(p["period_end"])).days <= 110
                            and p["published_at"] <= current["published_at"]]
                if not possible:
                    continue
                end = max(p["period_end"] for p in possible)
                prior = _latest([p for p in possible if p["period_end"] == end])
                derived = _difference(current, prior)
                if derived:
                    candidates[(derived["period_start"], derived["period_end"])].append(derived)
        merged = [_merge_quarter(rows) for rows in candidates.values()]
        merged = [r for r in merged if r is not None]
        by_end = defaultdict(list)
        for row in merged:
            by_end[row["period_end"]].append(row)
        # Ambiguous start dates for one end date cannot enter a consecutive-quarter chain.
        ordered = sorted((rows[0] for rows in by_end.values() if len(rows) == 1),
                         key=lambda r: r["period_end"])
        quarters.extend(ordered)
        for i in range(3, len(ordered)):
            window = ordered[i-3:i+1]
            if any(day(a["period_end"]) + timedelta(days=1) != day(b["period_start"])
                   for a, b in zip(window, window[1:])):
                continue
            duration = (day(window[-1]["period_end"]) - day(window[0]["period_start"])).days + 1
            if not 330 <= duration <= 400:
                continue
            latest = window[-1]
            values = {k: v for k, v in latest["values"].items() if k in INSTANT}
            evidence = {k: latest["evidence"].get(k, {}) for k in INSTANT
                        if k in values or latest.get("evidence", {}).get(k, {}).get("status")}
            for key in FLOW_KEYS:
                nums = [number(r["values"].get(key)) for r in window]
                concepts = {r["evidence"].get(key, {}).get("concept") for r in window}
                if any(v is None for v in nums) or None in concepts or len(concepts) != 1:
                    continue
                values[key] = sum(nums)
                evidence[key] = {
                    "method": "sum_four_nonoverlapping_quarters", "concept": next(iter(concepts)),
                    "unit": "USD", "operands": [
                        {"start": r["period_start"], "end": r["period_end"], "value": value,
                         "evidence": r["evidence"].get(key, {})}
                        for r, value in zip(window, nums)],
                }
            if not any(k in values for k in FLOW_KEYS):
                continue
            trailing.append({
                **latest, "period": "TTM", "period_start": window[0]["period_start"],
                "accession": "", "values": values, "evidence": evidence,
                "published_at": max(r["published_at"] for r in window),
                "retrieved_at": max(r["retrieved_at"] for r in window),
                "available_at": max(r["available_at"] for r in window),
                "source_reports": _unique_sources(window),
                "warnings": sorted({w for r in window for w in r.get("warnings", [])}),
            })
    return sorted(quarters, key=lambda r: r["period_end"], reverse=True), trailing
