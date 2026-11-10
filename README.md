# STOCKTOOL.EU

Finanční analytická webová platforma. První aplikace: **Data Manager – přímá synchronizace MT5**.

## Aktuální stav

- Web s katalogem aplikací: \`site/\`.
- Data Manager: \`site/data-manager/\`.
- Serverové PHP API: \`site/data-manager/api/\`.
- StockToolBridge – **Expert Advisor přímo v MT5**, nikoliv CSV exportér: \`mt5/StockToolBridge.mq5\`.

## Přímá synchronizace MT5 → StockTool

\`\`\`
MetaTrader 5 (běžící na PC)
  └── StockToolBridge.mq5 (EA – jen čte svíčky, neobchoduje)
        └── HTTPS POST /test/data-manager/api/ingest.php
              └── Soukromé soubory mimo www (stocktool-private/data/)
                    └── /test/data-manager/api/candles.php
                          └── Webový graf a tabulka na Data Manageru
\`\`\`

**Není potřeba CSV, Python exportér ani další cloud.** Svíčky odesílá automaticky přímo terminál MT5. Prohlížeč se ovšem nemůže sám přímo připojit k procesu MT5 běžícímu na Windows, proto používáme modul EA a webové API.

**Důležité:** Odesílání nových svíček vyžaduje spuštěný MT5 i připojení k internetu. První verze synchronizuje vybraný symbol a timeframe, obvykle jeden EA na každý požadovaný pár. Při startu dožene až 5 000 dokončených svíček po dávkách, další svíčky posílá automaticky. Celkový soubor uchovává posledních 20 000 svíček na dataset. Web čte nejnovějších maximálně 5 000.

### 1. Nejprve publikuj web na FORPSI

Ve Windows spusť stávající **StockTool Deploy v3**. Nasazuje pouze obsah adresáře \`site/\` do:

\`/stocktool.eu/www/test/\`

Ověř v prohlížeči:

\`https://www.stocktool.eu/test/data-manager/api/status.php\`

Musíš vidět JSON (např. \`{"ok":true,"configured":false,...}\`). Pokud se zobrazí zdrojový PHP kód, HTML chyba nebo soubor ke stažení, **zastav se**: PHP není správně nastavené, nesmí se nahrávat API klíče.

### 2. Připrav neveřejný klíč a serverovou složku

**POZOR: před manipulací s klíčem změň připojení WinSCP z obyčejného FTP na FTPS / TLS Explicit (port 21).** Obyčejné FTP posílá přihlašovací údaje nezabezpečeně.

Ve WinSCP na FTP hlavního multihostingu založ mimo \`www\`:

\`\`\`
/stocktool.eu/
├── www/
│   └── test/
│       └── data-manager/
│           └── api/           ← veřejně dostupné PHP soubory, BEZ klíče
└── stocktool-private/
    └── config.php             ← SOUKROMÝ soubor, NEVEŘEJNÝ, NEPATŘÍ do GitHubu
\`\`\`

V PowerShellu na Windows vygeneruj náhodný klíč:

\`\`\`powershell
[guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
\`\`\`

Výsledkem je 64znakový náhodný řetězec. Ve WinSCP vytvoř soubor \`/stocktool.eu/stocktool-private/config.php\` s tímto obsahem (vlož svůj vlastní klíč):

\`\`\`php
<?php
return [
    'api_key' => 'ZDE_VLOZ_VLASTNI_NAHODNY_KLIC'
];
\`\`\`

Vzor je v \`mt5/private-config.example.php\`. Klíč nesdílej v chatu ani ve veřejném GitHubu. **Musí mít alespoň 32 znaků**. Soubor \`stocktool-private\` zůstane mimo veřejně přístupné \`www\`. Pokud hosting blokuje PHP přístup mimo \`www\`, bude nutné změnit umístění úložiště nebo využít hostovanou databázi.

Po vytvoření configu znovu otevři \`https://www.stocktool.eu/test/data-manager/api/status.php\` – mělo by být \`"configured":true\`. Tento status neověřuje, zda je klíč správně zadaný, pouze přítomnost souboru.

### 3. Přidej modul přímo do MetaTraderu 5

1. Otevři **MT5 → Soubor → Otevřít složku dat**.
2. Přejdi do \`MQL5/Experts/\`.
3. Ulož sem \`mt5/StockToolBridge.mq5\` z repozitáře a otevři ho v MetaEditoru, **F7 = kompilovat**.
4. V MT5 otevři **Nástroje → Možnosti → Expertní poradci** a přidej do povolených WebRequest URL \`https://www.stocktool.eu\`.
5. Připoj **StockToolBridge** na graf a nastav:
   - \`InpApiKey\` – stejný klíč z neveřejného \`config.php\`.
   - \`InpSymbol\` – prázdný = aktuální symbol grafu; jinak přesný název od brokera, např. \`XAUUSD\`.
   - \`InpTimeframe\` – např. \`PERIOD_H1\`.
   - \`InpInitialBars\` – např. \`500\` (max 5000).
   - \`InpEverySeconds\` – např. \`60\`.

V záložce **Experts** v MT5 kontroluj hlášky \`StockTool: synchronized...\` nebo případnou HTTP chybu. Modul neobsahuje žádné obchodní operace.

**Před zadáním klíče vždy ověř, že adresa serveru je skutečně HTTPS s platným certifikátem.** Výchozí URL je \`https://www.stocktool.eu/test/data-manager/api/ingest.php\`. Pokud na tomto hostnamu HTTPS nefunguje, je potřeba nejdřív zapnout SSL u FORPSI; nepřecházej na HTTP.

### 4. Otevři Data Manager

\`https://www.stocktool.eu/test/data-manager/\`

Do pole pro klíč vlož tentýž tajný klíč a klikni **Připojit**. Web načte datasety, graf a tabulku; automaticky je obnovuje každých 30 sekund. Klíč si drží jen v paměti otevřené záložky.

**Známá omezení BETA:** Prohlížeč si data z MT5 nevyžádá sám; EA aktivně odesílá zvolený symbol/timeframe. Server zatím ukládá do souborů a nemusí zvládat velké množství současných uživatelů. OHLCV údaje jsou data konkrétního brokera, tick volume není totéž co burzovní obchodovaný objem. Před veřejným zpřístupněním ověř licenci k tržním datům.

## Repo a nasazování

Repo: https://github.com/littleleg198602/STOCKTOOL

- Vývoj v GitHub / Codex.
- Publikace z lokálního Windows přes **WinSCP** a připravený \`Deploy-StockTool.bat\` v3.
- Nasazení pouze do \`/stocktool.eu/www/test/\`, hlavní web necháváme beze změny.
- Dřívější GitHub Actions FTPS workflow se nepoužívá.
- V repozitáři **nejsou žádné produkční klíče** a nikdy tam nesmějí být.

## Další fáze

Po otestování sestavení EA a PHP API na FORPSI: více symbolů/timeframů z jediného modulu, doplňování historie po výpadku, centrální MySQL úložiště, řízení uživatelů a napojení BUY / SHORT / Backtesting.
