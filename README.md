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



---

## BUY Scanner v0.1 – první analytická webová aplikace

**Adresa po nasazení přes WinSCP Deploy v3:**
https://www.stocktool.eu/test/buy-scanner/

**Data:** Skener čte přímo ze soukromého úložiště Data Manageru na FORPSI, tj. již synchronizované **denní D1 svíčky z Darwinex MT5**. Nepotřebuje žádný nový Python exportér, další program ani nový API klíč. Používá existující přístupový klíč StockTool. Klíč je pouze v paměti otevřené stránky, ukládání do cookies/localStorage ani do URL neprobíhá. Aktuálně je třeba jej při otevření BUY Scanneru vložit; sjednocené přihlášení bude samostatná další fáze.

**Cesta v repozitáři:**
- \`site/buy-scanner/index.html\` – aplikace.
- \`site/buy-scanner/styles.css\` – responzivní design.
- \`site/buy-scanner/app.js\` – dávkové načítání, filtrování, Top 10, graf, TXT export.
- \`site/buy-scanner/api/scan.php\` – autentizovaná serverová analýza každého D1 datasetu.

### Funkce

- Projde všechny dostupné D1 datasety na FORPSI po dávkách max. 60 souborů (API limit 80 na požadavek).
- Zobrazuje počet analyzovaných akcií, BUY kandidátů, nezřetelných nastavení a dat mimo požadavky.
- Filtrování Breakout / Pullback / Trend / Watch, vyhledávání symbolu, řazení a přepínač Top 10.
- Detail tickera: RSI(14), SMA(20/50/200), ATR(14) v % ceny, 20denní změna, 52týdenní high, poměr tick volume a konkrétní důvody zařazení.
- Detailní graf čte poslední denní svíčky přes existující \`data-manager/api/candles.php\`.
- Kopírování tickerů v jednom řádku do MT5 a textový souhrn (TXT) – **export výsledků analýzy, nikoliv historických cen**.

### Přesná výchozí pravidla v0.1

Všechny 3 typy technických kandidátů vyžadují platnou D1 historii **nejméně 210 dokončených svíček**, poslední svíčku ne starší než 10 kalendářních dní, close nad SMA200, SMA50 nad SMA200 a SMA50 rostoucí proti hodnotě před 5 obchodními svíčkami.

1. **Breakout** – k tomu close nejméně jako nejvyšší High předchozích 20 dokončených D1 svíček, RSI14 v rozsahu 45–76.
2. **Pullback** – pokud neprošel breakout: close od 97 % do 102,5 % SMA50 a RSI14 40–65.
3. **Trend** – pokud neprošel předchozí filtry: RSI14 48–70.
4. **Watch** – cena nad SMA200, RSI14 35–78, ale bez plné BUY formace.
5. **Bez signálu / málo dat / stará data** – aktuálně nezařazujeme mezi BUY kandidáty.

**Nejde o JOHN/Y score ani neprůhledné doporučení.** Řazení Top 10 je podle typu formace (Breakout → Pullback → Trend) a následně podle 20denní cenové změny, nikoliv podle pravděpodobnosti zisku či očekávaného výnosu. Není dosud zahrnuta valuation/fundamentální analýza, skutečný order flow, forced-selling indikátor ani risk-adjusted backtest – tyto vrstvy musí být vyhodnocovány samostatně, aby nedošlo ke směšování proxy a reálných údajů.

**Objem:** MT5 poskytuje \`tick_volume\` podle brokera; není to standardizovaný burzovní objem a nepoužíváme jej jako zásadní tvrdé BUY kritérium. Poměr 20denního tick volume vůči předchozím 20 dnům je pouze kontext.

**Svěžest:** 10denní limit chrání před výběrem titulů s velmi starými svíčkami. Není to oficiální obchodní kalendář; víkendy/svátky a dlouhé trading halty vyžadují později přesnější validaci.

### Nasazení a první ověření

1. Spusť na Windows svůj funkční \`Deploy-StockTool.bat\` (v3). Nasadí aktualizovanou \`site/\` do \`/stocktool.eu/www/test/\` na FORPSI, **bez zásahu do hlavního webu**.
2. Otevři \`https://www.stocktool.eu/test/buy-scanner/\` a vlož existující StockTool API klíč.
3. Klikni „Spustit BUY Scanner“, dokonči dávkové načítání dat a zkontroluj první výsledky.
4. Data Manager pro ověření původních cen zůstává na \`/test/data-manager/\`.

**Aktuální omezení:** Kód je připraven v GitHubu, ale BUY Scanner v0.1 zatím neprošel ověřením ve skutečném nasazení na FORPSI. Před obchodním využitím je nutné provést test na reálných D1 datech a zpětné ověření výsledků proti historii a případné divergenci brokerových dat. Skener nevydává ani nevykonává obchodní příkazy.


## Jednotné přihlášení StockTool – bez opakovaného API klíče

**Funkce od listopadu 2026:** Data Manager a BUY Scanner používají jednu zabezpečenou relaci v prohlížeči.

1. Po nasazení webu přes \`Deploy-StockTool.bat\` se na libovolné z těchto dvou stránek přihlas **jednou** současným soukromým API klíčem.
2. PHP ověří klíč na serveru a nastaví session cookie \`STOCKTOOL_AUTH\` s příznaky **Secure**, **HttpOnly**, **SameSite=Lax**, se společnou doménou \`stocktool.eu\` a cestou \`/test/\`.
3. Obě aplikace při otevření automaticky zkontrolují \`/test/data-manager/api/session.php\` a při platné relaci skrývají pole s API klíčem. **Samotný klíč se do cookie neukládá.**
4. Přihlášení má **klouzavou platnost 30 dnů od posledního použití**, pokud soubory cookie nebo data prohlížeče nejsou vymazány. Po vypršení, změně klíče nebo na jiném prohlížeči je nutné jednorázové opětovné přihlášení.
5. Odhlášení v jedné aplikaci odhlásí i druhou aplikaci při její další interakci/obnovení. Serverové relace žijí mimo veřejný web v \`/stocktool.eu/stocktool-private/sessions/\`.

Serverová API:
- \`POST /test/data-manager/api/login.php\` — ověří původní klíč (v hlavičce) a založí relaci.
- \`GET /test/data-manager/api/session.php\` — ověří zapamatované přihlášení.
- \`POST /test/data-manager/api/logout.php\` — odhlášení pro obě aplikace.
- \`GET /test/data-manager/api/datasets.php\`, \`GET /test/data-manager/api/candles.php\` a \`GET /test/buy-scanner/api/scan.php\` — přijímají zabezpečenou relaci nebo původní klíč.
- **\`POST /test/data-manager/api/ingest.php\` nadále vyžaduje přímo původní API klíč; přihlášení prohlížeče nestačí ke změně nebo odesílání dat.** Proto hromadná synchronizace MT5 funguje beze změny a bez nové konfigurace.

Žádná veřejná část serveru ani GitHub repozitář neobsahuje produkční API klíč. Tento způsob je vhodný pro soukromý provoz platformy; před otevřením veřejnosti s více uživateli bude třeba zavést individuální účty a jejich oprávnění.

**Nasazení změn:** Spusť existující lokální \`Deploy-StockTool.bat\` v3 a na webu obnov stránky přes Ctrl+F5. V nové verzi zadáš klíč **naposledy při prvním přihlášení**; potom se relace automaticky obnovuje. Starý Python synchronizátor na PC není potřeba měnit ani zastavovat.



---

## SHORT Scanner v0.1 – samostatná aplikace pro bearish analýzu

**Po nasazení:** https://www.stocktool.eu/test/short-scanner/

Vlastní logika pro technické scénáře poklesu, **nikoli mechanicky invertovaný BUY Scanner**. Používá již uložená D1 data z Data Manageru na FORPSI, bez CSV, nového MT5 exportéru a bez dalšího API klíče. Sdílí stávající zabezpečenou přihlašovací relaci StockTool s Data Managerem a BUY Scannerem (pokud je platná).

### Soubory
- \`site/short-scanner/index.html\` – vlastní webová stránka.
- \`site/short-scanner/app.js\` – filtrovaný seznam, paginace, graf, export tickerů a TXT analýzy.
- \`site/short-scanner/styles.css\` – vlastní barevné schéma; sdílí základ responzivního designu s BUY Scannerem.
- \`site/short-scanner/api/scan.php\` – autentizovaný PHP endpoint; dávkově prochází D1 datové soubory.
- \`site/short-scanner/api/short_rules.php\` – samostatné čisté analytické funkce.
- \`tests/short_rules_test.php\` – offline regresní testy pro PHP (bez API klíče a bez MT5).

### Výstupy
- **Top 10 SHORT kandidátů** – technicky potvrzená bearish formace, filtr proti extrémnímu riziku.
- **Top 5 rizikové** – technicky slabé akcie s příznaky možného prudkého odrazu / squeeze.
- **Top 5 nebrat** – ignorovat pro nynější SHORT vstup: příliš rizikové, zastaralé či nedostatečné informace nebo absence setupu.
- Samostatné filtry **Breakdown / Failed Rally / Downtrend / Watch**, vše, řazení, hledání a zobrazení detailu.
- **TXT výsledky a tickery v jednom řádku** pro MT5, navíc jedním kliknutím společný report **Top 10 SHORT / Top 5 rizikové / Top 5 nebrat** (jde o výstup screeningu, NE pokyn obchodovat).

### Technické podmínky – v0.1

Minimum **210 validních dokončených D1 svíček**. Poslední svíčka maximálně 10 kalendářních dní stará (jednoduchý limit, ne burzovní kalendář). Dlouhodobý bearish režim vyžaduje současně:
1. Close pod SMA200.
2. SMA50 pod SMA200.
3. SMA50 klesající proti SMA50 před 5 svíčkami.

Následně:
- **Breakdown**: v režimu poklesu close pod Low předchozích 20 svíček, RSI(14) 30–60.
- **Failed Rally**: v režimu poklesu close pod SMA50, denní High nejméně 98 % SMA50, denní close pod open, RSI(14) 32–65.
- **Downtrend**: v režimu poklesu close pod SMA50, dvacetisvíčková změna nejvýše -3 %, RSI(14) 30–65.
- **Watch**: cena pod SMA200 a další známka slabosti, bez kompletní SHORT formace.

**Rizikové veto (SHORT nezahrne do Top 10):** RSI pod 30; close více než 12 % pod SMA50; propad za 5 svíček o 15 % nebo více; ATR14 alespoň 7 % ceny; růst poslední svíčky o 10 % nebo více; chybné/duplicitní svíčky. Tyto příznaky se ukazují v detailu a mohou posunout jinak bearish kandidáta do kategorie „NEBRAT“.

**Pořadí není predikce výnosu:** defaultně Breakdown → Failed Rally → Downtrend a následně větší záporná 20denní změna; rizikový seznam podle počtu rizikových příznaků a volatility. Bez nějakého proprietárního skóre. Hodnoty ATR, RSI, SMA, změny a důvody jsou dohledatelné v detailu.

**Nezahrnuje:** dostupnost vypůjčení, poplatek za borrow, short interest, option gamma, skutečný order flow, fundamentální valuaci, vyhlášené výsledky a následné gapy. Bez těchto údajů aplikace **nemůže potvrdit proveditelný SHORT obchod**. Vše je výzkumná analýza, nikoli obchodní pokyn; Python ani server neodesílají objednávky na brokera.

### Nasazení
1. Spusť existující fungující **Deploy-StockTool.bat v3** na Windows. Nasazuje obsah \`site/\` do \`/stocktool.eu/www/test/\`.
2. Otevři https://www.stocktool.eu/test/short-scanner/ (případně Ctrl+F5).
3. Pokud už jsi přihlášený v Data Manageru nebo BUY Scanneru, pole pro klíč se skryje.
4. Klikni **Spustit SHORT Scanner**. Stránka analyzuje všechny dostupné D1 datové soubory postupně v dávkách po 35, aby se omezila zátěž sdíleného hostingu.
5. Vyzkoušej Top 10 SHORT, Top 5 rizikové, Top 5 nebrat, detail akcie a TXT.

**Testování:** Statická kontrola JavaScriptu, vazby na HTML prvky a simulace nepřihlášené/přihlášené webové aplikace byly úspěšné. Offline PHP testy jsou v \`tests/short_rules_test.php\`; lze je spustit příkazem \`php tests/short_rules_test.php\` na PC/serveru s PHP. Skutečný výpočet z reálných D1 dat na FORPSI je nutné ověřit po nasazení. Není důvod znovu instalovat MT5 nebo měnit API klíč.
