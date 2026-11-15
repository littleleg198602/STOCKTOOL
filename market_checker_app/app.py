from __future__ import annotations

from pathlib import Path
import re
import sys

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import json
import os
import sqlite3
import time

import altair as alt
import pandas as pd
import streamlit as st

from market_checker_app.analysis.buy_analysis import DEFAULT_WEIGHTS, CONFIG as BUY_CONFIG, combine as combine_buy, model_position
from market_checker_app.analysis.buy_learning import (
    LearningConfig, config_key, inspect_history, load_model, load_learning_report, save_learning_result, train_from_history,
)
from market_checker_app.services.financial_statements_service import FinancialStatementsService
from market_checker_app.collectors.financial_statements_client import StatementsError
from market_checker_app.analysis.scoring import validate_decision_scenarios
from market_checker_app.collectors.mt5_client import MT5Client
from market_checker_app.config import AppConfig, DEFAULT_DB_PATH, DEFAULT_OUTPUT_DIR
from market_checker_app.exporters.dashboard_builder import build_dashboard_tables
from market_checker_app.exporters.delta_builder import prepare_delta_for_excel
from market_checker_app.exporters.excel_exporter import ExcelExporter
from market_checker_app.models import AnalysisProgressState
from market_checker_app.services.comparison_service import ComparisonService
from market_checker_app.services.evaluation_service import EvaluationService
from market_checker_app.services.history_service import HistoryService
from market_checker_app.services.pipeline_service import PipelineService
from market_checker_app.services.ranking_service import RankingService
from market_checker_app.services.visualization_service import VisualizationService
from market_checker_app.services.yahoo_enrichment_service import YahooEnrichmentService
from market_checker_app.storage.sqlite_store import SQLiteStore
from market_checker_app.storage.yahoo_cache_store import YahooCacheCoverage, YahooCacheStore
from market_checker_app.utils.charts import (
    histogram_chart,
    line_chart,
    multi_line_chart,
    scatter_score_confidence,
    signal_bar_chart,
    top_bottom_bar_chart,
)




def _render_buy_price_cache(cache: YahooCacheStore, watchlist: list[str]) -> None:
    context = f"buy_price_job:{cache.db_path.resolve()}"
    previous = st.session_state.get("buy_price_active_context")
    if previous and previous != context:
        old_job = st.session_state.get(previous)
        if old_job and old_job.get("active"):
            old_job.update(active=False, status="database_changed")
    st.session_state["buy_price_active_context"] = context
    existing = st.session_state.get(context)
    interval = 1.0 if existing and existing.get("active") else None

    @st.fragment(run_every=interval)
    def render_prices():
        job = st.session_state.get(context)
        active = bool(job and job.get("active"))
        if not active and interval is not None:
            st.rerun()  # Disable the timer even if a previous render was interrupted.
        with st.expander("Cenová data pro BUY a učení", expanded=active):
            include_benchmark = st.checkbox(
                "Doplnit také benchmark SPY", value=True, key="buy_price_include_benchmark",
                disabled=active,
            )
            tickers = list(dict.fromkeys(
                (["SPY"] if include_benchmark else []) +
                [str(t).strip().upper() for t in watchlist if str(t).strip()]
            ))
            if active and job["tickers"] != tickers:
                job.update(active=False, status="watchlist_changed")
                st.rerun()
            service = YahooEnrichmentService(cache)
            start_col, stop_col = st.columns(2)
            start = start_col.button(
                "Aktualizovat ceny celého watchlistu", disabled=active or not bool(watchlist),
                key="buy_price_refresh_all",
            )
            stop = stop_col.button("Zastavit načítání", disabled=not active, key="buy_price_stop")
            if stop:
                job.update(active=False, status="stopped")
                st.rerun()
            try:
                if start:
                    st.session_state[context] = service.start_price_refresh(
                        watchlist, include_benchmark=include_benchmark)
                    st.rerun()
                if active:
                    with st.spinner("Doplňuji ceny; další tickery pokračují automaticky..."):
                        service.step_price_refresh(job)
                    if not job["active"]:
                        st.rerun()
                coverage = cache.price_coverage(tickers)
            except (ValueError, OSError, sqlite3.Error) as exc:
                if job is not None:
                    job.update(active=False, status="storage_error", error=str(exc))
                st.error(f"Načítání cen se zastavilo: {exc}")
                if active:
                    st.rerun()
                return
            st.write(
                f"Upravené denní ceny: {coverage['fresh']} čerstvých, "
                f"{coverage['stale']} starších, {coverage['missing']} chybí; "
                f"{coverage['cooldown']} čeká po chybě."
            )
            if job and job["tickers"] == tickers:
                total = len(job["tickers"])
                handled = total - len(job["pending"])
                st.progress(handled / max(1, total),
                            text=f"Vyřízeno {handled}/{total} tickerů celého watchlistu")
                st.caption(
                    f"Staženo a uloženo: {job['saved']} · již čerstvé/převzaté z cache: "
                    f"{job['initial_fresh'] + job['reused']} · "
                    f"trvale neúspěšné v tomto běhu: {len(job['failed'])} · zbývá: {len(job['pending'])}."
                )
                if job["active"]:
                    wait = max(0, int(job["next_action_at"] - time.time() + 0.999))
                    if job["status"] == "waiting_yahoo":
                        st.info(f"Yahoo dočasně omezilo požadavky. Automaticky pokračuji přibližně za {wait} s.")
                    elif job["status"] == "waiting_retry":
                        st.info(f"Zbývající tickery čekají po chybě. Další pokus automaticky za {wait // 60} min {wait % 60} s.")
                    else:
                        st.caption(f"Poslední zpracovaný ticker: {job['last_ticker'] or '—'}. Další pokračuje automaticky.")
                elif job["status"] == "complete":
                    if coverage["fresh"] == coverage["total"]:
                        st.success("Ceny celého zvoleného watchlistu jsou připravené.")
                        st.info("Teď spusťte běžnou analýzu. Ta ceny započítá do BUY_SCORE i FinalTotalScore a uloží vstupy pro učení.")
                    else:
                        st.info("Předchozí načítání je dokončené, ale část cen už potřebuje obnovit. Spusťte novou aktualizaci.")
                elif job["status"] == "complete_with_errors":
                    st.warning("Načítání dokončeno s chybami. Nedostupné tickery nejsou označené jako úspěšné.")
                elif job["status"] == "source_unavailable":
                    st.warning("Yahoo opakovaně omezuje požadavky. Po pěti omezeních se běh zastavil; uložené ceny zůstaly zachované.")
                elif job["status"] == "storage_error":
                    st.error("Načítání zastavila chyba: " + job.get("error", ""))
                else:
                    st.info("Načítání je zastavené. Další spuštění přeskočí už uložené čerstvé ceny.")
                if job["errors"]:
                    if st.checkbox("Zobrazit tickery s chybou", key="buy_price_show_errors"):
                        st.dataframe(pd.DataFrame([
                            {"Ticker": ticker, "Pokusy": job["attempts"].get(ticker, 0),
                             "Stav": ("Nedostupné po opakování" if ticker in job["failed"] else
                                      "Čeká na další pokus" if job["active"] else "Nedokončeno"),
                             "Důvod": error}
                            for ticker, error in job["errors"].items()
                        ]), hide_index=True, width="stretch")
            st.caption(
                "Jedno spuštění postupně doplní celý watchlist. Čerstvé ceny přeskočí a výsledky "
                "ukládá po každém tickeru. Po dočasném omezení samo pokračuje; jednotlivé chyby "
                "zkusí nejvýše dvakrát s čekací dobou. Zastavení platí po dokončení aktuálního požadavku. "
                "Během načítání nechte aplikaci otevřenou a připojenou. Po restartu stačí znovu spustit "
                "aktualizaci; uložená cache se využije. Načtení cen samo nespouští analýzu ani trénink."
            )
    render_prices()


def _render_financial_statements(db_path: Path, watchlist: list[str]) -> None:
    context = f"statements_job:{Path(db_path).resolve()}"
    previous = st.session_state.get("statements_active_context")
    if previous and previous != context:
        old_job = st.session_state.get(previous)
        if old_job and old_job.get("active"):
            old_job.update(active=False, status="database_changed")
    st.session_state["statements_active_context"] = context
    existing = st.session_state.get(context)
    interval = 1.0 if existing and existing.get("active") else None
    labels = {
        "API_KEY_REQUIRED": "Chybí API klíč.",
        "SEC_CONTACT_REQUIRED": "Vyplňte platný kontaktní e-mail pro SEC.",
        "HTTP_401": "Zdroj odmítl přihlášení; zkontrolujte API klíč.",
        "HTTP_402": "Tento přístup může vyžadovat jiný tarif.",
        "HTTP_403": "Zdroj zamítl přístup; ověřte tarif nebo nastavení SEC.",
        "HTTP_429": "Zdroj dočasně omezil počet požadavků.",
        "NO_SUPPORTED_STATEMENTS": "Žádné podporované datované výkazy.",
        "NO_SUPPORTED_ANNUAL_STATEMENTS": "Žádné podporované datované roční výkazy.",
        "SEC_TICKER_NOT_FOUND": "Ticker nemá nalezené CIK v mapě SEC.",
        "PROVIDER_REJECTED_REQUEST": "Zdroj odmítl požadavek; ověřte klíč, tarif a limity.",
        "NETWORK_ERROR": "Spojení se zdrojem selhalo.",
        "INVALID_SYMBOL_MAPPING": "Zdroj vrátil nepoužitelnou mapu tickerů.",
        "EMPTY_SYMBOL_MAPPING": "Zdroj vrátil prázdnou mapu tickerů.",
        "UNSUPPORTED_STATEMENT_FORMAT": "Formát výkazu není podporovaný.",
        "INVALID_SYMBOL": "Zdroj nepodporuje tento zápis tickeru.",
        "HTTP_404": "Zdroj data nenašel.",
    }

    @st.fragment(run_every=interval)
    def render_statements():
        job = st.session_state.get(context)
        active = bool(job and job.get("active"))
        if not active and interval is not None:
            st.rerun()
        with st.expander("Firemní výkazy pro BUY a učení", expanded=active):
            providers = {"sec": "SEC EDGAR", "fmp": "Financial Modeling Prep", "finnhub": "Finnhub"}
            provider = st.selectbox("Zdroj výkazů", list(providers), format_func=providers.get,
                                    key="statements_provider", disabled=active)
            contact, credential = "", ""
            if provider == "sec":
                contact = st.text_input("Kontaktní e-mail pro požadavky SEC",
                                        value=os.environ.get("SEC_CONTACT_EMAIL", ""),
                                        key="statements_sec_contact", disabled=active)
                st.caption("SEC nevyžaduje API klíč. E-mail identifikuje klienta v požadavcích podle pravidel SEC.")
            else:
                variable = "FMP_API_KEY" if provider == "fmp" else "FINNHUB_API_KEY"
                credential = st.text_input("API klíč", value=os.environ.get(variable, ""),
                                            type="password", key="statements_key_" + provider, disabled=active)
                st.caption("Dostupnost výkazů závisí na vašem tarifu. Klíč se neukládá do historie ani reportů.")
            tickers = list(dict.fromkeys(str(t).strip().upper() for t in watchlist if str(t).strip()))
            if active and (job["tickers"] != tickers or job["provider"] != provider):
                job.update(active=False, status="settings_changed")
                st.rerun()
            service = FinancialStatementsService(db_path)
            start_col, stop_col = st.columns(2)
            start = start_col.button("Aktualizovat výkazy celého watchlistu",
                                     disabled=active or not tickers, key="statements_refresh_all")
            stop = stop_col.button("Zastavit načítání výkazů", disabled=not active, key="statements_stop")
            if stop:
                job.update(active=False, status="stopped")
                st.rerun()
            try:
                if start:
                    st.session_state[context] = service.start_refresh(tickers, provider, credential, contact)
                    st.rerun()
                if active:
                    with st.spinner("Načítám výkazy; další firmy pokračují automaticky..."):
                        service.step_refresh(job, credential, contact)
                    if not job["active"]:
                        st.rerun()
                states = service.store.statuses(provider)
            except StatementsError as exc:
                if active:
                    job.update(active=False, status="access_blocked", error_code=exc.code)
                    st.rerun()
                st.warning(labels.get(exc.code, exc.code))
                return
            except (OSError, sqlite3.Error, ValueError):
                if job:
                    job.update(active=False, status="storage_error")
                if active:
                    st.rerun()
                st.error("Výkazy nelze uložit nebo načíst. Zkontrolujte cestu a přístup k databázi.")
                return
            now = time.time()
            good = sum(states.get(t, {}).get("status") == "OK" for t in tickers)
            fresh = sum(states.get(t, {}).get("status") == "OK"
                        and service._deadline(states[t]) > now for t in tickers)
            st.caption(f"Zdroj {providers[provider]}: {fresh}/{len(tickers)} firem má čerstvě načtené výkazy; "
                       f"poslední načtení bylo úspěšné u {good}. Úplnost ukazatelů ukáže analýza.")
            if job and job["provider"] == provider and job["tickers"] == tickers:
                total = len(tickers)
                handled = total - len(job["pending"])
                st.progress(handled / max(1, total), text=f"Vyřízeno {handled}/{total} firem celého watchlistu")
                st.caption(f"Uloženo: {job['saved']} · čerstvé z cache: {job['initial_fresh'] + job['reused']} · "
                           f"nedostupné v tomto běhu: {len(job['failed'])} · zbývá: {len(job['pending'])}.")
                if job["active"]:
                    wait = max(0, int(job["next_action_at"] - now + 0.999))
                    if job["status"] in {"waiting_source", "waiting_retry"}:
                        reason = labels.get(job.get("error_code"), job.get("error_code", "")) if job["status"] == "waiting_source" else ""
                        st.info(f"{reason} Čekám na další povolený pokus. Automaticky pokračuji přibližně za "
                                f"{wait // 3600} h {(wait % 3600) // 60} min {wait % 60} s.")
                    else:
                        st.caption(f"Poslední firma: {job['last_ticker'] or '—'}. Další pokračuje automaticky.")
                elif job["status"] == "complete":
                    if fresh == total:
                        st.success("Výkazy celého watchlistu jsou načtené.")
                        st.info("Spusťte běžnou analýzu s ukládáním historie. Ta použije výkazy pro BUY_SCORE, FinalTotalScore a další učení.")
                    else:
                        st.info("Předchozí načítání je dokončené, ale část výkazů už potřebuje obnovit.")
                elif job["status"] == "complete_with_errors":
                    st.warning("Průchod dokončen. Část firem zdroj nepokrývá nebo se je nepodařilo načíst; dostupné výkazy jsou uložené.")
                elif job["status"] == "access_blocked":
                    st.error(labels.get(job["error_code"], job["error_code"]))
                    st.caption("Načítání je zastavené. Po opravě přístupu nebo změně zdroje znovu spusťte aktualizaci.")
                elif job["status"] == "source_unavailable":
                    st.warning("Zdroj opakovaně selhává nebo omezuje požadavky. Po pěti takových chybách se běh zastavil.")
                elif job["status"] == "storage_error":
                    st.error("Načítání zastavila chyba databáze. Zkontrolujte její cestu a přístup.")
                else:
                    st.info("Načítání je zastavené. Další spuštění využije již uložené výkazy.")
                if job["errors"] and st.checkbox("Zobrazit firmy s chybou", key="statements_show_errors"):
                    st.dataframe(pd.DataFrame([
                        {"Ticker": ticker, "Pokusy v tomto běhu": job["attempts"].get(ticker, 0),
                         "Důvod": labels.get(code, code)}
                        for ticker, code in job["errors"].items()
                    ]), hide_index=True, width="stretch")
            st.caption(
                "Jedno spuštění postupně doplní celý watchlist ze zvoleného zdroje a přeskočí čerstvou cache. "
                "Ukládá po každé firmě. Dočasné chyby opakuje nejvýše dvakrát s čekací dobou; "
                "nepodporované firmy přeskočí a chybu přístupu oznámí. Zastavení platí po dokončení aktuální firmy. "
                "Aplikaci nechte otevřenou a připojenou. Po restartu aktualizaci znovu spusťte; cache zůstává zachovaná."
            )
            st.caption(
                "SEC poskytuje roční i čtvrtletní výkazy. Při dostatku dat analýza použije posledních 12 měsíců (TTM) pro B03/B04; B06 zůstává roční. Tyto strategie "
                "mají dohromady výchozí váhu 40 % BUY modelu, pokud jsou dostupná potřebná data. "
                "V hlavním FinalTotalScore nyní tvoří až 25 % rozhodovacích vstupů podle pokrytí. Po stažení spusťte analýzu, která skóre přepočítá. "
                "Datované ukazatele se také ukládají pro budoucí učení; chybějící údaje nejsou negativní signál."
            )
    render_statements()


