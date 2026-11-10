# StockTool.eu

Webová platforma pro finanční analytiku, výzkum akcií, obchodních strategií a backtesting.

## Stav – v1.0

První responzivní úvodní stránka s katalogem šesti připravovaných aplikací:
- JOHNY
- BUY Scanner
- SHORT Scanner
- Order Flow
- Backtesting
- Data Manager

Katalog obsahuje interaktivní hledání, přepínače kategorií, detaily plánovaných aplikací a přehled vývoje. Graf na úvodní stránce je pouze ilustrační – nejde o tržní data. Analytické moduly zatím nejsou spuštěné.

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

Po schválení vizuálního vzhledu první funkční webová aplikace, následně samostatné Python služby a datová vrstva. Běžný sdílený hosting FORPSI může vyžadovat oddělené řešení pro trvale běžící Python procesy.
