# STOCKTOOL.EU

Webová platforma s analytickými nástroji. Data Manager propojujeme s MetaTraderem 5
**přímo přes již používanou Python integraci**: bez CSV, bez exportéru a bez jednoho
Expert Advisora na každý symbol.

## Jak funguje hromadná synchronizace MT5

\`\`\`
MetaTrader 5 (běžící na Windows)
  └── jeden stocktool_mt5_sync.py (čte až 700+ akcií automaticky)
        └── HTTPS API na FORPSI
              └── soukromé datové úložiště mimo www
                    └── Data Manager na stocktool.eu/test/data-manager/
\`\`\`

**Nejde o program pro ruční export.** Synchronizátor čte svíčky přímo přes
\`MetaTrader5\` Python knihovnu, zpracuje seznam dostupných symbolů a pošle je
na zabezpečený web. Nepotřebuje otevřené grafy ani vlastní EA v MT5.
Nepoužívá tradingové funkce a nikdy nezadává obchody.

### Co už je v repozitáři

- \`scripts/stocktool_mt5_sync.py\` — jeden synchronizátor pro mnoho symbolů.
- \`scripts/StockTool-MT5-START.bat\` — spuštění synchronizace jedním kliknutím.
- \`site/data-manager/\` — webový graf, přihlášení k API, vyhledávání tickerů.
- \`site/data-manager/api/\` — PHP příjem a čtení dat z neveřejného úložiště.

### První spuštění na Windows

1. Otevři MT5, přihlas se ke svému brokerovi, nech terminál zapnutý.
2. Do stejné složky na počítači ulož ze složky \`scripts/\` oba soubory
   \`StockTool-MT5-START.bat\` a \`stocktool_mt5_sync.py\`.
3. Dvojklik na \`StockTool-MT5-START.bat\` (na počítači musí být Python).
4. Při prvním spuštění jednou zadáš stejný soukromý API klíč jako na FORPSI.
   V této verzi se ve Windows uloží chráněný DPAPI, nikoli do GitHubu.
5. Program projde dostupné akcie od brokera a postupně pošle dokončené D1
   svíčky do FORPSI. Dále při běžícím MT5 automaticky kontroluje nové svíčky.
6. Otevři \`https://www.stocktool.eu/test/data-manager/\`, přihlas se klíčem a
   vyber ticker. Web kontroluje aktualizace každých 30 sekund.

**Pozor:** detekce akcií je založena na názvech skupin brokerových symbolů
(např. Stocks, Shares, Equities). Pokud má broker atypické názvy skupin,
\`--universe stocks\` nemusí najít všech 700 požadovaných akcií. Nejprve ověř
výpis dostupných akcií; alternativou je \`--universe marketwatch\` (viditelné
symboly v Market Watch, mohou zahrnovat i neakcie) nebo \`--universe file\`
s TXT seznamem přesných brokerových názvů (jedna akcie na řádek).
TXT seznam je jen výběr tickerů, **nejde o export cen ani svíček**.

Diagnostika bez odesílání dat:
\`\`\`powershell
py -3 scripts/stocktool_mt5_sync.py --discover --max-symbols 20000
\`\`\`

Jednorázový test na maximálně 10 akciích:
\`\`\`powershell
py -3 scripts/stocktool_mt5_sync.py --once --max-symbols 10 --initial-bars 100
\`\`\`

Běžná automatická synchronizace:
\`\`\`powershell
py -3 scripts/stocktool_mt5_sync.py --loop --max-symbols 700 --timeframe D1 --initial-bars 300 --interval-minutes 15
\`\`\`

Pro H1 lze spustit jinou instanci s parametrem \`--timeframe H1\`. Pro větší
zátěž ale nejprve ověř výkon a limit hostingového tarifu.

**Jak funguje postupná aktualizace:** poprvé se odešle až 300 uzavřených
D1 svíček na instrument; pak se přenášejí nové dokončené svíčky. Poslední
úspěšně synchronizovaný čas se ukládá na Windows do \`~/.stocktool/\`, aby se
po restartu nestahovala znovu celá historie. Po delším výpadku se pokusí
doplnit všechny dostupné svíčky od posledního úspěšného přenosu.

**Limit:** Python MT5 získá jen svíčky, které daný broker v terminálu nabízí;
historie respektuje také nastavení \`Max. bars in chart\` v MT5. Někteří brokeři
700 požadovaných akcií vůbec nenabízejí nebo mají jiné názvy.

### Webové API na FORPSI

Před synchronizací je nutné jednou nakonfigurovat server. To jsme v projektu
již začali: \`/test/data-manager/api/status.php\` má odpovědět JSON s
\`"configured":true\`.

Hlavní hosting je u FORPSI, soubory nahráváme lokálně přes WinSCP a
\`Deploy-StockTool.bat\` v3, do:
\`/stocktool.eu/www/test/\`.

Soukromá konfigurace zůstává **mimo** veřejný web:
\`\`\`
/stocktool.eu/
├── www/test/data-manager/api/
└── stocktool-private/
    ├── config.php     # API klíč; NEPATŘÍ do GitHubu
    └── data/          # automaticky vytvářené datové soubory
\`\`\`

Knihovna bere tajný klíč z proměnné prostředí \`STOCKTOOL_API_KEY\`, nebo si
ho při prvním spuštění vyžádá a lokálně zašifruje pomocí Windows DPAPI.
Klíč nikdy nesdílej ve zprávách ani repozitáři. Vždy používej HTTPS
k API a **FTPS** při nasazování přes WinSCP.

Pokud endpoint \`/test/data-manager/api/status.php\` vrací přímo PHP zdrojový
kód místo JSON, API je chybně nastavené a nesmí se použít s klíči.

### Kapacita a bezpečnost

- Doporučené pilotní ověření: 10 akcií, pak 100, potom cca 700.
- Přenos omezuje pauza mezi požadavky; při chybném HTTP serveru používá retry.
- Na hostingu se ukládají maximálně poslední 20 000 svíček na jeden
  symbol/timeframe, web najednou čte posledních 5 000. Výchozí D1 přenos
  posílá při prvním cyklu až 300 svíček na symbol.
- Metadata datasetu jsou zvlášť, aby seznam 700 akcií nepotřeboval číst
  700 velkých souborů.
- Při vypnutí počítače nebo MT5 se synchronizace zastaví a po spuštění
  se pokusí chybějící svíčky doplnit.
- Každý broker má jinou nabídku akcií a tick volume není skutečný burzovní
  obchodovaný objem. Ověř podmínky brokera před přeposíláním či zveřejněním dat.

### Rozsah testování

Repo obsahuje implementaci, ale přenos nelze považovat za úspěšně zprovozněný,
dokud neproběhne test s tvým MT5 a hostingem FORPSI. Nejsou žádné závislosti
na placeném cloudu; musíme ale ověřit výkon a kvóty sdíleného hostingu.

Dřívější \`mt5/StockToolBridge.mq5\` (jedna instance na graf) byl opuštěn.
Data Manager nyní používá jeden lokální Python bridge pro hromadné načítání.