def _render_statement_coverage(statement: dict) -> None:
    coverage = statement.get("field_coverage", [])
    if not coverage:
        st.caption("Podrobné pokrytí položek vznikne po nové analýze.")
        return
    labels = {
        "debt": "Celkový dluh", "net_debt": "Čistý dluh",
        "debt_current": "Krátkodobá část dlouhodobého dluhu",
        "debt_long": "Dlouhodobá část dluhu", "short_borrowings": "Krátkodobé půjčky celkem",
        "debt_lease_current": "Dluh a leasingy: krátkodobá část",
        "debt_lease_noncurrent": "Dluh a leasingy: dlouhodobá část",
        "debt_lease_total": "Dlouhodobý dluh a leasingy včetně splatné části",
        "commercial_paper": "Krátkodobé dluhové cenné papíry",
        "shares": "Akcie v oběhu ke konci období", "shares_issued": "Vydané akcie včetně vlastních",
        "treasury_shares": "Vlastní akcie (mohou zahrnovat preferenční)",
        "weighted_basic_shares": "Vážený průměr akcií pro základní EPS",
        "weighted_diluted_shares": "Vážený průměr akcií pro zředěné EPS",
        "stock_compensation": "Náklad na akciové odměny",
        "interest_expense": "Úrokové náklady", "interest_expense_debt": "Úroky jen z dluhu",
        "gross_profit": "Hrubý zisk", "revenue": "Tržby", "cogs": "Náklady na tržby",
        "operating_cash_flow": "Provozní cash flow", "free_cash_flow": "Volné cash flow",
        "capex": "Investice do dlouhodobého hmotného majetku",
    }
    statuses = {
        "AVAILABLE": "Vykázáno", "DERIVED": "Dopočteno z doložených položek",
        "MISSING": "Chybí", "OTHER_DATE_ONLY": "Existuje pouze k jinému datu",
        "INVALID_NEGATIVE": "Záporná hodnota není pro tuto položku přípustná",
        "CONFLICTING_FACTS": "Rozporné hodnoty v podání",
        "CONFLICTING_SAME_DAY_FILINGS": "Rozporná podání ze stejného dne",
        "CONFLICTING_DEBT_COMPONENTS": "Nesouhlasí složky dluhu",
        "INCOMPLETE_DEBT_COMPONENTS": "Chybí složka celkového dluhu",
        "NOT_AGGREGATED": "Průměr akcií se do TTM nesčítá",
    }
    bases = {
        "including_finance_capital_leases": "včetně finančních/kapitálových leasingů",
        "excluding_finance_capital_leases": "bez finančních/kapitálových leasingů",
        "vendor_reported_total": "součet poskytovatele; rozsah leasingů neověřen",
        "unavailable": "nedostupný",
    }
    basis = statement.get("accounting_basis", {}).get("debt", "unavailable")
    present = sum(r.get("value") is not None for r in coverage)
    st.markdown("**Dostupnost účetních položek**")
    st.caption(f"Položky: {present}/{len(coverage)} · Základ dluhu: {bases.get(basis, basis)}")
    st.dataframe(pd.DataFrame([
        {"Položka": labels.get(r["field"], r["field"]), "Hodnota": r.get("value"),
         "Jednotka": r.get("unit"), "Stav": statuses.get(r["status"], r["status"]),
         "Zdrojový koncept": r.get("concept"), "Výpočet": r.get("method"),
         "Potřebné položky": ", ".join(r.get("required_fields", [])),
         "Jiná data pozorování": ", ".join(r.get("other_observation_dates", []))}
        for r in coverage]), hide_index=True, width="stretch")
    st.caption("Počet dostupných položek není skóre firmy. Alternativní položky se "
               "nesčítají automaticky a chybějící hodnota není nula.")


def _render_statement_detail(payload: dict) -> None:
    statement = payload.get("financial_statements", {})
    names = {
        "OK": "Výkazy jsou připravené", "PARTIAL": "Část ukazatelů chybí",
        "DATA_MISSING": "Výkazy nejsou načtené", "SECTOR_MISSING": "Chybí sektor firmy",
        "SECTOR_NOT_SUPPORTED": "Finanční firmy a REIT zatím potřebují samostatnou metodiku",
        "STALE_STATEMENTS": "Poslední použitelné období je příliš staré",
        "CACHE_STALE": "Výkazy nebyly obnoveny více než 30 dnů", "STORAGE_ERROR": "Chyba čtení výkazů",
    }
    with st.expander("Rozbor výkazů a původ údajů", expanded=False):
        status = statement.get("status", "DATA_MISSING")
        st.write(names.get(status, status))
        st.caption(f"Zdroj: {statement.get('provider', '—')} · měna: {statement.get('currency', '—')} · "
                   f"období do: {statement.get('period_end', '—')} · "
                   f"pokrytí ukazatelů: {statement.get('coverage', 0):.0%}")
        monitor = statement.get("sec_events", {})
        st.write("SEC 8-K: " + monitor.get("status", "NOT_CHECKED"))
        st.caption("Kontrola posledn\u00edch 90 dn\u016f, nejv\u00fd\u0161e 3 dokumenty na firmu. Kategorie pod\u00e1n\u00ed nen\u00ed ov\u011b\u0159en\u00ed dopadu a sama nem\u011bn\u00ed sk\u00f3re. Chyb\u011bj\u00edc\u00ed upozorn\u011bn\u00ed nepotvrzuje absenci rizik.")
        if monitor.get("events"):
            st.dataframe(pd.DataFrame(monitor["events"]), hide_index=True, width="stretch")
        if monitor.get("errors"):
            st.write({"chyby_SEC_8K": monitor["errors"]})
        if statement.get("extended_metric_details"):
            st.dataframe(pd.DataFrame([{"ukazatel": name, **detail}
                                      for name, detail in statement["extended_metric_details"].items()]).drop(columns=["sources"], errors="ignore"),
                         hide_index=True, width="stretch")
            st.caption("Pom\u011bry a r\u016fst jsou desetinn\u00e1 \u010d\u00edsla (0,10 = 10 %); zm\u011bna mar\u017ee 0,01 = 1 procentn\u00ed bod. Zdroje jsou zachov\u00e1ny v auditu.")
        basis = statement.get("basis", "FY")
        period_labels = {"TTM_APPLIED": "Použity poslední čtyři čtvrtletí",
                         "ANNUAL_IS_CURRENT": "Roční výkaz pokrývá stejné poslední období",
                         "ANNUAL_FALLBACK": "Použity roční údaje; pro novější TTM chybí vhodná data"}
        st.write("Základ ukazatelů: **" + ("posledních 12 měsíců (TTM)" if basis == "TTM" else "roční výkazy (FY)") + "**")
        st.caption(period_labels.get(statement.get("quarterly_status"), "Starší analýza bez čtvrtletního rozboru"))
        if statement.get("quarterly_reports"):
            st.markdown("**Jednotlivá čtvrtletí ze SEC**")
            quarterly = pd.DataFrame(statement["quarterly_reports"])
            columns = ["period_start", "period_end", "currency", "revenue", "operating_income",
                       "net_income", "operating_cash_flow", "capex", "free_cash_flow",
                       "assets", "operating_margin", "available_at"]
            st.dataframe(quarterly[[c for c in columns if c in quarterly]], hide_index=True, width="stretch")
            st.caption("Peněžní hodnoty jsou v uvedené měně, nikoli automaticky v milionech. "
                       "Cash flow a investice jsou za dané čtvrtletí; aktiva jsou stav ke konci období. "
                       "Prázdná hodnota znamená nedostupný nebo rozporný údaj.")
            st.json({"quarterly_provenance": statement["quarterly_reports"]}, expanded=False)
        _render_statement_coverage(statement)
        st.caption("Pokryt\u00ed z\u016fst\u00e1v\u00e1 podle 10 hlavn\u00edch ukazatel\u016f. Roz\u0161\u00ed\u0159en\u00e9 vstupy maj\u00ed vlastn\u00ed dostupnost; nejsou automaticky dal\u0161\u00edmi body nav\u00edc.")
        metric_labels = {
            "revenue_growth": "Meziroční růst tržeb", "gross_margin": "Hrubá marže",
            "operating_margin": "Provozní marže", "roa": "Zisk / průměrná aktiva",
            "ocf_assets": "Provozní cash flow / průměrná aktiva",
            "accruals_assets": "(Zisk − provozní cash flow) / průměrná aktiva",
            "fcf_margin": "Volné cash flow / tržby", "debt_assets": "Dluh / aktiva",
            "current_ratio": "Oběžná aktiva / krátkodobé závazky",
            "interest_coverage": "Provozní zisk / úrokové náklady",
            "stock_compensation_revenue": "Akciové odměny / tržby (vstup pro učení)",
            "annual_share_growth": "Roční změna akcií v oběhu (srovnatelné podání)",
            "debt_includes_leases": "Základ dluhu: 1 = včetně leasingů, 0 = bez nich",
        }
        if statement.get("metrics"):
            st.dataframe(pd.DataFrame([
                {"Ukazatel": metric_labels.get(k, k), "Hodnota (poměr)": v}
                for k, v in statement["metrics"].items()
            ]), hide_index=True, width="stretch")
            st.caption("U marží a růstu znamená 0,10 hodnotu 10 %. Likvidita a úrokové krytí jsou násobky. "
                       "Prázdná hodnota znamená chybějící údaj.")
        if statement.get("reports"):
            report_table = pd.DataFrame(statement["reports"])
            st.dataframe(report_table.drop(columns=["source_reports"], errors="ignore"),
                         hide_index=True, width="stretch")
        st.caption("FY nebo TTM je uvedeno výše. EBIT je provozní zisk; EBITDA je jeho aproximace přičtením "
                   "vykázaných odpisů. Chybějící dluhové položky se nepovažují za nulu.")
        if statement.get("warnings"):
            st.write(statement["warnings"])
        st.json({"values": statement.get("values", {}), "evidence": statement.get("evidence", {}),
                 "valuation_source": statement.get("valuation_source"),
                 "reports": statement.get("reports", []),
                 "ttm_status": statement.get("ttm_status"),
                 "ttm_requires_prior_year": statement.get("ttm_requires_prior_year")})


