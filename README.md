# StockTool.eu — vývoj analytické platformy

Testovací web: **https://www.stocktool.eu/test/**  
Data Manager: **https://www.stocktool.eu/test/data-manager/**

## Data Manager v0.3 — hromadná synchronizace MT5

Data Manager již má ověřený přenos reálných svíček z Darwinex-Live (test 10 akcií × 300 D1 svíček a fungující webový graf). Předchozí import stovek D1 akcií úspěšně prošel podle uživatele; konkrétní serverové počty mimo test je nutné ověřit na webu. Verze v0.3 rozšiřuje **zdrojové intervaly z MT5 H1, H4, D1, W1**.

**Není potřeba CSV, exportér, 700 grafů ani EA.** Jeden lokální Python proces využívá přihlášený terminál MetaTrader 5, postupně prochází všechny nabízené akcie a odesílá dokončené OHLCV svíčky přes zabezpečené HTTPS na soukromé úložiště FORPSI.

### Doporučený postup nové verze

1. **Ukonči předchozí okno synchronizátoru D1**, pokud ještě běží. Nespouštěj dvě hromadné synchronizace současně.
2. Nech běžet a přihlášený MetaTrader 5.
3. Z \`scripts/\` spusť \`StockTool-MT5-MULTI-TF-TEST.bat\` — první kontrola 10 akcií × H1, H4, D1, W1 (až 120 dokončených svíček na interval).
4. Pokud test vypíše přenosy bez síťových chyb, spusť \`StockTool-MT5-MULTI-TF.bat\` — do 700 akcií × 4 zdrojové intervaly, až 300 dokončených svíček při prvním importu každého datasetu.
5. Otevři webový Data Manager, připoj se svým existujícím API klíčem a aktualizuj stránku **Ctrl+F5**, pokud má prohlížeč starý JavaScript.

Oba nové BATy stáhnou nejnovější Python synchronizátor z tohoto GitHub repozitáře, ověří přístup k FORPSI a použijí **už uložený API klíč Windows DPAPI**. API klíč **nikdy neposílej do chatu, nezapisuj na GitHub ani do zdrojových kódů**. Přenos používá platně ověřené HTTPS přes knihovnu \`truststore\` a systémová ověření Windows.

Po prvním importu se při běžícím MT5 a synchronizátoru provádí další kontrola každých 15 minut. Pokud počítač vypneš, uložené serverové svíčky zůstávají na FORPSI; po dalším spuštění program navazuje na poslední potvrzenou svíčku pro každý \`symbol|timeframe\`. Celý cyklus stovek instrumentů může trvat déle než 15 minut; 15 minut je přestávka **po dokončení** celého cyklu. Stále jde o testovací prostředí na sdíleném webhostingu, jeho výkon je potřeba sledovat.

### Co zobrazuje web

- **Unikátní akcie** — každý symbol započten právě jednou bez ohledu na počet intervalů.
- **Datasety** — každá kombinace symbolu a interval H1/H4/D1/W1 je samostatný dataset.
- **Počet svíček a poslední aktualizace** — metadata získaná z API.
- **Ticker jednou v levém seznamu**, a u něj dostupné nativní intervaly.
- **Přepínač původních MT5 intervalů** (H1, H4, D1, W1) a samostatný přepínač agregace do vyššího časového rámce.
- **Kontrola OHLC**, duplicitních časů a času poslední svíčky.

Upozornění: burzovní neobchodní hodiny, víkendy a svátky **nejsou chyby historie**. Data Manager nyní nekvalifikuje běžné tržní přestávky jako ztracené svíčky. Broker může mít pro některé akcie kratší historii nebo instrument nemusí podporovat vybraný interval. Jednotlivé MT5 instrumenty mohou mít odlišné obchodní hodiny a hodnoty tick volume.

### Ruční režim bez BAT (pro diagnostiku)

\`\`\`powershell
py -3 -m pip install MetaTrader5 truststore
py -3 scripts/stocktool_mt5_sync.py --check-api
py -3 scripts/stocktool_mt5_sync.py --once --max-symbols 10 --timeframes H1,H4,D1,W1 --initial-bars 120
py -3 scripts/stocktool_mt5_sync.py --loop --max-symbols 700 --timeframes H1,H4,D1,W1 --initial-bars 300
\`\`\`

Původní přepínač \`--timeframe D1\` zůstává funkční. Nový \`--timeframes\` umožňuje více intervalů v jedné instanci. Zpracovává jen symboly, které broker kategorizuje jako Stocks / Shares / Equities (aktuálně bylo zjištěno 685 symbolů na Darwinex-Live); konkrétní počet a dostupná historie se mohou měnit.

### Architektura a bezpečnost

\`\`\`text
Windows PC + MetaTrader 5
  └── scripts/stocktool_mt5_sync.py  (read-only Python MT5 integrace)
        └── šifrované HTTPS + soukromý API klíč
              └── FORPSI PHP API: site/data-manager/api/
                    ├── ingest.php
                    ├── datasets.php   (rychlá metadata symbolů)
                    └── candles.php    (konkrétní vybraný dataset)
              └── stocktool-private/data/   (mimo veřejné www)
                    └── webový Data Manager
\`\`\`

Klíč na hostingu leží v \`/stocktool.eu/stocktool-private/config.php\` **mimo \`www\`** a nikdy se nenasazuje do veřejného adresáře. Data z webu jsou čitelná jen po přihlášení API klíčem, který se v prohlížeči drží pouze v paměti otevřené stránky.

Hosting FORPSI: FTP \`ftpx.forpsi.com\`, cesta \`/stocktool.eu/www/test/\`. Web se publikuje z PC přes existující **StockTool Deploy v3** a WinSCP s FTPS Explicit TLS. Rozšíření serverového PHP endpointu nevyžaduje nový soukromý klíč.

**Pozor:** starý \`StockToolBridge.mq5\` po jednom grafu a ruční CSV exportér byly odstraněny. Konektor neobsahuje obchodní příkazy. Respektuj licenční podmínky burzovních dat a brokera, zejména před zveřejněním dat dalším uživatelům.

### Zbývající vývoj

Výkonnější centrální úložiště (pravděpodobně MySQL dle možností FORPSI), přesnější kontrola obchodních kalendářů, automatické spuštění na Windows **jen po výslovném zapnutí uživatelem**, a první BUY / SHORT analytické webové aplikace nad společnými daty.

