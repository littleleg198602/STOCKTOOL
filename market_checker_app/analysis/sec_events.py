"""Bounded SEC 8-K disclosure review; categories are not verified economic impact."""
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import re
from market_checker_app.analysis.financial_statements import timestamp

CATEGORIES = {
    "1.03": ("Bankruptcy / receivership", "HIGH"),
    "2.04": ("Debt acceleration", "HIGH"),
    "4.02": ("Non-reliance on financial statements", "HIGH"),
    "3.01": ("Listing notice / transfer", "REVIEW"),
    "4.01": ("Auditor change", "REVIEW"),
    "3.02": ("Unregistered equity sales", "REVIEW"),
    "2.06": ("Material impairment", "REVIEW"),
}

class _ReadableText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._hidden += 1
        elif tag in {"p", "br", "div", "tr", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._hidden:
            self._hidden -= 1
        elif tag in {"p", "div", "tr", "h1", "h2", "h3"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.parts.append(data)

def extract_sec_item_excerpts(document: bytes, *, form: str) -> tuple[tuple[str, str], ...]:
    """Return bounded, cited 8-K sections for review, not interpreted claims."""
    if form.upper().removesuffix("/A") != "8-K":
        return ()
    parser = _ReadableText()
    parser.feed(document.decode("utf-8", errors="replace"))
    plain = " ".join(" ".join(parser.parts).split())
    pattern = re.compile(r"\bItem\s+(\d{1,2}\.\d{2})\b", re.IGNORECASE)
    matches = list(pattern.finditer(plain))
    # Keep the longest occurrence: a contents entry or cross-reference must
    # not hide the actual section. Excerpts remain un-interpreted evidence.
    excerpts: dict[str, str] = {}
    for index, match in enumerate(matches):
        code = match.group(1)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(plain)
        excerpt = plain[match.end():min(end, match.end() + 1400)].strip(" .:-")
        if len(excerpt) > len(excerpts.get(code, "")):
            excerpts[code] = excerpt
    priority = {code: i for i, code in enumerate(
        ("1.03", "2.04", "4.02", "3.01", "4.01", "3.02", "2.06"))}
    selected = sorted(excerpts, key=lambda code: (priority.get(code, 99), code))[:16]
    return tuple((f"Item {code}", excerpts[code]) for code in selected)


def filing_candidates(payload, cik, as_of):
    recent = payload.get("filings", {}).get("recent", {})
    if not isinstance(recent, dict) or not isinstance(recent.get("form"), list):
        raise ValueError("INVALID_SUBMISSIONS")
    def cell(key, i):
        values = recent.get(key, [])
        return str(values[i]) if isinstance(values, list) and i < len(values) else ""
    result = []
    for i, form in enumerate(recent["form"][:1000]):
        if form not in {"8-K", "8-K/A"}:
            continue
        accepted = timestamp(cell("acceptanceDateTime", i))
        if accepted is None:
            filed = timestamp(cell("filingDate", i))
            accepted = filed + timedelta(days=1) if filed else None
        if accepted is None or not 0 <= (as_of-accepted).total_seconds() <= 90*86400:
            continue
        accession, document = cell("accessionNumber", i), cell("primaryDocument", i)
        if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accession) or not re.fullmatch(r"[A-Za-z0-9_.-]+", document):
            continue
        items = sorted(set(re.findall(r"\d{1,2}\.\d{2}", cell("items", i))) & set(CATEGORIES))
        if not items:
            continue
        result.append({"accession": accession, "form": form, "published_at": accepted.isoformat(),
                       "items": items, "is_amendment": form.endswith("/A"),
                       "source_url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{document}"})
    return sorted(result, key=lambda r: r["published_at"], reverse=True)


def events_at(reports, as_of):
    candidates = [r["sec_events"] for r in reports if isinstance(r.get("sec_events"), dict)
                  and timestamp(r["sec_events"].get("observed_at")) is not None
                  and timestamp(r["sec_events"]["observed_at"]) <= as_of]
    if not candidates:
        return {"status": "NOT_CHECKED", "events": [], "scoring_applied": False}
    monitor = dict(max(candidates, key=lambda m: m["observed_at"]))
    monitor["events"] = [dict(e) for e in monitor.get("events", [])
                         if timestamp(e.get("published_at")) is not None and timestamp(e["published_at"]) <= as_of]
    if as_of - timestamp(monitor["observed_at"]) > timedelta(days=7):
        monitor["status"] = "STALE"
    monitor["scoring_applied"] = False
    return monitor