def _render_buy_learning(db_path: Path):
    status_labels = {
        "READY": "Experimentální model splnil nastavené podmínky",
        "MODEL_STALE": "Uložený model zestárl; pro přeučení je potřeba nová historie",
        "OK": "Historie je načtená",
        "HISTORY_DATABASE_MISSING": "Databáze historie neexistuje",
        "BUY_HISTORY_NOT_AVAILABLE": "Zatím nejsou uložené BUY analýzy",
        "HISTORY_READ_FAILED": "Historii se nepodařilo načíst",
        "PRICE_PROVENANCE_MISSING": "Chybí historie s doloženou úpravou cen",
        "NO_MATURED_EXAMPLES": "Zatím nejsou dostupné následné výsledky",
        "NOT_ENOUGH_HISTORY": "Málo dokončených historických příkladů",
        "INSUFFICIENT_TIME_PERIODS": "Málo různých dnů analýzy",
        "INSUFFICIENT_TEMPORAL_VALIDATION": "Chybí historie pro tři časová ověření",
        "INSUFFICIENT_OUTCOME_WINDOWS": "Málo oddělených období následných výsledků",
        "STATEMENTS_NOT_BETTER": "Výkazy nezlepšily model dostatečně proti variantě bez přímých ukazatelů",
        "NOT_BETTER_THAN_BASELINE": "Nový model nepřekonal základní odhad dostatečně stabilně",
    }
    with st.expander("Učení BUY analyzátoru", expanded=False):
        horizon = st.selectbox("Horizont výsledku (obchodní seance)", [20, 60],
                               key="buy_learning_v7_horizon")
        targets = {
            "absolute_return": "Kladný výnos po modelových nákladech",
            "benchmark_excess_return": "Překonání SPY po modelových nákladech",
        }
        target = st.selectbox("Co se model učí odhadovat", list(targets),
                              format_func=lambda value: targets[value], key="buy_learning_v7_target")
        cost = st.number_input("Náklady na vstup a výstup dohromady (bazické body; 10 = 0,1 %)",
                               min_value=0.0, max_value=1000.0, value=10.0, step=5.0,
                               key="buy_learning_v7_cost")
        use_statements = st.checkbox("Zahrnout ukazatele z výkazů a ověřit jejich přínos", value=True,
                                     key="buy_learning_statements")
        st.caption("Rozšířený model musí překonat také model bez přímých ukazatelů z výkazů na stejných příkladech. "
                   "Obě varianty používají současné BUY strategie. Nová metodika používá pouze nové uložené analýzy.")
        learning_config = LearningConfig(horizon_sessions=int(horizon), target=target,
                                          round_trip_cost_bps=float(cost), include_statements=use_statements)
        context = f"buy_learning_v7:{Path(db_path).resolve()}:{config_key(learning_config)}"
        if context not in st.session_state:
            try:
                restored = load_model(db_path, learning_config)
                st.session_state[context] = {"model": restored, "report": load_learning_report(db_path, learning_config)}
            except (ValueError, OSError, sqlite3.Error) as exc:
                st.session_state[context] = {"model": None, "load_error": str(exc)}
        state = st.session_state[context]
        if state.get("load_error"):
            st.warning(f"Uložený model nelze načíst: {state['load_error']}")
        inspect_col, train_col = st.columns(2)
        if inspect_col.button("Zkontrolovat dostupnou historii", key="buy_learning_v7_inspect"):
            with st.spinner("Čtu uložené analýzy a dostupné následné ceny..."):
                state["inspection"] = inspect_history(db_path, learning_config)
        if train_col.button("Natrénovat a vyhodnotit model", key="buy_learning_v7_train"):
            progress = st.empty()
            progress_text = {
                "Reading historical BUY inputs": "Načítám uložené BUY příklady...",
                "Training finished; experimental model passed configured gates": "Vyhodnocení je dokončené.",
            }
            def show_progress(message):
                if message.startswith("Fitting chronological period"):
                    message = "Vyhodnocuji časové období " + message.rsplit(" ", 1)[-1]
                progress.caption(progress_text.get(message, message))
            with st.spinner("Učím model a ověřuji ho na třech pozdějších obdobích..."):
                candidate, report = train_from_history(
                    db_path, config=learning_config, progress_callback=show_progress
                )
            state["report"] = report
            state.pop("inspection", None)
            state.pop("save_error", None)
            try:
                save_learning_result(db_path, learning_config, candidate, report)
            except (ValueError, OSError, sqlite3.Error) as exc:
                state["save_error"] = str(exc)
            if candidate is not None:
                state["model"] = candidate
                state.pop("load_error", None)
            progress.empty()
        report = state.get("inspection") or state.get("report")
        if report:
            status = report.get("status", "")
            st.write(status_labels.get(status, status))
            counts = report.get("counts", {})
            st.write({
                "Uložené BUY řádky": counts.get("raw_rows", 0),
                "Příklady se známým výsledkem": report.get("matured_examples", 0),
                "Dny uložených signálů": counts.get("stored_signal_dates", 0),
                "Dny s použitelným následným výsledkem": report.get("signal_dates", 0),
                "Chybějící údaje strategií": counts.get("insufficient_features", 0),
                "Chybějící výsledky benchmarku": counts.get("missing_benchmark_outcomes", 0),
                "Čekající nebo neúplné výsledky": counts.get("pending_or_incomplete_outcomes", 0),
                "Chybějící doložené cenové řady": counts.get("missing_verified_price_paths", 0),
                "Chybějící datované ukazatele výkazů": counts.get("insufficient_statement_metrics", 0),
                "Starší metodika skóre": counts.get("scoring_version_mismatch", 0),
                "Duplicitní analýzy stejného dne": counts.get("duplicate_ticker_days", 0),
            })
            if report.get("cached"):
                st.caption("Historie i nastavení jsou stejné; načetl se výsledek předchozího učení.")
            if report.get("error"):
                st.warning(str(report["error"]))
            if status in {"PRICE_PROVENANCE_MISSING", "NO_MATURED_EXAMPLES",
                          "NOT_ENOUGH_HISTORY", "INSUFFICIENT_TIME_PERIODS",
                          "INSUFFICIENT_TEMPORAL_VALIDATION", "INSUFFICIENT_OUTCOME_WINDOWS"}:
                st.info(
                    "Ukládejte pravidelné BUY analýzy. Starší signály se použijí, až bude "
                    "dostupná doložená upravená cenová řada pokrývající jejich následný vývoj. "
                    "Stovky akcií z jednoho dne nenahrazují dlouhou časovou historii."
                )
            if report.get("folds"):
                fold_table = pd.DataFrame([
                    {key: value for key, value in fold.items() if key != "reliability_bins"}
                    for fold in report["folds"]
                ])
                st.dataframe(fold_table, width="stretch", hide_index=True)
                final_fold = report["folds"][-1]
                if final_fold.get("reliability_bins"):
                    st.caption("Poslední ověřovací období: odhadované a skutečné četnosti výsledků.")
                    st.dataframe(pd.DataFrame(final_fold["reliability_bins"]),
                                 width="stretch", hide_index=True)
            st.download_button(
                "Stáhnout zprávu o učení", json.dumps(report, ensure_ascii=False, indent=2),
                file_name=f"buy_learning_{horizon}_{target}.json", mime="application/json",
                key="buy_learning_v7_report",
            )
        if state.get("save_error"):
            st.warning("Výsledek je dostupný v této relaci, ale uložení do databáze selhalo: "
                       + state["save_error"])
        model = state.get("model")
        if model is not None:
            model_age = pd.Timestamp.now(tz="UTC") - pd.Timestamp(model.trained_at)
            if model_age.days > learning_config.model_max_age_days:
                st.warning("Uložený model je starší než 30 dnů a nové pravděpodobnosti se nezobrazují.")
            st.caption(
                f"Načtený model {model.model_id} · vytvořen {model.trained_at} · "
                f"horizont {model.horizon_sessions} seancí · {targets[model.target]}. "
                f"Poslední ověření: Brier {model.holdout_brier:.4f}, "
                f"základní odhad {model.baseline_brier:.4f}."
            )
            if report and report.get("status") not in {"OK", "READY"}:
                st.caption("Poslední pokus dříve uložený model nenahradil.")
        st.caption(
            "Vstup pro měření výsledku je následující denní závěrečná cena po analýze. "
            "Před každým ověřením se vyřadí dosud neznámé výsledky a přidá časový odstup. "
            "Modelové pravděpodobnosti jsou experimentální. Přijatý aktuální model kladného výnosu se při další analýze zapojí do FinalTotalScore s vahou 5 %. Model překonání SPY zůstává samostatný. Deterministický BUY_SCORE se nemění."
        )
        return model, learning_config



MAX_PREVIEW_ROWS = 500
DEFAULT_NEWS_SOURCES_TEXT = "\n".join(
    [
        "https://news.google.com/rss/search?q={ticker}%20stock&hl=en-US&gl=US&ceid=US:en",
        "https://www.nasdaq.com/feed/rssoutbound",
        "https://www.marketscreener.com/rss/news/",
        "https://www.investing.com/rss/news.rss",
        "https://www.benzinga.com/feed",
    ]
)


def _parse_json_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
        except json.JSONDecodeError:
            return [value]
    return []


def _resolve_sqlite_path(raw_value: str) -> tuple[Path, str | None]:
    """
    Normalize user-provided SQLite path from UI and try to recover common typos.

    Returns:
        tuple[path, info_message]
        info_message is shown to user when path was auto-corrected.
    """
    raw = (raw_value or "").strip().strip('"').strip("'")
    candidate = Path(raw.replace("\\", "/")) if raw else DEFAULT_DB_PATH

    if candidate.suffix.lower() != ".db":
        candidate = candidate.with_suffix(".db")

    if candidate.exists():
        return candidate, None

    fallback = candidate.parent / "market_checker_history.db"
    if candidate.name != "market_checker_history.db" and fallback.exists():
        return fallback, f"DB soubor `{candidate}` nebyl nalezen, používám `{fallback}`."

    return candidate, None




def _load_yahoo_tickers_from_excel(uploaded_file: object) -> tuple[list[str], str | None]:
    if uploaded_file is None:
        return [], None
    try:
        frame = pd.read_excel(uploaded_file)
    except Exception as exc:
        return [], f"Excel se nepodařilo načíst: {exc}"

    if frame.empty:
        return [], "Excel je prázdný."

    normalized = {str(c).strip().lower(): c for c in frame.columns}
    ticker_col = normalized.get('yahoo ticker') or normalized.get('yahoo_ticker') or normalized.get('ticker')
    if ticker_col is None:
        return [], "Excel musí obsahovat sloupec 'Yahoo ticker' (nebo 'ticker')."

    values = frame[ticker_col].dropna().astype(str).str.strip()
    cleaned = [v for v in values.tolist() if v and v.lower() != 'nan']
    return MT5Client.sanitize_watchlist(cleaned), None

def _parse_finished_at_from_excel_name(path: Path) -> pd.Timestamp | None:
    match = re.search(r"market_checker_(\d{8}_\d{6})\.xlsx$", path.name)
    if not match:
        return None
    return pd.to_datetime(match.group(1), format="%Y%m%d_%H%M%S", errors="coerce")


@st.cache_data(show_spinner=False)
def _load_history_from_excels(output_dir_value: str) -> pd.DataFrame:
    output_dir = Path(output_dir_value)
    files = sorted(output_dir.glob("market_checker_*.xlsx"))
    if not files:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    for idx, path in enumerate(files, start=1):
        finished_at = _parse_finished_at_from_excel_name(path)
        if finished_at is None or pd.isna(finished_at):
            continue
        try:
            frame = pd.read_excel(path, sheet_name="Signals")
        except Exception:
            continue
        if frame.empty or "ticker" not in frame.columns:
            continue
        frame = frame.copy()
        frame["run_id"] = idx
        frame["finished_at"] = finished_at
        keep_cols = [
            "run_id",
            "finished_at",
            "ticker",
            "current_price",
            "scoring_version",
            "legacy_total_score",
            "legacy_signal",
            "final_total_score",
            "raw_total_score",
            "news_score",
            "tech_score",
            "yahoo_score",
            "behavioral_score",
            "risk_score",
            "rank_in_watchlist",
            "percentile_in_watchlist",
            "signal",
            "final_confidence",
            "tech_source_used",
            "reasons",
            "warnings",
            "risk_flags",
            "key_drivers",
            "overall_summary",
        ]
        frames.append(frame[[c for c in keep_cols if c in frame.columns]])

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).sort_values(["run_id", "ticker"], ascending=[True, True])


def _render_progress_ui(state: AnalysisProgressState, elapsed_sec: float) -> None:
    st.write(f"**{state.current_message}**")
    if state.current_symbol:
        st.caption(
            f"Ticker {state.current_symbol} • {state.current_position}/{state.total_symbols}"
        )
    st.progress(float(state.overall_progress))
    st.caption(f"{int(state.overall_progress * 100)} % • {elapsed_sec:.1f}s")


def _show_limited_dataframe(df: pd.DataFrame, title: str, preferred_cols: list[str] | None = None, rows: int = MAX_PREVIEW_ROWS) -> None:
    st.subheader(title)
    if df.empty:
        st.info("Data nejsou dostupná.")
        return
    view = df.copy()
    if preferred_cols:
        cols = [c for c in preferred_cols if c in view.columns]
        if cols:
            view = view[cols]
    if len(view) > rows:
        st.warning(f"Zobrazuji prvních {rows} řádků z {len(view)} kvůli výkonu UI.")
        view = view.head(rows)
    st.dataframe(view, width="stretch")


