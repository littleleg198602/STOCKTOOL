# StockTool.eu

Webová platforma pro finanční analytiku, výzkum akcií, obchodních strategií a backtesting.

## Stav – v1.1: první funkční webová aplikace

První responzivní úvodní stránka s katalogem šesti aplikací (Data Manager BETA, ostatní ve vývoji):
- JOHNY
- BUY Scanner
- SHORT Scanner
- Order Flow
- Backtesting
- Data Manager

Katalog obsahuje interaktivní hledání, přepínače kategorií, detaily plánovaných aplikací a přehled vývoje. Graf na úvodní stránce je pouze ilustrační – nejde o tržní data. První funkční aplikace Data Manager běží samostatně pod `/test/data-manager/`.

## Data Manager BETA – první funkční modul

Web: `https://stocktool.eu/test/data-manager/` (po lokálním nasazení Deploy v3).

Funkce:
- Import CSV/TSV z MT5 se sloupci DATE, TIME, OPEN, HIGH, LOW, CLOSE, TICKVOL (případně bez objemu).
- Normalizace a kontrola OHLC, seřazení svíček podle času, spojení opakovaných importů stejného symbolu/timeframe.
- Lokální uložení do IndexedDB v prohlížeči (max. 100 000 svíček na dataset).
- Svíčkový graf, agregace do delšího intervalu (např. H1 → H4 / D1), tabulka s listováním.
- Export všech původních svíček zpět do CSV, smazání datasetu, umělý demo dataset.
- Limit souboru 20 MB. Záznamy se nikam neodesílají; **zatím nejde o společnou serverovou databázi ani automatické propojení s MT5**.
- Při vymazání úložiště prohlížeče mohou uložená data zmizet. Důležité datasety exportuj.

CSV exportér pro Windows s MetaTraderem 5:
```powershell
py -m pip install MetaTrader5
py scripts/export_mt5_csv.py --symbol XAUUSD --timeframe H1 --count 5000
```
Exportér používá právě otevřený a přihlášený MT5 terminál na PC; neodesílá žádná hesla. Exportuje jen **dokončené** svíčky (bez aktuálně se tvořící). Časy z MT5 Python API ukládá v UTC. Zdroj a skutečná dostupnost historie závisí na brokerovi. Web si interval doplněný do importního formuláře neodvozuje automaticky ze souboru; musí odpovídat exportu.

Složky:
- `site/data-manager/index.html`, `styles.css`, `app.js` – první aplikace.
- `scripts/export_mt5_csv.py` – místní Python MT5 exportér (nenahrává se na hosting).

## Soubory webu

- \`site/index.html\` – vstupní stránka.
- \`site/assets/styles.css\` – vzhled a mobilní zobrazení.
- \`site/assets/app.js\` – vyhledávání, filtry, detaily.
- \`site/assets/favicon.svg\` – ikonka stránky.

Web funguje jako statické HTML, CSS a JavaScript bez instalačních závislostí.

## Nasazení – aktuální postup

Publikujeme **z lokálního PC přes WinSCP na FORPSI**. GitHub používáme pro vývoj a verzování.

1. Změny uložit do větve \`main\`.
2. Ve Windows spustit existující \`Deploy-StockTool.bat\` (StockTool Deploy v3).
3. Skript stáhne aktuální \`site/\` a synchronizuje ji do cílového adresáře na FORPSI.
4. Otevřít [https://stocktool.eu/test/](https://stocktool.eu/test/) a aktualizovat prohlížeč, případně přes Ctrl+F5.

### Ověřená cesta FTP pro multihosting

- FTP host: \`ftpx.forpsi.com\`
- Uložené připojení WinSCP: \`f0476608.multi@ftpx.forpsi.com\`
- Cílový adresář: \`/stocktool.eu/www/test/\`

Připojení je potřeba zabezpečit volbou **FTP → TLS/SSL Explicit encryption**, port 21; neukládat přihlašovací údaje do repozitáře. Pokud upravíš název uloženého připojení WinSCP, uprav i místní deploy skript.

**Pozor:** hlavní \`/stocktool.eu/www/\` nesynchronizujeme. Pracujeme pouze v podsložce \`test/\`, aby se nepřepsal stávající web.

Starý \`.github/workflows/deploy-test.yml\` byl test pro nasazení přes GitHub Actions a momentálně se nepoužívá. K publikování používej lokální Deploy v3.

## Další fáze

Nyní: praktické otestování Data Manageru v prohlížeči a exportu z uživatelova MT5. Další krok: bezpečný lokální most pro automatickou synchronizaci dat a později Python služby/datová vrstva se správným řízením přístupů. Běžný sdílený hosting FORPSI může vyžadovat oddělené řešení pro trvale běžící Python procesy.