def _total_score_audit(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            pass
    return {}


def _render_total_score_detail(row) -> None:
    audit = _total_score_audit(row.get("total_score_details"))
    if not audit:
        st.info("Tento záznam je ze starší metodiky. Pro zapojení nových dat spusťte analýzu.")
        return
    with st.expander("Co vstoupilo do FinalTotalScore", expanded=True):
        c1, c2 = st.columns(2)
        c1.metric("Skóre před novými vstupy", f"{audit['base_final_total_score']:.2f}")
        c2.metric("FinalTotalScore", f"{audit['final_total_score']:.2f}",
                  delta=f"{audit['score_change']:+.2f}")
        labels = {"momentum": "Ceny: momentum a breakout (B01/B02)",
                  "fundamentals": "Výkazy: kvalita, ocenění, F-score (B03/B04/B06)",
                  "earnings": "Výsledková událost (B05)", "learning": "Ověřený naučený model"}
        rows = []
        for key, label in labels.items():
            item = audit.get(key, {})
            module = "technical" if key == "momentum" else "news"
            weight = (item.get("share_in_module", 0) * audit.get("effective_module_weights", audit.get("module_weights", {})).get(module, 0)
                      if key in {"momentum", "earnings"} else audit.get("effective_module_weights", {}).get("fundamentals", item.get("weight", 0)) if key == "fundamentals" else item.get("weight", 0))
            if key != "learning":
                weight *= 1 - audit.get("learning", {}).get("weight", 0)
            rows.append({"Vstup": label, "Stav": item.get("status"),
                         "Skóre / pravděpodobnost": item.get("score", item.get("probability")),
                         "Váha ve výsledném rozhodování (%)": round(weight * 100, 2),
                         "Pokrytí": item.get("coverage"),
                         "Zdroj / model": item.get("provider", item.get("model_id")),
                         "Důvod nedostupnosti": item.get("statement_status")})
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption(
            "APPLIED = započítáno. Nedostupný vstup nemá záporné body. "
            "Skóre strategií je 0–100; modelová pravděpodobnost 0–1. "
            "Nové vstupy nahrazují část vah; jejich skóre se prostě nesčítají. "
            "Vliv rizika se uplatní následně a existující blokace BUY/SELL zůstávají.")
        st.write(f"RiskScore: {audit.get('original_risk_score', 0):.2f} → "
                 f"{audit.get('effective_risk_score', 0):.2f}")
        st.caption("Rizika z cen: " + (", ".join(audit.get("buy_risk_flags", [])) or "bez nového rizika"))
        if audit.get("statement_data"):
            _render_statement_coverage(audit["statement_data"])
        breakdown = _parse_json_list(row.get("module_breakdown"))
        if breakdown:
            st.dataframe(pd.DataFrame(breakdown), hide_index=True, width="stretch")
        st.caption("Sk\u00f3re = 50 + sou\u010det p\u0159\u00edsp\u011bvk\u016f modul\u016f a ov\u011b\u0159en\u00e9ho modelu; kvalita tlum\u00ed odchylku od 50 a zv\u00fd\u0161en\u00e9 riziko ode\u010d\u00edt\u00e1 body. V\u00e1hy zat\u00edm nejsou statisticky optimalizovan\u00e9.")
        st.json(audit, expanded=False)


def _render_detail_ticker(signals_df: pd.DataFrame, ticker: str) -> None:
    row = signals_df[signals_df["ticker"] == ticker].head(1)
    if row.empty:
        st.info("Detail tickeru není dostupný.")
        return

    _render_total_score_detail(row.iloc[0])

    score_df = VisualizationService.prepare_score_decomposition_df(signals_df, ticker)
    conf_df = VisualizationService.prepare_confidence_decomposition_df(signals_df, ticker)

    col1, col2 = st.columns(2)
    with col1:
        st.altair_chart(
            alt.Chart(score_df)
            .mark_bar()
            .encode(x=alt.X("modul:N", title="Modul"), y=alt.Y("hodnota:Q", title="Skóre"), tooltip=["modul:N", alt.Tooltip("hodnota:Q", format=".2f")])
            .properties(title="Vstupní skóre modulů (před integrací)", height=280),
            width="stretch",
        )
    with col2:
        st.altair_chart(
            alt.Chart(conf_df)
            .mark_bar(color="#1f77b4")
            .encode(x=alt.X("modul:N", title="Modul"), y=alt.Y("hodnota:Q", title="Confidence"), tooltip=["modul:N", alt.Tooltip("hodnota:Q", format=".2f")])
            .properties(title="Rozklad confidence", height=280),
            width="stretch",
        )

    st.markdown("### Shrnutí tickeru")
    st.write(f"**OverallSummary:** {row.iloc[0].get('overall_summary', '')}")
    st.write(f"**RiskScore:** {float(row.iloc[0].get('risk_score', 0)):.2f}")

    for label, key in [("KeyDrivers", "key_drivers"), ("Warnings", "warnings"), ("Reasons", "reasons")]:
        st.markdown(f"**{label}**")
        values = _parse_json_list(row.iloc[0].get(key))
        if not values:
            st.caption("Bez záznamu")
        for item in values:
            st.write(f"- {item}")


def _render_quality_drawdown(details: dict) -> None:
    st.subheader("Kvalita po propadu — pilotní hodnocení")
    st.caption("Samostatný přehled pro horizont 3–12 měsíců. Kandidát není potvrzený BUY. "
               "Cena nemusí být nad EMA200; TotalScore a finální obchodní akce zůstávají samostatné.")
    records = {ticker: payload["quality_drawdown"] for ticker, payload in details.items()
               if isinstance(payload.get("quality_drawdown"), dict)}
    if not records:
        st.info("Tento běh ještě nové hodnocení neobsahuje. Doplňte cenová data a výkazy a spusťte novou analýzu. "
                "Staré výsledky se zpětně nepřepisují.")
        return
    statuses = {"CANDIDATE_REVIEW": "Kandidát — ověřit příčinu propadu",
                "PARTIAL_CANDIDATE": "Částečný kandidát — doplnit kritické údaje",
                "PARTIAL_DATA": "Částečně vyhodnoceno",
                "NOT_APPLICABLE": "Sektor zatím nepodporován",
                "WATCHLIST": "Sledovat", "RISK_REVIEW": "Prověřit riziko",
                "INSUFFICIENT_DATA": "Nelze posoudit — chybí data",
                "PRICE_REVIEW": "Prověřit ceny", "OUTSIDE_DRAWDOWN": "Mimo propad alespoň 15 %"}
    timing = {"UNKNOWN": "Nelze posoudit", "STABILIZING": "Známky stabilizace",
              "HIGH_VOLATILITY": "Vysoká volatilita", "WAITING_FOR_STABILIZATION": "Čeká na stabilizaci"}
    rows = []
    for ticker, item in records.items():
        rows.append({"ticker": ticker, "stav": statuses.get(item["status"], item["status"]),
                     "atraktivita_financí": item.get("attractiveness_score"),
                     "skóre_s_ohledem_na_pokrytí": item.get("coverage_adjusted_score") if item.get("version") == "quality_drawdown_v3_attractiveness" else None,
                     "pokrytí_celkové_%": round(item.get("coverage", 0)*100, 1),
                     "pokrytí_financí_%": round(item["financial_coverage"]*100, 1) if item.get("financial_coverage") is not None else None,
                     "nevyhodnocená_váha_%": round((1-item.get("coverage", 0))*100, 1),
                     "chybí": "; ".join(f"{group}: {', '.join(names)}" for group, names in item.get("missing_inputs", {}).items() if names),
                     "kritické_neznámé": "; ".join(item.get("critical_missing", [])),
                     "metodika": item.get("version"),
                     "propad_od_252_max_%": item.get("drawdown_pct"),
                     "změna_5_seancí_%": item.get("returns", {}).get("5"),
                     "změna_21_seancí_%": item.get("returns", {}).get("21"),
                     "načasování": timing.get(item.get("timing"), item.get("timing")),
                     "kontrola_cen": item.get("price_status"), "ceny_k": item.get("price_as_of"),
                     "výkazy_k": item.get("statement_period_end"),
                     "rizika": "; ".join(item.get("risk_flags", []))})
    table = pd.DataFrame(rows)
    c1, c2, c3 = st.columns(3)
    c1.metric("Kandidáti včetně částečných", sum(v["status"] in {"CANDIDATE_REVIEW", "PARTIAL_CANDIDATE"} for v in records.values()))
    c2.metric("Nelze posoudit", sum(v["status"] == "INSUFFICIENT_DATA" for v in records.values()))
    c3.metric("Ceny k prověření", sum(v.get("price_status") != "ADJUSTED_SERIES" for v in records.values()))
    st.caption("Atraktivita hodnotí dostupné finanční ukazatele; chybějící váha se přerozdělí jen uvnitř stejné složky. "
               "Zdraví, ocenění i vývoj podnikání musí mít dostatek dat; příčina propadu se posuzuje odděleně. "
               "Celkové pokrytí zahrnuje 15 % zatím nevyhodnocené příčiny propadu. "
               "Skóre s ohledem na pokrytí používá původní pevné váhy a střed 50. "
               "Jde o neověřenou pilotní metodiku, nikoli pravděpodobnost výnosu.")
    if any(v.get("version") != "quality_drawdown_v3_attractiveness" for v in records.values()):
        st.info("Zobrazený běh používá starší metodiku. Pro novou atraktivitu spusťte novou analýzu; uložená historie se nepřepisuje.")
    choice = st.selectbox("Výběr příležitostí po propadu", ["Všechny stavy"] + sorted(table["stav"].unique()),
                          key="quality_drawdown_filter")
    visible = table if choice == "Všechny stavy" else table[table["stav"] == choice]
    visible = visible.sort_values("atraktivita_financí", ascending=False, na_position="last")
    st.dataframe(visible, hide_index=True, width="stretch")
    st.download_button("Stáhnout přehled kvality po propadu", table.to_csv(index=False).encode("utf-8-sig"),
                       file_name="quality_drawdown.csv", mime="text/csv", key="quality_drawdown_csv")
    with st.expander("Rozpis hodnocení, zdroje a chybějící vstupy"):
        ticker = st.selectbox("Firma", sorted(records), key="quality_drawdown_detail")
        item = records[ticker]
        st.write(statuses.get(item["status"], item["status"]))
        audit_rows = []
        for group, component in item.get("components", {}).items():
            for indicator, audit in component.get("item_audit", {}).items():
                audit_rows.append({"složka": group, "ukazatel": indicator,
                    "body_0_100": audit.get("score"), "stav": audit.get("status"),
                    "váha_uvnitř_složky_%": round(audit["weight_in_group"]*100, 2),
                    "maximální_váha_%": round(audit["maximum_weight"]*100, 2),
                    "využitá_váha_%": round(audit["effective_weight"]*100, 2),
                    "příspěvek_do_konzervativního_skóre": round(audit["score_contribution"], 3),
                    "přepočtená_váha_ve_složce_%": round(audit.get("normalized_weight_in_group", 0)*100, 2),
                    "váha_v_atraktivitě_%": round(audit["attractiveness_weight"]*100, 2) if audit.get("attractiveness_weight") is not None else None,
                    "příspěvek_do_atraktivity": round(audit["attractiveness_contribution"], 3) if audit.get("attractiveness_contribution") is not None else None})
        if audit_rows:
            st.dataframe(pd.DataFrame(audit_rows), hide_index=True, width="stretch")
        for reason in item.get("reasons", []):
            st.write("• " + reason)
        st.json(item)


def _render_dashboard(signals_df: pd.DataFrame, ranking_tables: dict[str, pd.DataFrame], dashboard_tables: dict[str, pd.DataFrame], buy_details: dict | None = None) -> None:
    if signals_df.empty:
        st.info("Dashboard zatím nemá data. Spusťte analýzu.")
        return

    st.markdown("## Dashboard")
    if "total_score_details" not in signals_df or not signals_df["total_score_details"].map(_total_score_audit).map(bool).any():
        st.info("Zobrazený výsledek používá starší metodiku. Spusťte analýzu pro nový FinalTotalScore.")
    else:
        st.caption("FinalTotalScore zahrnuje dostupné BUY strategie, výkazy a ověřený model. "
                   "Stejné skóre používá pořadí, historie i export. "
                   "Stažení dat nebo změna modelu se projeví při další analýze.")
        with st.expander("Vliv nových vstupů na hlavní skóre", expanded=False):
            columns = ["ticker", "base_final_total_score", "new_evidence_score_change",
                       "final_total_score", "fundamental_score", "fundamental_weight",
                       "learned_probability", "learning_status", "learning_weight"]
            st.dataframe(signals_df[[c for c in columns if c in signals_df]], hide_index=True, width="stretch")
            st.caption("new_evidence_score_change = rozdíl bodů v této analýze; "
                       "váhy jsou v rozsahu 0–1. Podrobnosti a důvody najdete v detailu tickeru.")

    _render_quality_drawdown(buy_details or {})

    kpi = VisualizationService.prepare_kpi(signals_df)
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Počet tickerů", kpi["tickers"])
    c2.metric("Průměrný FinalTotalScore", f"{kpi['avg_score']:.2f}")
    c3.metric("Průměrný FinalConfidence", f"{kpi['avg_confidence']:.2f}")
    c4.metric("Průměrný RiskScore", f"{kpi['avg_risk']:.2f}")
    c5.metric("Akce BUY", kpi["buy_count"])
    c6.metric("Akce SELL", kpi["sell_count"])

    st.markdown("### Diagnostika rozhodovacího enginu")
    bull_series = pd.to_numeric(signals_df.get("bull_score", pd.Series(dtype=float)), errors="coerce")
    bear_series = pd.to_numeric(signals_df.get("bear_score", pd.Series(dtype=float)), errors="coerce")
    spread_series = pd.to_numeric(signals_df.get("bull_bear_spread", pd.Series(dtype=float)), errors="coerce")
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Bull score min/max", f"{bull_series.min():.1f} / {bull_series.max():.1f}" if not bull_series.dropna().empty else "n/a")
    d2.metric("Bear score min/max", f"{bear_series.min():.1f} / {bear_series.max():.1f}" if not bear_series.dropna().empty else "n/a")
    d3.metric("Spread min/max", f"{spread_series.min():.1f} / {spread_series.max():.1f}" if not spread_series.dropna().empty else "n/a")
    d4.metric("Signal downgrady", int(pd.to_numeric(signals_df.get("downgrade_count", pd.Series(dtype=float)), errors="coerce").fillna(0).sum()))

    app_cfg = AppConfig()
    scenario_rows = validate_decision_scenarios(app_cfg.decision_weights, app_cfg.decision_thresholds)
    scenario_df = pd.DataFrame(scenario_rows)
    st.dataframe(scenario_df, width="stretch")

    blocked_series = signals_df.get("blocked_reasons")
    if blocked_series is not None:
        blocked_items: list[str] = []
        for value in blocked_series.dropna().tolist():
            blocked_items.extend(_parse_json_list(value))
        if blocked_items:
            blocked_df = pd.Series(blocked_items).value_counts().reset_index()
            blocked_df.columns = ["důvod_blokace", "count"]
            st.dataframe(blocked_df, width="stretch")

    st.markdown("### Kalibrace HOLD (analýza, bez změny produkčních thresholdů)")
    audits = [_total_score_audit(v) for v in signals_df.get("total_score_details", pd.Series(dtype=object))]
    if audits:
        applied_fundamentals = sum(a.get("fundamentals", {}).get("status") == "APPLIED" for a in audits)
        applied_learning = sum(a.get("learning", {}).get("status") == "APPLIED" for a in audits)
        st.caption(
            f"Pokrytí uloženého TotalScore: fundamenty zapojeny u {applied_fundamentals}/{len(signals_df)} firem, "
            f"ověřený model učení u {applied_learning}/{len(signals_df)}. "
            "Chybějící vstupy nejsou negativní signál."
        )
    calibration = VisualizationService.prepare_hold_calibration(
        signals_df, decision_weights=app_cfg.decision_weights,
        decision_thresholds=app_cfg.decision_thresholds,
    )
    st.caption("HOLD je mezivýsledek enginu. Finální akce BUY / SELL / NO_TRADE zahrnuje také rizikové kontroly.")
    hold_diag_df = calibration["hold_diagnostics"]
    hold_concentration_df = calibration["hold_concentration"]
    sensitivity_df = calibration["sensitivity_distribution"]
    confidence_sanity = calibration["confidence_sanity"]
    tech_effectiveness = calibration["technical_driver_effectiveness"]

    if hold_diag_df.empty:
        st.info("HOLD diagnostika není dostupná.")
    else:
        st.caption("Top HOLD tickery (bull/bear spread, confidence, primary driver, směry modulů, blokace).")
        st.dataframe(hold_diag_df.head(25), width="stretch")

    c_hold1, c_hold2, c_hold3 = st.columns(3)
    c_hold1.metric("HOLD count", int(confidence_sanity.get("hold_count", 0)))
    c_hold2.metric("High-confidence HOLD", int(confidence_sanity.get("high_conf_hold_count", 0)))
    c_hold3.metric("High-confidence HOLD ratio", f"{float(confidence_sanity.get('high_conf_hold_ratio', 0.0)):.2%}")
    st.caption(str(confidence_sanity.get("explanation", "")))

    cc1, cc2 = st.columns(2)
    with cc1:
        st.subheader("HOLD concentration podle primární příčiny")
        st.dataframe(hold_concentration_df, width="stretch")
    with cc2:
        st.subheader("Sensitivity simulace hold-band")
        st.caption(
            f"Simulace mezivýsledku z uložených integrovaných modulů: "
            f"{calibration.get('sensitivity_eligible_count', 0)} záznamů; "
            f"{calibration.get('sensitivity_skipped_count', 0)} bez platného auditu vynecháno. "
            "Používá aktuální nastavení hranic; nepřepočítává finální obchodní akci."
        )
        if sensitivity_df.empty:
            st.info("Sensitivity simulace není dostupná.")
        else:
            st.altair_chart(
                alt.Chart(sensitivity_df)
                .mark_bar()
                .encode(
                    x=alt.X("scenario:N", title="Simulace"),
                    y=alt.Y("count:Q", title="Počet"),
                    color=alt.Color("signal:N", title="Signál"),
                    tooltip=["scenario:N", "signal:N", "count:Q"],
                )
                .properties(height=280),
                width="stretch",
            )
            pivot = sensitivity_df.pivot(index="scenario", columns="signal", values="count").fillna(0).reset_index()
            st.dataframe(pivot, width="stretch")

    st.subheader("Silný technický modul u HOLD")
    st.metric(
        "HOLD se silným technickým modulem",
        f"{int(tech_effectiveness.get('strong_technical_hold_count', 0))} / {int(tech_effectiveness.get('hold_count', 0))}",
    )
    st.caption(f"Podíl: {float(tech_effectiveness.get('strong_technical_hold_ratio', 0.0)):.2%}")
    examples_df = tech_effectiveness.get("examples", pd.DataFrame())
    if isinstance(examples_df, pd.DataFrame) and not examples_df.empty:
        st.dataframe(examples_df.head(25), width="stretch")
    else:
        st.caption("Nenalezeny výrazné technické stavy, které by končily HOLD.")

    signals = sorted(signals_df["signal"].dropna().unique().tolist()) if "signal" in signals_df.columns else []
    filter_col1, filter_col2, filter_col3 = st.columns(3)
    with filter_col1:
        selected_signals = st.multiselect("Filtr signálu", options=signals, default=signals)
    with filter_col2:
        confidence_range = st.slider("Rozsah confidence", 0, 100, (0, 100))
    with filter_col3:
        risk_range = st.slider("Rozsah risk", 0, 100, (0, 100))

    filtered = signals_df.copy()
    if selected_signals:
        filtered = filtered[filtered["signal"].isin(selected_signals)]
    filtered = filtered[(pd.to_numeric(filtered["final_confidence"], errors="coerce").between(confidence_range[0], confidence_range[1])) & (pd.to_numeric(filtered["risk_score"], errors="coerce").between(risk_range[0], risk_range[1]))]

    signal_df = VisualizationService.prepare_signal_distribution_df(filtered)
    score_series = pd.to_numeric(filtered.get("final_total_score", pd.Series(dtype=float)), errors="coerce").dropna()
    if not score_series.empty:
        st.caption(
            f"FinalTotalScore ve filtru: {score_series.min():.2f} až {score_series.max():.2f}. "
            "STRONG BUY / STRONG SELL určuje bull/bear engine podle převahy modulů, confidence a blokací; "
            "samotný rozsah TotalScore jejich dosažitelnost neurčuje."
        )
    decision_series = filtered.get("decision_signal", filtered.get("signal", pd.Series(dtype=str)))
    st.caption(
        f"Mezivýsledek enginu ve stejném filtru: STRONG BUY={int(decision_series.eq('STRONG BUY').sum())}, "
        f"STRONG SELL={int(decision_series.eq('STRONG SELL').sum())}. "
        "Graf distribuce níže ukazuje finální akce po rizikových kontrolách."
    )

    score_hist = VisualizationService.prepare_histogram_df(filtered, "final_total_score")
    conf_hist = VisualizationService.prepare_histogram_df(filtered, "final_confidence")
    risk_hist = VisualizationService.prepare_histogram_df(filtered, "risk_score")
    scatter_df = VisualizationService.prepare_scatter_df(filtered)
    top10, bottom10 = VisualizationService.prepare_top_bottom_df(filtered, "final_total_score", n=10)

    col1, col2 = st.columns(2)
    with col1:
        st.altair_chart(signal_bar_chart(signal_df, "Distribuce signálů"), width="stretch")
    with col2:
        st.altair_chart(histogram_chart(score_hist, "Rozložení FinalTotalScore", "Bucket skóre"), width="stretch")

    col3, col4 = st.columns(2)
    with col3:
        st.altair_chart(histogram_chart(conf_hist, "Rozložení FinalConfidence", "Bucket confidence"), width="stretch")
    with col4:
        st.altair_chart(histogram_chart(risk_hist, "Rozložení RiskScore", "Bucket risk"), width="stretch")

    st.altair_chart(scatter_score_confidence(scatter_df, "Confidence vs Score (tooltip + velikost dle MarketCap)"), width="stretch")

    ctop, cbottom = st.columns(2)
    with ctop:
        st.altair_chart(top_bottom_bar_chart(top10, "final_total_score", "Top 10 tickerů podle FinalTotalScore", positive_color="#2ca02c"), width="stretch")
        st.dataframe(top10, width="stretch")
    with cbottom:
        st.altair_chart(top_bottom_bar_chart(bottom10, "final_total_score", "Bottom 10 tickerů podle FinalTotalScore", positive_color="#2ca02c", negative_color="#d62728"), width="stretch")
        st.dataframe(bottom10, width="stretch")

    overlap = VisualizationService.prepare_drop_overlap_tables(dashboard_tables)
    shared = overlap.get("shared_drop_tickers", pd.DataFrame())
    st.subheader("Stejné tickery napříč propady")
    if shared.empty:
        st.info("Žádný ticker se neopakuje napříč 7D/14D/1M/3M propady.")
    else:
        st.dataframe(shared, width="stretch")

    with st.expander("Top/Bottom rank overview", expanded=False):
        st.dataframe(ranking_tables.get("top", pd.DataFrame()).head(20), width="stretch")
        st.dataframe(ranking_tables.get("bottom", pd.DataFrame()).head(20), width="stretch")


def _render_delta(delta_df: pd.DataFrame) -> None:
    st.markdown("## Delta vůči předchozímu běhu")
    if delta_df.empty:
        st.info("Delta není dostupná, protože chybí předchozí běh.")
        return

    if "ScoreComparable" in delta_df and not delta_df["ScoreComparable"].all():
        st.info("Metodika skóre se mezi běhy liší nebo není doložena. "
                "Tyto rozdíly nejsou vydávány za zlepšení či propad akcie.")
        st.dataframe(delta_df, width="stretch")
        delta_df = delta_df.loc[delta_df["ScoreComparable"]]
        if delta_df.empty:
            return
    improvements, declines = VisualizationService.prepare_delta_top_movers_df(delta_df, n=10)
    transitions = VisualizationService.prepare_signal_transition_df(delta_df)
    comp_delta = VisualizationService.prepare_component_delta_df(delta_df, n=12)

    col1, col2 = st.columns(2)
    with col1:
        st.altair_chart(top_bottom_bar_chart(improvements, "DeltaTotal", "Top 10 zlepšení FinalTotalScore", positive_color="#2ca02c"), width="stretch")
        st.dataframe(improvements.head(10), width="stretch")
    with col2:
        st.altair_chart(top_bottom_bar_chart(declines, "DeltaTotal", "Top 10 propadů FinalTotalScore", positive_color="#2ca02c", negative_color="#d62728"), width="stretch")
        st.dataframe(declines.head(10), width="stretch")

    st.subheader("Přechody signálů")
    if transitions.empty:
        st.info("Přechody signálů nejsou dostupné.")
    else:
        st.altair_chart(
            alt.Chart(transitions.head(20))
            .mark_bar()
            .encode(
                y=alt.Y("SignalChange:N", sort="-x", title="Přechod"),
                x=alt.X("count:Q", title="Počet tickerů"),
                tooltip=["SignalChange:N", "count:Q"],
            )
            .properties(height=360, title="Nejčastější přechody signálů"),
            width="stretch",
        )
        st.dataframe(transitions, width="stretch")

    st.subheader("Delta komponent pro největší movery")
    if comp_delta.empty:
        st.info("Component delta není dostupná pro aktuální data.")
    else:
        st.altair_chart(
            alt.Chart(comp_delta)
            .mark_bar()
            .encode(
                x=alt.X("ticker:N", title="Ticker"),
                y=alt.Y("delta:Q", title="Delta"),
                color=alt.Color("component:N", title="Komponenta"),
                tooltip=["ticker:N", "component:N", alt.Tooltip("delta:Q", format=".2f")],
            )
            .properties(height=360, title="Z čeho se skládá změna skóre (top movers)"),
            width="stretch",
        )

    st.subheader("Detailní delta tabulka (side-by-side)")
    mode = st.radio(
        "Zobrazení",
        options=["Vše", "Jen propady (DeltaTotal < 0)"],
        horizontal=True,
    )
    preferred_cols = [
        "ticker",
        "market_cap_usd_prev",
        "market_cap_usd",
        "DeltaMarketCap",
        "final_total_score_prev",
        "final_total_score",
        "DeltaTotal",
        "rank_in_watchlist_prev",
        "rank_in_watchlist",
        "DeltaRank",
        "final_confidence_prev",
        "final_confidence",
        "DeltaConfidence",
        "signal_prev",
        "signal",
        "SignalChange",
        "DeltaNews",
        "DeltaTech",
        "DeltaYahoo",
        "DeltaBehavioral",
        "DeltaRisk",
    ]
    detail_cols = [c for c in preferred_cols if c in delta_df.columns]
    detail = delta_df[detail_cols].copy() if detail_cols else delta_df.copy()
    if mode.startswith("Jen propady") and "DeltaTotal" in detail.columns:
        detail = detail[detail["DeltaTotal"] < 0]
    if "DeltaTotal" in detail.columns:
        detail = detail.sort_values("DeltaTotal", ascending=True)
    st.caption("Pozn.: DeltaRank > 0 = zlepšení pořadí (nižší rank je lepší).")
    delta_cols = [c for c in ["DeltaTotal", "DeltaRank", "DeltaConfidence", "DeltaNews", "DeltaTech", "DeltaYahoo", "DeltaBehavioral", "DeltaRisk", "DeltaMarketCap"] if c in detail.columns]
    styled = (
        detail.head(500)
        .style.format(
            {
                "DeltaTotal": "{:+.2f}",
                "DeltaRank": "{:+.0f}",
                "DeltaConfidence": "{:+.2f}",
                "DeltaNews": "{:+.2f}",
                "DeltaTech": "{:+.2f}",
                "DeltaYahoo": "{:+.2f}",
                "DeltaBehavioral": "{:+.2f}",
                "DeltaRisk": "{:+.2f}",
                "DeltaMarketCap": "{:+,.0f}",
                "market_cap_usd_prev": "{:,.0f}",
                "market_cap_usd": "{:,.0f}",
            },
            na_rep="-",
        )
        .map(lambda v: "background-color: rgba(40,167,69,0.25)" if isinstance(v, (int, float)) and v > 0 else ("background-color: rgba(220,53,69,0.25)" if isinstance(v, (int, float)) and v < 0 else ""), subset=delta_cols)
    )
    st.dataframe(styled, width="stretch")


def _render_trends(history_service: HistoryService, output_dir: Path) -> None:
    st.markdown("## Trends napříč běhy")
    global_history = history_service.store.read_global_history()
    if global_history["run_id"].nunique() < 2 if not global_history.empty else True:
        excel_history = _load_history_from_excels(str(output_dir))
        if excel_history["run_id"].nunique() >= 2:
            global_history = excel_history
            st.info("SQLite zatím nemá dost běhů, trendy načítám z historických Excel exportů v outputs.")
    trend = VisualizationService.prepare_trend_history_df(global_history)

    if trend["avg_scores"].empty:
        st.info("Zatím není dost historických běhů pro graf.")
        return

    avg_scores = trend["avg_scores"]
    col1, col2, col3 = st.columns(3)
    with col1:
        st.altair_chart(line_chart(avg_scores, "finished_at", "avg_final_total_score", "Průměrný FinalTotalScore v čase"), width="stretch")
    with col2:
        st.altair_chart(line_chart(avg_scores, "finished_at", "avg_final_confidence", "Průměrný FinalConfidence v čase"), width="stretch")
    with col3:
        st.altair_chart(line_chart(avg_scores, "finished_at", "avg_risk_score", "Průměrný RiskScore v čase"), width="stretch")

    signal_counts = trend["signal_counts"]
    if not signal_counts.empty:
        st.altair_chart(
            alt.Chart(signal_counts)
            .mark_bar()
            .encode(
                x=alt.X("finished_at:T", title="Běh"),
                y=alt.Y("count:Q", title="Počet tickerů"),
                color=alt.Color("signal:N", title="Signál"),
                tooltip=["signal:N", "count:Q", "finished_at:T"],
            )
            .properties(height=320, title="Vývoj počtu signálů v čase"),
            width="stretch",
        )

    module_scores = trend["module_scores"]
    if not module_scores.empty:
        melt_cols = [c for c in module_scores.columns if c.startswith("avg_")]
        melted = module_scores.melt(id_vars=["finished_at"], value_vars=melt_cols, var_name="module", value_name="score")
        st.altair_chart(multi_line_chart(melted, "Průměrná skóre modulů v čase"), width="stretch")

    bucket_behavior = trend["bucket_behavior"]
    if not bucket_behavior.empty:
        st.altair_chart(
            alt.Chart(bucket_behavior)
            .mark_line(point=True)
            .encode(
                x=alt.X("finished_at:T", title="Běh"),
                y=alt.Y("final_total_score:Q", title="Průměrný FinalTotalScore"),
                color=alt.Color("bucket:N", title="Bucket"),
                tooltip=["bucket:N", alt.Tooltip("final_total_score:Q", format=".2f"), "finished_at:T"],
            )
            .properties(height=300, title="Top 20 % vs Bottom 20 % v čase"),
            width="stretch",
        )


def _render_history(history_service: HistoryService, output_dir: Path) -> None:
    st.markdown("## History tickeru")
    source_df = history_service.store.read_global_history()
    if source_df.empty:
        source_df = _load_history_from_excels(str(output_dir))
        if not source_df.empty:
            st.info("SQLite historie je prázdná, historii tickeru načítám z Excel exportů v outputs.")

    tickers = sorted(source_df["ticker"].dropna().astype(str).unique().tolist()) if not source_df.empty and "ticker" in source_df.columns else []
    if not tickers:
        st.info("Pro vybraný ticker zatím není dostatek historických dat.")
        return

    ticker = st.selectbox("Vyber ticker pro historii", tickers)
    hist = source_df[source_df["ticker"] == ticker].copy()
    prepared = VisualizationService.prepare_ticker_history_df(hist)

    if prepared["series"].empty:
        st.info("Pro vybraný ticker zatím není dostatek historických dat.")
        return

    series = prepared["series"]
    col1, col2, col3 = st.columns(3)
    with col1:
        st.altair_chart(line_chart(series, "finished_at", "final_total_score", "FinalTotalScore v čase"), width="stretch")
    with col2:
        st.altair_chart(line_chart(series, "finished_at", "final_confidence", "FinalConfidence v čase"), width="stretch")
    with col3:
        st.altair_chart(line_chart(series, "finished_at", "risk_score", "RiskScore v čase"), width="stretch")

    col4, col5 = st.columns(2)
    with col4:
        if "rank_in_watchlist" in series.columns:
            st.altair_chart(line_chart(series, "finished_at", "rank_in_watchlist", "Rank v čase (nižší je lepší)"), width="stretch")
    with col5:
        if "percentile_in_watchlist" in series.columns:
            st.altair_chart(line_chart(series, "finished_at", "percentile_in_watchlist", "Percentil v čase"), width="stretch")

    module_series = prepared["module_series"]
    if not module_series.empty:
        st.altair_chart(multi_line_chart(module_series, "Skóre modulů v čase"), width="stretch")

    st.subheader("Signálová historie")
    st.dataframe(prepared["table"], width="stretch")

    st.subheader("Poslední běhy tickeru (detail tabulka)")
    st.dataframe(series.sort_values("finished_at", ascending=False).head(20), width="stretch")

    snap = prepared["last_snapshot"]
    if not snap.empty:
        row = snap.iloc[0]
        _render_total_score_detail(row)
        st.markdown("### Poslední snapshot")
        st.write(f"**OverallSummary:** {row.get('overall_summary', '')}")
        for label, key in [("KeyDrivers", "key_drivers"), ("Warnings", "warnings"), ("Reasons", "reasons")]:
            st.markdown(f"**{label}**")
            values = _parse_json_list(row.get(key))
            if not values:
                st.caption("Bez záznamu")
            for item in values:
                st.write(f"- {item}")


def _render_signals(signals_df: pd.DataFrame) -> None:
    action_column = "action" if "action" in signals_df.columns else "signal"
    action_options = sorted(signals_df[action_column].dropna().unique())
    signal_filter = st.multiselect("Action filter", options=action_options, default=action_options)
    regime_filter = st.multiselect("Regime filter", options=sorted(signals_df["regime"].dropna().unique()), default=sorted(signals_df["regime"].dropna().unique()))
    min_conf = st.slider("Min confidence", 0, 100, 0)
    max_risk = st.slider("Max risk", 0, 100, 100)
    filtered = signals_df[(signals_df[action_column].isin(signal_filter)) & (signals_df["regime"].isin(regime_filter)) & (pd.to_numeric(signals_df["final_confidence"], errors="coerce") >= min_conf) & (pd.to_numeric(signals_df["risk_score"], errors="coerce") <= max_risk)]

    display_columns = [
        "ticker",
        "action",
        "forecast",
        "decision_signal",
        "action_reasons",
        "yahoo_ticker",
        "yahoo_data_status",
        "news_score",
        "tech_score",
        "yahoo_score",
        "behavioral_score",
        "risk_score",
        "bull_score",
        "bear_score",
        "bull_bear_spread",
        "raw_total_score",
        "quality_adjusted_score",
        "risk_adjusted_score",
        "final_total_score",
        "base_final_total_score",
        "new_evidence_score_change",
        "fundamental_score",
        "fundamental_weight",
        "learning_status",
        "learned_probability",
        "learning_weight",
        "final_confidence",
        "data_quality_score",
        "signal",
        "signal_strength",
        "tech_source_used",
        "rank_in_watchlist",
        "percentile_in_watchlist",
        "regime",
    ]
    st.dataframe(filtered[[c for c in display_columns if c in filtered.columns]], width="stretch")

    ticker = st.selectbox("Detail tickeru", options=signals_df["ticker"].tolist())
    _render_detail_ticker(signals_df, ticker)


st.set_page_config(page_title="Market Checker", layout="wide")
st.title("Market Checker")

for key, default in {
    "watchlist": [],
    "watchlist_text": "",
    "excel_watchlist": [],
    "last_result": None,
    "analysis_progress": None,
    "mt5_loaded_count": None,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

with st.sidebar:
    output_dir = Path(st.text_input("Output directory", str(DEFAULT_OUTPUT_DIR)))
    marketcap_file = st.text_input("MarketCap file", "")
    export_excel = st.checkbox("Export do Excelu", value=True)
    compare_prev = st.checkbox("Porovnat s předchozím během", value=True)
    save_history = st.checkbox("Ukládat historii do SQLite", value=True)
    sqlite_raw_input = st.text_input("DB soubor", str(DEFAULT_DB_PATH))
    max_rss = st.number_input("Max RSS items per source", min_value=1, max_value=200, value=30)
    use_rss = st.checkbox("Použít RSS zprávy", value=True)
    use_mt5 = st.checkbox("Použít MT5 pro watchlist a technická data", value=False)
    load_watchlist = st.button("Načíst watchlist z MT5", disabled=not use_mt5)
    st.metric("Tickery načtené z MT5", st.session_state.mt5_loaded_count if st.session_state.mt5_loaded_count is not None else 0)
    yahoo_batch_size = st.number_input(
        "Yahoo tickerů v jedné automatické dávce",
        min_value=1,
        max_value=1000,
        value=100,
        help=(
            "Jedno kliknutí automaticky spustí další dávky, dokud nejsou zpracované všechny "
            "aktuálně dostupné tickery nebo Yahoo nezapne ochranný rate limit."
        ),
    )
    yahoo_delay_ms = st.number_input(
        "Pauza mezi Yahoo požadavky (ms)",
        min_value=0,
        max_value=5000,
        value=750,
        step=250,
    )
    refresh_yahoo = st.button("Doplnit Yahoo cache")
    run_analysis = st.button("Spustit analýzu", type="primary")

sqlite_path, sqlite_info = _resolve_sqlite_path(sqlite_raw_input)

config = AppConfig(output_dir=output_dir, marketcap_file=marketcap_file, export_excel=export_excel, compare_previous_run=compare_prev, save_history=save_history, sqlite_path=sqlite_path, max_rss_items_per_source=int(max_rss))
config.ensure_output_dir()
store = SQLiteStore(config.sqlite_path)
yahoo_cache = YahooCacheStore(config.sqlite_path)

if sqlite_info:
    st.warning(sqlite_info)
st.caption(f"Aktivní DB: `{config.sqlite_path}`")
learned_model, learning_config = _render_buy_learning(config.sqlite_path)

if load_watchlist:
    loaded_watchlist, mt5_error = MT5Client().load_watchlist()
    if mt5_error:
        st.error(mt5_error)
        st.session_state.mt5_loaded_count = 0
    else:
        st.session_state.watchlist = loaded_watchlist
        st.session_state.watchlist_text = "\n".join(loaded_watchlist)
        st.session_state.mt5_loaded_count = len(loaded_watchlist)
        st.success(f"Z MT5 načteno {len(loaded_watchlist)} tickerů.")

uploaded_excel = st.file_uploader("Excel s Yahoo tickery (XLSX)", type=["xlsx"])
if uploaded_excel is not None:
    excel_watchlist, excel_err = _load_yahoo_tickers_from_excel(uploaded_excel)
    if excel_err:
        st.error(excel_err)
        st.session_state.excel_watchlist = []
    else:
        st.session_state.excel_watchlist = excel_watchlist
        st.success(f"Načteno z Excelu: {len(excel_watchlist)} Yahoo tickerů")
else:
    st.session_state.excel_watchlist = []

watchlist_text = st.text_area("Ruční watchlist (jeden ticker na řádek)", height=130, key="watchlist_text")
mt5_watchlist = MT5Client.sanitize_watchlist(watchlist_text.splitlines())
excel_watchlist = MT5Client.sanitize_watchlist(st.session_state.excel_watchlist)
excel_mode = len(excel_watchlist) > 0

if excel_mode:
    watchlist = excel_watchlist
    yahoo_only_tickers = set(excel_watchlist) if not use_mt5 else set()
    active_sources = ["Yahoo"]
    if use_rss:
        active_sources.append("RSS")
    if use_mt5:
        active_sources.append("MT5 technika")
    st.info(f"Excel režim aktivní. Zdroje: {', '.join(active_sources)}.")
else:
    watchlist = mt5_watchlist
    yahoo_only_tickers = set()

if st.session_state.mt5_loaded_count is not None:
    st.info(f"Načteno z MT5: {st.session_state.mt5_loaded_count} tickerů")
else:
    st.info("Načteno z MT5: 0 tickerů")

st.write(f"**Aktuálně ve watchlistu:** {len(watchlist)} tickerů (Excel/Yahoo-only: {len(excel_watchlist)})")


_render_buy_price_cache(yahoo_cache, watchlist)
_render_financial_statements(config.sqlite_path, watchlist)


def _render_yahoo_coverage(coverage: YahooCacheCoverage) -> None:
    if coverage.total == 0:
        st.caption("Yahoo cache: watchlist je prázdný")
        return
    st.write(
        f"**Yahoo cache:** {coverage.usable}/{coverage.total} použitelných "
        f"(fresh {coverage.fresh}, stale {coverage.stale}, failed {coverage.failed}, "
        f"pending {coverage.missing + coverage.corrupt}, unsupported {coverage.unsupported})"
    )
    st.progress(coverage.usable / coverage.total)


yahoo_coverage_placeholder = st.empty()
with yahoo_coverage_placeholder.container():
    _render_yahoo_coverage(yahoo_cache.coverage(watchlist))

if refresh_yahoo:
    if not watchlist:
        st.error("Nejdřív načtěte nebo zadejte watchlist.")
    else:
        yahoo_refresh_status = st.empty()
        yahoo_refresh_progress = st.progress(0.0)

        def _on_yahoo_refresh(
            completed: int,
            total_candidates: int,
            ticker: str,
            status: str,
            coverage: YahooCacheCoverage,
        ) -> None:
            yahoo_refresh_status.write(
                f"Yahoo metadata: {completed}/{total_candidates} • {ticker} • {status} • "
                f"celkové pokrytí {coverage.usable}/{coverage.total}"
            )
            yahoo_refresh_progress.progress(completed / max(1, total_candidates))

        try:
            refresh_result = YahooEnrichmentService(yahoo_cache).refresh_all(
                watchlist,
                batch_size=int(yahoo_batch_size),
                delay_seconds=float(yahoo_delay_ms) / 1000.0,
                progress_callback=_on_yahoo_refresh,
            )
        except Exception as exc:
            st.error(f"Doplnění Yahoo cache selhalo: {exc}")
            refresh_result = None
        if refresh_result is None:
            st.stop()
        yahoo_refresh_progress.progress(
            min(1.0, refresh_result.attempted / max(1, refresh_result.candidates))
            if refresh_result.rate_limited
            else 1.0
        )
        with yahoo_coverage_placeholder.container():
            _render_yahoo_coverage(refresh_result.coverage)
        if refresh_result.rate_limited:
            st.warning(
                "Yahoo dočasně omezilo požadavky. Dosavadní data jsou uložená; "
                "po ochranné pauze spusťte doplnění znovu."
            )
        elif refresh_result.remaining:
            st.warning(
                f"Automaticky dokončeno {refresh_result.batches} dávek: "
                f"{refresh_result.succeeded} úspěšně, {refresh_result.partial} částečně, "
                f"{refresh_result.failed} chyb. {refresh_result.remaining} tickerů čeká "
                "na pozdější opakování po chybě nebo cooldownu."
            )
        else:
            st.success(
                f"Yahoo cache je hotová: automaticky proběhlo {refresh_result.batches} dávek, "
                f"{refresh_result.succeeded} tickerů úspěšně "
                f"({refresh_result.partial} částečných dat)."
            )

if len(watchlist) > config.large_universe_threshold:
    if use_mt5:
        st.info(
            f"Velký universe režim: analyzuji všech {len(watchlist)} tickerů. "
            "Technická data poběží hromadně přes MT5 a RSS paralelně. "
            "Yahoo fundamenty a odhady analytiků se načtou z trvalé cache; "
            "chybějící tickery doplní jedno kliknutí automaticky po dávkách."
        )
    else:
        st.warning(
            f"Ve watchlistu je {len(watchlist)} tickerů, ale MT5 je vypnuté. "
            "Zapněte MT5, jinak bude technická část ve velkém universe režimu neutrální."
        )

rss_default = DEFAULT_NEWS_SOURCES_TEXT if use_rss else ""
rss_sources = [s.strip() for s in st.text_area("RSS sources", rss_default).splitlines() if s.strip()]
if use_rss:
    st.caption(
        "Tickerové zprávy používají Google News RSS bez registrace (experimentální zdroj). "
        "Nefunkční Yahoo Finance RSS není ve výchozím seznamu."
    )

if st.session_state.analysis_progress:
    _render_progress_ui(st.session_state.analysis_progress, 0.0)

if run_analysis and not watchlist:
    st.error("Watchlist je prázdný. Nahrajte Excel nebo zadejte alespoň jeden ticker.")
    run_analysis = False

if run_analysis:
    pipeline = PipelineService(config)
    previous = st.session_state.last_result["signals"] if st.session_state.last_result else pd.DataFrame()
    started = time.time()

    progress_placeholder = st.empty()

    def _on_progress(state: AnalysisProgressState) -> None:
        st.session_state.analysis_progress = state
        with progress_placeholder.container():
            _render_progress_ui(state, time.time() - started)

    try:
        result = pipeline.run(
            watchlist,
            rss_sources,
            store if save_history else None,
            progress_callback=_on_progress,
            yahoo_only_tickers=yahoo_only_tickers,
            yahoo_only_mode=False,
            rss_enabled=use_rss,
            mt5_enabled=use_mt5,
            learning_config=learning_config,
        )
    except Exception as exc:
        st.error(f"Analýza selhala: {exc}")
        st.exception(exc)
        st.stop()

    result_errors = list(result.get("errors", []))
    result_warnings = list(result.get("warnings", []))
    if result_errors:
        st.error(f"Analýza doběhla s {len(result_errors)} závažnými problémy. Výsledky mohou být fallback.")
        for message in result_errors:
            st.write(f"- {message}")
    if result_warnings:
        with st.expander(f"Upozornění z analýzy ({len(result_warnings)})", expanded=bool(result_errors)):
            for message in result_warnings[:200]:
                st.write(f"- {message}")
            if len(result_warnings) > 200:
                st.caption(f"Zobrazeno prvních 200 z {len(result_warnings)} upozornění.")
    result["configured_sources"] = pd.DataFrame({"source": rss_sources})
    delta_df = pd.DataFrame()
    if compare_prev:
        if save_history and result.get("run_id"):
            delta_df = HistoryService(store).build_delta_against_previous(int(result["run_id"]))
            if delta_df.empty:
                delta_df = HistoryService(store).build_delta_with_excel_fallback(result["signals"], output_dir)
        elif not previous.empty:
            delta_df = ComparisonService.compare_runs(result["signals"], previous)

    dashboard_tables = build_dashboard_tables(result["signals"])
    dashboard_tables.update(VisualizationService.prepare_drop_overlap_tables(dashboard_tables))
    ranking_tables = RankingService.top_bottom_tables(result["signals"])

    if export_excel:
        path = output_dir / f"market_checker_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        dashboard_export = VisualizationService.prepare_dashboard_export_payload(result["signals"], ranking_tables, dashboard_tables)
        try:
            ExcelExporter().export(path, result["signals"], result["sources"], result["articles"], dashboard_tables, prepare_delta_for_excel(delta_df), dashboard_export)
            st.success(f"Excel export uložen: {path}")
            if result.get("run_id"):
                store.update_run_excel_path(int(result["run_id"]), str(path))
        except Exception as exc:
            st.error(f"Excel export selhal: {exc}")

    result["dashboard"] = dashboard_tables
    result["ranking"] = ranking_tables
    result["delta"] = delta_df
    st.session_state.last_result = result

if st.session_state.last_result:
    result = st.session_state.last_result
    signals_df = result["signals"]

    (
        tab_signals,
        tab_dashboard,
        tab_articles,
        tab_sources,
        tab_delta,
        tab_trends,
        tab_history,
        tab_predictions,
        tab_ranking,
        tab_buy,
    ) = st.tabs(
        [
            "Signals",
            "Dashboard",
            "Articles",
            "Sources",
            "Delta",
            "Trends",
            "History",
            "Predikce",
            "Ranking",
            "BUY ANALYSIS",
        ]
    )

    with tab_buy:
        st.subheader("BUY ANALYSIS")
        details = result.get("buy_details", {})
        if not details:
            st.info("Nejd??v spus?te anal?zu watchlistu.")
        else:
            with st.expander("Strategy settings", expanded=False):
                st.caption("Zm?na vah p?epo??t? ulo?en? strategie bez stahov?n? dat.")
                weights = dict(DEFAULT_WEIGHTS)
                for name, label in (("momentum", "Momentum group"), ("fundamental", "Fundamental group"),
                                    ("event", "Earnings group"), ("B01", "B01 Momentum"),
                                    ("B02", "B02 Breakout"), ("B03", "B03 Quality"),
                                    ("B04", "B04 Value"), ("B05", "B05 Earnings"),
                                    ("B06", "B06 F-score")):
                    weights[name] = st.number_input(label, min_value=0.0, max_value=1.0,
                                                     value=float(DEFAULT_WEIGHTS[name]), step=0.05,
                                                     key=f"buy_weight_{name}")
                min_coverage = st.slider("Minimum data coverage", 0.0, 1.0,
                                         float(BUY_CONFIG["min_coverage"]), 0.05)
                max_penalty = st.slider("Maximum risk penalty", 0, 30,
                                        int(BUY_CONFIG["max_risk_penalty"]))
            config_buy = {**BUY_CONFIG, "min_coverage": min_coverage,
                          "max_risk_penalty": max_penalty}
            buy_rows = []
            for ticker, payload in details.items():
                prediction = (learned_model.predict(payload) if learned_model is not None
                              else {"probability": None, "status": "MODEL_UNAVAILABLE"})
                summary = combine_buy(payload["strategies"],
                                      min(float(payload["summary"]["risk_penalty"]), max_penalty),
                                      weights, config_buy)
                buy_rows.append({"ticker": ticker, "sector": payload.get("sector", ""),
                                 "buy_score": summary["buy_score"], "buy_alpha": summary["buy_alpha"],
                                 "risk_penalty": summary["risk_penalty"],
                                 "data_coverage": summary["data_coverage"],
                                 "confidence": summary["confidence"], "status": summary["status"],
                                 "provisional": summary.get("provisional", False),
                                 "learned_probability": prediction["probability"],
                                 "learning_status": prediction["status"],
                                 "main_score_learning_status": payload.get("total_score_details", {}).get("learning", {}).get("status", "OLD_METHODOLOGY"),
                                 "main_score_learning_weight": payload.get("total_score_details", {}).get("learning", {}).get("weight", 0),

                                 "statement_status": payload.get("financial_statements", {}).get("status", "DATA_MISSING"),
                                 "statement_coverage": payload.get("financial_statements", {}).get("coverage", 0),
                                 "statement_fields_present": sum(r.get("value") is not None for r in payload.get("financial_statements", {}).get("field_coverage", [])),
                                 "statement_fields_total": len(payload.get("financial_statements", {}).get("field_coverage", [])),
                                 **{sid: payload["strategies"][sid]["score"]
                                    for sid in ("B01", "B02", "B03", "B04", "B05", "B06")}})
            buy_table = pd.DataFrame(buy_rows)
            scored = buy_table["buy_score"].notna()
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Analyzovan? akcie", len(buy_table))
            m2.metric("BUY kandid?ti", int((buy_table["status"] == "BUY_CANDIDATE").sum()))
            m3.metric("Pr?m?rn? BUY_SCORE", f"{buy_table.loc[scored, 'buy_score'].mean():.1f}" if scored.any() else "?")
            m4.metric("Nedostate?n? data", int((buy_table["status"] == "INSUFFICIENT_DATA").sum()))
            if "metadata" in result:
                st.caption(f"Posledn? aktualizace: {result['metadata'].finished_at}")
            sector_options = sorted(x for x in buy_table["sector"].dropna().unique() if x)
            selected_sector = st.selectbox("Sektor", ["V?echny"] + sector_options)
            selected_status = st.selectbox("Stav", ["V?echny"] + sorted(buy_table["status"].unique()))
            minimum_coverage = st.slider("Filtr pokryt? dat", 0.0, 1.0, 0.0, 0.05)
            displayed = buy_table.loc[buy_table["data_coverage"] >= minimum_coverage]
            if selected_sector != "V?echny":
                displayed = displayed.loc[displayed["sector"] == selected_sector]
            if selected_status != "V?echny":
                displayed = displayed.loc[displayed["status"] == selected_status]
            displayed = displayed.sort_values("buy_score", ascending=False, na_position="last")
            st.dataframe(displayed, width="stretch", hide_index=True)
            st.caption("Nastavení vah na této kartě upravuje jen náhled BUY. "
                       "Hlavní FinalTotalScore má pevně verzované váhy. "
                       "Predikce níže odpovídá nyní zvolenému modelu; sloupce main_score_learning "
                       "ukazují jeho skutečné použití v poslední analýze.")
            st.caption(f"learned_probability: odhad 0–1 pro horizont {learning_config.horizon_sessions} seancí; "
                       f"cíl {learning_config.target}. Prázdná hodnota má vysvětlení ve sloupci learning_status.")
            st.caption("Ka?d? horizont pou??v? vlastn? skupinov? v?hy. "
                       "Kandid?ti s nedostate?n?mi daty nemaj? po?ad?.")
            with st.expander("Swing / position weights", expanded=False):
                horizon_weights = {}
                for horizon, defaults in (
                    ("SWING", (0.60, 0.15, 0.25)),
                    ("POSITION", (0.25, 0.65, 0.10)),
                ):
                    st.write(horizon)
                    horizon_weights[horizon] = {**weights}
                    for group, default in zip(("momentum", "fundamental", "event"), defaults):
                        horizon_weights[horizon][group] = st.number_input(
                            f"{horizon} {group}", min_value=0.0, max_value=1.0,
                            value=default, step=0.05, key=f"buy_{horizon}_{group}")
            for horizon, horizon_weight in horizon_weights.items():
                horizon_rows = []
                for symbol, item in details.items():
                    horizon_summary = combine_buy(
                        item["strategies"],
                        min(float(item["summary"]["risk_penalty"]), max_penalty),
                        horizon_weight, config_buy,
                    )
                    if horizon_summary["buy_score"] is not None:
                        horizon_rows.append({
                            "ticker": symbol, "buy_score": horizon_summary["buy_score"],
                            "status": horizon_summary["status"],
                            "data_coverage": horizon_summary["data_coverage"],
                            "provisional": horizon_summary.get("provisional", False),
                        })
                st.markdown(f"### TOP BUY {horizon}")
                if horizon_rows:
                    st.dataframe(pd.DataFrame(horizon_rows).sort_values(
                        "buy_score", ascending=False).head(20), width="stretch", hide_index=True)
                else:
                    st.info("Zat?m ??dn? kandid?t s dostate?n?m pokryt?m dat.")
            ticker = st.selectbox("BUY detail", list(details))
            payload = details[ticker]
            _render_statement_detail(payload)
            if payload.get("price_history"):
                price_chart = pd.DataFrame(payload["price_history"])
                st.line_chart(price_chart.set_index("date")["close"])
            st.json(payload["summary"])
            st.write("Rizikov? faktory:", payload.get("risk_flags", []))
            chosen_strategy = st.selectbox("Modelov? vstup", list(payload["strategies"]),
                                           key="buy_entry_strategy")
            chosen = payload["strategies"][chosen_strategy]
            equity = st.number_input("Kapit?l ??tu pro model po?tu kus? (0 = bez v?po?tu)",
                                     min_value=0.0, value=0.0, step=1000.0)
            st.write("Modelov? ?rovn?, bez obchodn?ho p??kazu:",
                     model_position(chosen["entry_trigger"], chosen["invalidation_level"],
                                    equity if equity > 0 else None, config_buy))
            for sid, strategy in payload["strategies"].items():
                with st.expander(f"{sid} ? {strategy['strategy_name']} ? {strategy['status']}"):
                    st.json(strategy)
            st.download_button("BUY CSV", displayed.to_csv(index=False).encode("utf-8-sig"),
                               file_name="buy_analysis.csv", mime="text/csv")
            st.download_button("BUY text", displayed.to_string(index=False),
                               file_name="buy_analysis.txt", mime="text/plain")
            from io import BytesIO
            xlsx_buffer = BytesIO()
            with pd.ExcelWriter(xlsx_buffer, engine="openpyxl") as writer:
                displayed.to_excel(writer, sheet_name="BUY", index=False)
            st.download_button("BUY XLSX", xlsx_buffer.getvalue(),
                               file_name="buy_analysis.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    with tab_signals:
        _render_signals(signals_df)

    with tab_dashboard:
        _render_dashboard(signals_df, result.get("ranking", {}), result.get("dashboard", {}), result.get("buy_details", {}))
        st.markdown("### Přehledové tabulky")
        _show_limited_dataframe(result["dashboard"].get("top_total", pd.DataFrame()), "Top 20 by FinalTotalScore")
        _show_limited_dataframe(result["dashboard"].get("weekly_drops", pd.DataFrame()), "Top 20: 7denní propad", preferred_cols=["ticker", "last_week_change_pct", "overlap_count", "overlap_windows", "is_shared_drop", "signal", "final_total_score"])
        _show_limited_dataframe(result["dashboard"].get("d14_drops", pd.DataFrame()), "Top 20: 14denní propad", preferred_cols=["ticker", "last_14d_change_pct", "overlap_count", "overlap_windows", "is_shared_drop", "signal", "final_total_score"])
        _show_limited_dataframe(result["dashboard"].get("m1_drops", pd.DataFrame()), "Top 20: 1M propad", preferred_cols=["ticker", "last_1m_change_pct", "overlap_count", "overlap_windows", "is_shared_drop", "signal", "final_total_score"])
        _show_limited_dataframe(result["dashboard"].get("m3_drops", pd.DataFrame()), "Top 20: 3M propad", preferred_cols=["ticker", "last_3m_change_pct", "overlap_count", "overlap_windows", "is_shared_drop", "signal", "final_total_score"])
        _show_limited_dataframe(result["dashboard"].get("top_marketcap", pd.DataFrame()), "Top 20 by MarketCap")

    with tab_articles:
        _show_limited_dataframe(
            result.get("articles", pd.DataFrame()),
            "Články",
            preferred_cols=["ticker", "source", "published_at", "title", "sentiment"],
            rows=1500,
        )

    with tab_sources:
        configured_sources = result.get("configured_sources", pd.DataFrame())
        _show_limited_dataframe(configured_sources, "Nakonfigurované zdroje (přesně podle pole RSS sources)", rows=2000)

        sources_df = result.get("sources", pd.DataFrame())
        _show_limited_dataframe(sources_df, "Rozbalené zdroje použité během běhu", rows=1000)

        articles_df = result.get("articles", pd.DataFrame())
        st.subheader("Reálně nalezené články podle zdroje")
        if isinstance(articles_df, pd.DataFrame) and not articles_df.empty and "source" in articles_df.columns:
            by_source = articles_df["source"].value_counts().reset_index()
            by_source.columns = ["source", "count_articles"]
            st.dataframe(by_source, width="stretch")
        else:
            st.info("Z článků nebyly detekovány žádné zdroje (nebo nejsou dostupná data).")

    with tab_delta:
        _render_delta(result.get("delta", pd.DataFrame()))

    with tab_trends:
        if save_history:
            _render_trends(HistoryService(store), output_dir)
        else:
            st.info("Trendy nejsou dostupné, protože je vypnuto ukládání historie do SQLite.")

    with tab_history:
        if save_history:
            _render_history(HistoryService(store), output_dir)
        else:
            st.info("Historie není dostupná, protože je vypnuto ukládání historie do SQLite.")

    with tab_predictions:
        st.subheader("Vyšly minulé pondělní predikce v2.1?")
        st.caption(
            "Obchodní akce BUY/SELL se hodnotí jen podle směru a NO_TRADE se do hit rate "
            "nezapočítává. Cenová předpověď UP/DOWN/FLAT se vyhodnocuje zvlášť."
        )
        if save_history:
            hold_tolerance = st.number_input(
                "Tolerance pro skutečný pohyb FLAT (%)",
                min_value=0.0,
                max_value=10.0,
                value=2.0,
                step=0.5,
                key="prediction_hold_tolerance_pct",
                help="Např. 2 % znamená, že skutečný týdenní pohyb od -2 % do +2 % je FLAT.",
            )
            prediction_frames = EvaluationService().evaluate_predictions(
                store.read_global_history(),
                hold_tolerance_pct=float(hold_tolerance),
            )
            overall = prediction_frames["prediction_overall"]
            overall_values = (
                dict(zip(overall["metric"], overall["value"])) if not overall.empty else {}
            )
            evaluated = int(overall_values.get("evaluated_directional_trades") or 0)
            correct = int(overall_values.get("correct_directional_trades") or 0)
            wrong = int(overall_values.get("wrong_directional_trades") or 0)
            hit_rate = overall_values.get("directional_hit_rate_pct")
            coverage = overall_values.get("trade_coverage_pct")
            forecast_accuracy = overall_values.get("forecast_accuracy_pct")
            no_trade = int(overall_values.get("no_trade_predictions") or 0)
            metric_cols = st.columns(6)
            metric_cols[0].metric("Obchody", evaluated)
            metric_cols[1].metric("HIT", correct)
            metric_cols[2].metric("MISS", wrong)
            metric_cols[3].metric(
                "Directional hit rate",
                f"{float(hit_rate):.1f} %" if pd.notna(hit_rate) else "čeká na další běh",
            )
            metric_cols[4].metric(
                "Trade coverage",
                f"{float(coverage):.1f} %" if pd.notna(coverage) else "n/a",
            )
            metric_cols[5].metric(
                "Forecast accuracy",
                f"{float(forecast_accuracy):.1f} %" if pd.notna(forecast_accuracy) else "n/a",
                help=f"NO_TRADE pozorování: {no_trade}",
            )

            if evaluated == 0:
                st.info(
                    "Zatím není uzavřený žádný směrový obchod. NO_TRADE je záměrná abstence; "
                    "forecast se může vyhodnotit i bez obchodu."
                )

            st.caption(
                "Výpočet používá všechny týdny uložené ve stejné SQLite databázi. "
                "Nejnovější týden zůstává PENDING, starší výsledky HIT/MISS/NO_TRADE se nemažou. "
                "Pravděpodobné splity se před výpočtem výnosu auditovatelně upraví."
            )
            cumulative = prediction_frames["prediction_cumulative"].copy()
            weekly = prediction_frames["prediction_weekly"].copy()
            if not cumulative.empty:
                cumulative["week_start"] = pd.to_datetime(
                    cumulative["week_start"], errors="coerce"
                )
                rate_chart_data = cumulative[
                    ["week_start", "hit_rate_pct", "cumulative_hit_rate_pct"]
                ].melt(
                    id_vars="week_start",
                    var_name="series",
                    value_name="hit_rate_pct_value",
                )
                rate_chart_data["series"] = rate_chart_data["series"].map(
                    {
                        "hit_rate_pct": "Úspěšnost daného týdne",
                        "cumulative_hit_rate_pct": "Kumulativní úspěšnost",
                    }
                )
                rate_chart = (
                    alt.Chart(rate_chart_data)
                    .mark_line(point=True)
                    .encode(
                        x=alt.X("week_start:T", title="Týden predikce"),
                        y=alt.Y(
                            "hit_rate_pct_value:Q",
                            title="Úspěšnost (%)",
                            scale=alt.Scale(domain=[0, 100]),
                        ),
                        color=alt.Color("series:N", title="Řada"),
                        tooltip=[
                            alt.Tooltip("week_start:T", title="Týden"),
                            alt.Tooltip("series:N", title="Metrika"),
                            alt.Tooltip(
                                "hit_rate_pct_value:Q",
                                title="Úspěšnost (%)",
                                format=".2f",
                            ),
                        ],
                    )
                    .properties(title="Týdenní a dlouhodobý directional hit rate", height=320)
                )
                st.altair_chart(rate_chart, width="stretch")
                st.caption(
                    "Kumulativní čára je vážená všemi uskutečněnými BUY/SELL akcemi: například 100 HIT a "
                    "1 MISS znamená 99,01 %, nikoli průměr dvou týdnů."
                )

                weekly["week_start"] = pd.to_datetime(weekly["week_start"], errors="coerce")
                result_counts = weekly[["week_start", "hits", "misses"]].melt(
                    id_vars="week_start",
                    var_name="result",
                    value_name="count",
                )
                result_counts["result"] = result_counts["result"].map(
                    {"hits": "HIT", "misses": "MISS"}
                )
                count_chart = (
                    alt.Chart(result_counts)
                    .mark_bar()
                    .encode(
                        x=alt.X("week_start:T", title="Týden predikce"),
                        y=alt.Y("count:Q", title="Počet predikcí", stack=True),
                        color=alt.Color(
                            "result:N",
                            title="Výsledek",
                            scale=alt.Scale(
                                domain=["HIT", "MISS"],
                                range=["#2ca02c", "#d62728"],
                            ),
                        ),
                        tooltip=[
                            alt.Tooltip("week_start:T", title="Týden"),
                            alt.Tooltip("result:N", title="Výsledek"),
                            alt.Tooltip("count:Q", title="Počet"),
                        ],
                    )
                    .properties(title="Počet obchodních HIT a MISS po týdnech", height=280)
                )
                st.altair_chart(count_chart, width="stretch")

            st.write("Výsledek podle obchodní akce")
            st.dataframe(prediction_frames["prediction_summary"], width="stretch")
            st.write("Přesnost cenového forecastu")
            st.dataframe(prediction_frames["forecast_summary"], width="stretch")
            st.write("Srovnání podle verze scoringu")
            st.dataframe(prediction_frames["prediction_by_version"], width="stretch")
            st.write("Dlouhodobý directional hit rate podle tickeru")
            _show_limited_dataframe(
                prediction_frames["prediction_by_ticker"],
                "Souhrn všech uzavřených týdenních predikcí pro každý ticker",
                rows=3000,
            )
            st.write("Detail všech týdenních predikcí")
            _show_limited_dataframe(
                prediction_frames["prediction_details"],
                "HIT/MISS = výsledek BUY/SELL; NO_TRADE = bez obchodu; forecast_result se hodnotí samostatně",
                rows=3000,
            )
        else:
            st.warning(
                "Zapněte `Ukládat historii do SQLite`. Bez uložené ceny a signálu "
                "nelze příští pondělí ověřit, zda predikce vyšla."
            )

    with tab_ranking:
        st.subheader("Top ranking")
        st.dataframe(result["ranking"].get("top", pd.DataFrame()), width="stretch")
        st.subheader("Bottom ranking")
        st.dataframe(result["ranking"].get("bottom", pd.DataFrame()), width="stretch")
        if save_history:
            eval_frames = EvaluationService().evaluate_snapshots(store.read_global_history())
            st.subheader("Historické srovnání skóre (není obchodní backtest)")
            for name, frame in eval_frames.items():
                if name in EvaluationService.PREDICTION_FRAME_NAMES:
                    continue
                st.write(name)
                st.dataframe(frame, width="stretch")
