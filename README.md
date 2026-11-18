# StockTool.eu — vývoj analytické platformy

## JOHNY: výpočty přes GitHub Actions

Připravené propojení používá původní Python jádro JOHNY, seznam a D1 svíčky
z Data Manageru a výsledky zobrazuje v `site/johny/`. Historie i model se ukládají
na soukromé místo na FORPSI. Aktivace vyžaduje nasazení nových endpointů a Actions
secret `STOCKTOOL_API_KEY`. [Postup aktivace a rozsah první verze](docs/JOHNY_GITHUB_ACTIONS.md).

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


---

## Market Pressure Scanner v0.1 – aplikace 04

**Po nasazení přes stávající Deploy v3:**
https://www.stocktool.eu/test/market-pressure/

Market Pressure Scanner je samostatná čtvrtá webová aplikace nad již synchronizovanými **MT5 D1 OHLC + brokerovým tick volume**. Nemění BUY nebo SHORT pravidla, nepřidává exportér do MT5, nevytváří objednávky a nepotřebuje nový API klíč. Po otevření se automaticky přihlásí pomocí stávajícího zabezpečeného StockTool session cookie a spustí analýzu dostupných D1 datasetů.

**Pozor: NEJDE O SKUTEČNÝ ORDER FLOW ani důkaz Forced Selling.** Uzavřené svíčky ani brokerovo tick volume neprozradí identitu obchodníků, margin cally, nucené likvidace, short interest, burzovní objem ani tok objednávek. Všechny názvy Panika/Forced Selling jsou pouze cenové proxy.

### Soubory
- \`site/market-pressure/index.html\` – přehled indikací, filtrů a rizik.
- \`site/market-pressure/app.js\` – automatická relace, dávkové načítání, Top 10, detail, graf, kopírování tickerů, TXT souhrn.
- \`site/market-pressure/styles.css\` – samostatný barevný styl; základní webový design sdílený přes relativní CSS import.
- \`site/market-pressure/api/scan.php\` – přihlášené read-only PHP API, dávky po 30 z již uložených D1 datasetů; žádné další síťové zdroje.
- \`site/market-pressure/api/pressure_rules.php\` – čisté deterministické analytické funkce.
- \`tests/market_pressure_rules_test.php\` – syntetické regresní testy v PHP CLI bez klíčů a bez spojení na MT5.

### Přesné vzorce v0.1

Nejdříve vyžadujeme minimálně 80 validních D1 svíček a poslední svíčku maximálně 10 kalendářních dní starou. Historie s duplicitním časem nebo OHLC chybou do aktuálních žebříčků nepatří.

**Indikace panického výprodeje:**
- D1 změna Close vůči předchozímu Close ≤ -2 %.
- Denní cenový pohyb v absolutních jednotkách alespoň -1,25 **ATR14 před poslední svíčkou**.
- True Range poslední svíčky alespoň 1,4 předchozího ATR14.
- Close v dolních 32 % denního rozpětí High–Low.

**Forced selling – pouze cenová proxy:**
- D1 Close změna za 5 dokončených svíček nejvýše -7 % a za 20 nejvýše -10 %.
- Aspoň 4 z posledních 5 svíček mají Close níže než předchozí Close.
- Aspoň 2 z posledních 5 svíček jsou medvědí s True Range alespoň 1,3 předchozího ATR14.
- Toto **nedokazuje** nucenou likvidaci. Výstup je záměrně označen jako "Forced proxy".

**Vyčerpání:** Po aktuální nebo nedávné (max. 5 předchozích dokončených D1) panické/forced-proxy epizodě vytvoří aktuální svíčka nové Low předchozích 20 D1; její spodní knot tvoří alespoň 35 % rozpětí a Close skončí v horních 45 % rozpětí. Jde pouze o hypotézu možného vyčerpání, ne potvrzení bottom.

**Možný obrat:** V posledních 5 *předchozích* D1 se vyskytla panická/forced-proxy epizoda, aktuální svíčka je růstová, Close je nad High předchozího dne a v horních 32 % vlastního rozpětí. Žádná budoucí svíčka není použita (bez look-ahead).

**Pokračující prodejní tlak:** 5denní změna ≤ -4 %, alespoň 3 poklesové svíčky za 5 D1 a Close pod předchozím 20svíčkovým Low nebo v dolních 35 % rozpětí; případně nová panická/forced-proxy epizoda.

**Tlakové body 0–9:** součet +1 za propad posledního dne ≥2 %, +2 za cenový pohyb alespoň -1,25 ATR, +1 za rozpětí ≥1,4 ATR, +1 za Close v dolních 30 % rozpětí, +1 za tick volume ≥1,5× průměr 20 předchozích svíček, +1 za ≥4 poklesové dny z 5, +1 za pětidenní propad ≥7 %, +1 za Close pod Low předchozích 20 svíček. Je to **transparentní počet splněných podmínek**, nikoli pravděpodobnost výnosu, confidence level nebo "AI skóre".

Pokud tick volume chybí nebo je nula, poměr aktivity se vrací jako \`null\` a nepřičítají se body za objem. Brokerovo tick volume **není** skutečný burzovní volume.

### Výsledky webu
- Prodejní tlak / panika / forced proxy / vyčerpání / možné obraty / sledovat BUY / sledovat pokračování poklesu / všechny akcie.
- Každý ticker má vysvětlení, varování, 1/5/20 D změnu, rozpětí/ATR, close location, tick volume, stav dat a graf.
- Výběr Top 10, filtry, řazení a hledání; tickery v jednom řádku pro MT5.
- Společný textový report: Top 10 výprodej, Top 10 forced-selling proxy, Top 10 možné obraty/vyčerpání, Top 10 pokračující pokles.
- Žádná akce neotevírá obchody nebo nevytváří BUY/SHORT příkazy.

### Postup nasazení a ověření

1. Spusť na Windows svůj již používaný **Deploy-StockTool.bat v3**. Ten stáhne GitHub \`site/\` do \`/stocktool.eu/www/test/\` na FORPSI, bez přepsání soukromých MT5 dat.
2. Otevři https://www.stocktool.eu/test/market-pressure/ a v případě potřeby obnov \`Ctrl+F5\`.
3. Pokud platí StockTool relace z Data Manageru/BUY/SHORT, není potřeba klíč ani klikání; skener sám projde všechny dostupné D1 tickery. Jinak se přihlas pouze jednou.
4. Prověř filtry, detail, graf a TXT export. Pokud jsou všechny žebříčky prázdné, otevři filtr **Všechny**, zkontroluj aktuálnost posledních D1 svíček a dostupnost historie.

**Testování:** Syntetické offline PHP testy: \`php tests/market_pressure_rules_test.php\`. Ke spouštění není potřeba API klíč, MT5 ani internet. Po nasazení do FORPSI je nutné ověřit skutečné výsledky na brokerových datech. V0.1 nebyly ověřeny výsledky historického backtestu; slibovat jejich úspěšnost by bylo zavádějící.


---

## Backtesting Engine v0.1 – aplikace 05 (historická validace skenerů)

**Po nasazení:** https://www.stocktool.eu/test/backtesting/

**Architektura:** Čistá webová aplikace na FORPSI nad privátními D1 soubory z MT5 Data Manageru. Používá již fungující StockTool přihlášení, nepotřebuje žádný další CSV/EA/MT5 exportér, nemění žádnou databázi a neposílá obchodní příkazy.

### Soubory

- \`site/backtesting/index.html\` – parametry, srovnání strategií, výsledky, grafy a jednotlivé obchody.
- \`site/backtesting/styles.css\` – plně responzivní design.
- \`site/backtesting/app.js\` – dávkování, stop, win-rate/profit-factor, syntetický DD, filtrování, CSV/TXT, kopírování tickerů MT5.
- \`site/backtesting/api/run.php\` – autentizovaný read-only API, zpracování v dávkách 4 soubory při ALL / 8 při jedné strategii.
- \`site/backtesting/api/engine.php\` – serverový historický exekuční model, signály pouze z minulých/aktuálních uzavřených svíček.
- \`site/buy-scanner/api/buy_rules.php\` – přesně původní BUY funkce extrahované z live BUY skeneru; nyní je sdílí skener i backtest.
- \`site/short-scanner/api/short_rules.php\` a \`site/market-pressure/api/pressure_rules.php\` – existující nezměněná pravidla ostatních skenerů.
- \`tests/backtesting_engine_test.php\` – offline testy v PHP, včetně absence look-ahead, nákladů, shody se skenery a obchodních horizontů.
- \`.github/workflows/backtesting-tests.yml\` – automatická kontrola syntaxe a regresních testů při push.

### Testovatelné strategie (samostatně nebo ALL)

1. BUY Scanner (LONG): jen současné BUY kandidáty \`BREAKOUT\`, \`PULLBACK\`, \`TREND\`.
2. SHORT Scanner (SHORT): současné \`BREAKDOWN\`, \`FAILED_RALLY\`, \`DOWNTREND\` včetně již používaného veto filtru proti přehnanému riziku.
3. Market Pressure – obrat LONG: jen jeho historické \`watch_buy\` = REVERSAL/EXHAUSTION.
4. Market Pressure – pokračování SHORT: jen jeho historické \`watch_down\` = PANIC / FORCED_PROXY / CONTINUATION.

Pro historický den **i** se na serveru předá skeneru pouze pole \`bars[0..i]\`. Nezpřístupní se mu následující ceny ani pozdější volatilita. Pro historický výpočet se čas simulace nastaví na datum poslední známé uzavřené svíčky; aktuální desetidenní filtr čerstvosti tak nevyřazuje starší historické signály. Historická data mohou být zastaralá vůči dnešku; web je označí, ale nevymaže.

### Výslovný exekuční model a náklady

- Signál vzniká **po dokončení** svíčky \`i\` na základě tehdy známé historie.
- Obchod se otevírá na \`Open(i+1)\`, tedy až v další dostupné D1 svíčce.
- Při horizontu \`H\` uzavírá na \`Open(i+1+H)\`. Horizonty jsou pevně 1 / 5 / 10 / 20 / 60 obchodních D1 svíček (ne kalendářní dny). Všechny budoucí vstupy/výstupy jsou vyhodnoceny **až zpětně**.
- Jedna otevřená pozice maximálně pro daný symbol + strategii + horizont. Překryvné signály se přeskočí, žádné dokupování ani zdvojnásobování shortů.
- Nelze-li historický obchod plně uzavřít na existující svíčce, **nesmí** se počítat za výhru, prohru ani jako mark-to-market.
- \`spread\` je **celý** bid-ask spread v bps; polovina se promítá do vstupního a polovina do výstupního open. \`slippage\` na každém obchodu oboustranně; \`commission\` v bps za každou stranu. Náklady jsou modelované, nikoliv skutečný brokerův historický spread.
- LONG a SHORT mají opačné směry P/L. SHORT neobsahuje borrow fee, financování, margin, omezení shortability ani případné nucené uzavření pozice.

K dispozici je přepínání strategie a horizontu, srovnání 4×5 kombinací, rozpad po akciích, stránkovaný seznam konkrétních obchodů a **CSV celé historie uzavřených obchodů**. TXT obsahuje všechny výsledky a tickery ve formátu jedné řádky pro MT5.

### Přesná interpretace statistik

- **Win-rate** = podíl uzavřených obchodů s \`net_pct > 0\`.
- **Průměr a medián** = průměr/medián čistých % výnosů jednotlivých obchodů; každý obchod má v těchto číslech stejnou váhu.
- **Profit factor** = součet kladných čistých % / absolutní součet záporných čistých %. Pokud nejsou žádné ztráty, API/UI vrací \`—\` (nedostatek dat), ne automaticky nekonečno.
- **Max DD a graf** = syntetický index 100, kde se obchody uzavřené ve stejný den nejprve průměrují a následně skládají po dnech uzavření. Jde o ilustrativní **closed-trade event křivku**, nikoli live portfolio, skutečný kapitál, průběžný nerealizovaný zisk/ztrátu ani běžný portfolio drawdown! Nesmí se interpretovat jako skutečný maximální drawdown obchodního účtu.
- Do výpočtů nevstupují delistované nebo jinak nepřítomné akcie = **survivorship bias**, ani dividendy/splity bez ověřených upravených dat, takže absolutní výnosy mohou být zkreslené. Při ~300 D1 je počet historických signálů výrazně omezen, zejména pro strategii vyžadující 210 D1 warm-up a držení 60 D1.

### Dávkování / sdílený FORPSI hosting

Browser zpracuje postupně všechna D1 data ve více krátkých API požadavcích; nikdy nejediným PHP requestem na 685 × 4 × 5 testů. V režimu ALL jsou 4 soubory na batch, v režimu jednoho skeneru 8. Všechny horiony jednoho symbolu/strategie používají **jeden průchod historickými signály**. Je zde tlačítko **Zastavit výpočet**; nedokončený výsledek je zřetelně označen jako částečný a export úplného reportu je vypnutý.

**Poznámka:** režim ALL je výpočetně náročný i po dávkování; pro první ověření doporučujeme jednu strategii (BUY, 5 D1) a pak všechny. Aktualizace synchronizátoru MT5 ani nový API klíč nejsou potřeba.

### První nasazení a kontrola

1. Spusť svůj stávající **Deploy-StockTool.bat v3** a nahraj \`site/\` z GitHubu do \`/stocktool.eu/www/test/\`.
2. Otevři https://www.stocktool.eu/test/backtesting/ a obnov případně \`Ctrl+F5\`.
3. Vyber nejdřív BUY, horizont 5 D1 a třeba komise 1 / spread 5 / slippage 2 bps; spusť a zkontroluj počet výsledků i jednotlivé transakce.
4. Poté zkus ALL s horizonty 5 / 10 / 20 D1. Srovnej, zda jsou výnosy netto vždy nižší než gross (u stejných obchodů a kladných nákladů).
5. Při nulovém počtu obchodů ověř historii vybrané strategie a délku požadovaného horizontu – 60 D1 vyžaduje minimálně 271 dostupných svíček i pro jediný BUY/SHORT signál.

**Testy:** příkaz \`php tests/backtesting_engine_test.php\` na lokálním PC/CI. GitHub Actions automaticky zkontroluje PHP lint a JS \`node --check\`. Samotný reálný běh na FORPSI nad brokerovým datasety je potřeba ověřit po nasazení – ve vývojovém repozitáři nejsou osobní serverová data.



---

## Strategy Lab v0.1 – vizuální webový vývoj strategií (aplikace 07)

**Adresa po stávajícím Deploy v3:** https://www.stocktool.eu/test/strategy-lab/

Tato nová aplikace je inspirovaná **no-code jednoduchostí BlueCandle a výzkumným workflow StrategyQuant X**, ale jedná se o vlastní implementaci StockTool.eu. Nekopíruje jejich kód ani uživatelské rozhraní. Je to funkční **beta webový prototyp**, nikoli náhrada plného SQX, nepřipojuje automaticky živé obchodování a negeneruje hotové Expert Advisery.

### Architektura a zabezpečení

- \`site/strategy-lab/index.html\` – 4 funkční pracovní pohledy: Rule Builder, Generator, Databank, Robustness.
- \`site/strategy-lab/styles.css\` – responzivní webové analytické prostředí.
- \`site/strategy-lab/engine.js\` – čistě klientské historické indikátory a simulace obchodů, bez přístupu k MT5 a bez odesílání objednávek.
- \`site/strategy-lab/app.js\` – UI, data, společná autentizace, generátor, lokální knihovna, OOS, graf, CSV/JSON.
- \`tests/strategy_lab_engine_test.cjs\` – syntetické regresní testy indikátorů, vstupů/výstupů, SL/TP, nákladů, OOS, generatoru a Monte Carlo.
- \`.github/workflows/strategy-lab-tests.yml\` – automatické Node.js ověření při GitHub push.

Po otevření aplikace se obnoví **existující zabezpečená StockTool relace** přes Data Manager \`/test/data-manager/api/session.php\`, případně jednorázově ověří klíč přes \`login.php\`. Klíč se **nikam neukládá**. Aplikace získá D1 tickery přes \`datasets.php\` a OHLCV historii přes \`candles.php?symbol=…&timeframe=D1&limit=5000\`.

**Výpočty i generování probíhají výhradně v prohlížeči**. Server FORPSI pouze vrací již uložené D1 svíčky a není zatěžován statisíci požadavků na backtesting. Prohlížeč si může zapamatovat poslední ticker a maximálně 100 **konfigurací strategií** v \`localStorage\`; nikdy neobsahují API klíč ani heslo do MT5. Lze je exportovat/importovat do JSON souboru. Nepřihlašuje se na obchodní účet, neprovádí transakce ani nezakládá EAs.

### 1. Rule Builder

No-code kombinace **1–5 vstupních** a **0–5 výstupních** pravidel s AND/OR, LONG/SHORT, fixní maximální dobou držení 1–120 dokončených D1 svíček, volitelným SL/TP v %, spreadem/komisí/slippage v bps a definicí chronologického OOS úseku (15–50 % historie). Aktuální bloky:

- RSI(Period) pod/nad hranicí;
- Close nad/pod SMA či EMA;
- křížení dvou SMA nahoru/dolů;
- průraz maxima/minima *předchozích* N dokončených D1;
- ROC = změna ceny za N D1 nad/pod %;
- nárůst brokerova tick volume nad násobek průměru předchozích N D1;
- růstová/poklesová svíčka.

### 2. Exekuční model (D1 OHLC, bez look-ahead)

- Signál se vyhodnotí na **Close(i)** a vstup proběhne **až na Open(i+1)**. Není-li další svíčka, neotevírá se hypotetická pozice.
- SL a TP se vyhodnocují podle High/Low až po vstupu; pokud se na stejné D1 dotknou oba, uplatní se **konzervativně STOP jako první**. Neznáme intradenní posloupnost ceny. Při gapu přes stop se plní na horším OPEN, nikoli za nereálně příznivý SL.
- Pokud obchod neuzavřel SL/TP, vyhodnocuje se na konci D1 případné pravidlo výstupu a maximální horizont. Obě varianty uzavírají až na dalším D1 OPEN.
- Komise se odečítají na obou koncích obchodu; celý bid/ask spread se modeluje jako poloviční dopad při vstupu a výstupu, stejně tak slippage v bps pro obě strany. Jde o přibližný model brokerových nákladů.
- Jediný otevřený obchod na symbol a jeden testovaný konfigurační scénář. Fixní znovuinvestování není skutečné margin/risk řízení.
- Na konci historie rozpracované pozice nejsou vykazovány jako uzavřené výhry.
- Statistiky: počet uzavřených obchodů, úspěšnost netto, průměr, profit factor, čisté % z geometricky složených obchodů, drawdown syntetického uzavřeného „equity“ indexu. **Nejde o realistickou ekvitu portfolia**, protože chybí sizing, margin a mark-to-market.

### 3. Generator

Vygeneruje **30 / 100 / 200** reprodukovatelných konfigurací pravidel, period, horizontů a SL/TP podle zadaného seed; backtestuje všechny na právě načteném instrumentu. **Není to genetické programování ani strojové učení v rozsahu StrategyQuant X.**

- Generátor se řadí **výhradně podle IN-SAMPLE (trénovacího) výsledku**, a to s podmínkou minimálního počtu IS obchodů, PF a kladného průměrného netto výnosu.
- Posledních 15–50 % chronologické historie je OOS; jeho výsledek se uživateli pouze zobrazí a **nepoužívá se při řazení**.
- Obchody, které překračují hranici IS/OOS, se do statistik ani jednoho podvzorku nezahrnou.
- Z nejlepších variant může uživatel otevřít konfiguraci pro další test či ji uložit do Databank. Tím je OOS považováno za zkoumané; další ladění podle OOS by znamenalo přeoptimalizaci.

### 4. Databank a Robustness

- Databank ukládá výhradně **necitlivé konfigurace a malý statistický snapshot**, nikoli celou historii nebo klíč; maximum 100. Jednorázový import/export JSON.
- Robustness spouští 200 Monte Carlo **permutací pořadí uzavřených obchodů**, vrací medián a 95. percentil drawdownu. To **není** simulace nových cenových cest, tickových spreadů ani pravý Walk-Forward.
- Další stresový test zdvojnásobí nastavené komise, spread a slippage a přepočítá celý backtest. Zobrazuje OOS sample count a jasná varování, pokud je vzorek malý.

### Omezení v0.1 a roadmapa

Aplikace funguje **pouze pro jeden instrument a D1 data**; nepodporuje zatím H1/H4, multi-symbol testy, true tick engine, intradenní exekuci, portfolio-level drawdown, pravidelné přeoptimalizování, skutečný genetický algoritmus, Walk-Forward Matrix ani export plnohodnotného EA pro MT5. Tyto schopnosti mohou vznikat až dalšími iteracemi.

Pro seriózní testy nestačí 300 D1: doporučeno průběžně rozšířit historii, přidat delistované tituly, corporate-action upravené ceny, realizovatelné historické náklady a oddělený out-of-sample/unseen trh. Výsledky retrospektivního hledání nejsou důkazem ziskové obchodní strategie.

### Nasazení a testování

1. Spusť stávající **Deploy-StockTool.bat v3**, který stáhne aktuální GitHub \`main\` a nahraje \`site/\` do \`/stocktool.eu/www/test/\`.
2. Otevři https://www.stocktool.eu/test/strategy-lab/ a obnov případně \`Ctrl+F5\`.
3. Při platné StockTool relaci se vybere dostupný D1 ticker. V Rule Builderu zvol bloky a spusť backtest.
4. Pak vyzkoušej Generator → Databank → Robustness. Výsledky lze exportovat jako CSV historie obchodů či JSON definice strategie.
5. Pokud generátor nevrátí žádného kandidáta, znamená to, že žádná testovaná konfigurace nesplnila IS kritéria; není to chyba ani záruka absence příležitostí.

**Regresní test:** \`node tests/strategy_lab_engine_test.cjs\`. GitHub Actions kontroluje skripty a spouští test při změně souborů. Na lokálně simulovaných datech prošlo prvních 10 testů bez look-ahead a s konzervativní SL/TP logikou; první reálné nasazení na FORPSI je nutno ještě ověřit.


---

## Oddělení Equity MT5 a Market MT5 – nové řešení pro Strategy Lab

**Nyní máme dva datově nezávislé Data Managery:**

| Větev | Web | Data u FORPSI (mimo www) | Lokální MT5 |
|---|---|---|---|
| **EQUITY** (původní, beze změny) | https://www.stocktool.eu/test/data-manager/ | \`stocktool-private/data/\` | původní Darwinex MT5 pro akcie |
| **MARKET** (nová) | https://www.stocktool.eu/test/market-data/ | \`stocktool-private/market-data/\` | **jiný MT5 terminál** pro indexy/forex/kovy/komodity |

Oba používají **jedno existující zabezpečené přihlášení StockTool** a stejný soukromý API klíč, ale oddělené HTTPS API endpointy a samostatné serverové složky. **Akciová historie se nepřesouvá, nemaže ani nepřepisuje.**

### Které aplikace odkud čtou
- **BUY Scanner, SHORT Scanner, Market Pressure, stávající Backtesting Engine, JOHNY:** dál čtou výhradně **Equity Data Manager**, jak doposud.
- **Strategy Lab:** nyní čte výhradně **Market Data Manager** a nabízí originální intervaly **H1, H4, D1 a W1**, které opravdu existují v nové databázi.
- Databank konfigurací Strategy Lab používá nový název místního úložiště. Staré akciové konfigurace v prohlížeči zůstávají nedotčené, ale do nového market LABu se automaticky nekopírují.
- Výpočetní model LABu stále používá pouze dokončené OHLCV svíčky, vstup na dalším OPEN, konzervativní SL/TP a rozdělení IS/OOS. Všechny zvolené časové rámce jsou v backtestu **počet svíček**, nikoliv kalendářní dny.

### Synchronizace druhého MT5
Soubory:
- \`scripts/stocktool_mt5_sync.py\` – původní synchronizátor; zachovaný režim \`--universe stocks\`. Nově umí rozpoznávat i \`--universe markets\`.
- \`scripts/stocktool_mt5_market_sync.py\` – **samostatný market wrapper**, který vyžaduje explicitní \`--terminal-path\` a přesměruje data do \`/test/market-data/api/ingest.php\`.
- \`scripts/StockTool-MT5-MARKET-TEST.bat\` – první test až 8 instrumentů, originální H1/H4/D1/W1, 250 svíček/interval.
- \`scripts/StockTool-MT5-MARKET-START.bat\` – pravidelná synchronizace až 200 instrumentů, při prvním připojení až 1800 dokončených svíček/interval, cyklus 30 minut.
- \`tests/test_market_mt5_split.py\` a \`.github/workflows/market-data-split-tests.yml\` – automatické ověření oddělení MT5 dat, PHP syntaxe, Market LABu a bezpečnosti výběru instrumentů.

**Podstatné:** Windows launcher při prvním spuštění požádá o plnou cestu k \`terminal64.exe\` **DRUHÉHO** MetaTraderu 5, například \`C:\Program Files\Broker Markets\terminal64.exe\`. Tuto cestu uloží do \`%USERPROFILE%\.stocktool\market_terminal_path.txt\` (nejde o heslo). Konektor má separátní \`mt5_market_state_<hash>.json\`, takže si neplete ani potvrzené timestampy původních akciových dat.

Výběr \`markets\` hledá v cestách brokera indikace indexů, forexu, kovů, energií, komodit a dalších trhů. **Známé akciové složky jsou odfiltrovány i při Market Watch nebo ručním výběru**. Pokud broker pojmenovává složky jinak, můžeš použít přesný seznam symbolů v TXT:
\`\`\`bat
py -3 scripts\stocktool_mt5_market_sync.py --terminal-path "C:\TVUJ_DRUHY_MT5\terminal64.exe" --universe file --symbols-file "C:\MT5\moje-trhy.txt" --once --timeframes H1,H4,D1,W1 --initial-bars 1800
\`\`\`
Ve vstupním souboru musí být skutečné názvy symbolů dostupné u daného brokera, každý na vlastním řádku. Názvy typu \`US500\`, \`GER40\`, \`EURUSD\`, \`XAUUSD\` jsou pouze příklady; ne každý broker používá stejné značení.

### Postup nasazení
1. Nech běžet **stávající akciový MT5 a původní synchronizátor** – pokud fungují, nic v nich neměň.
2. Spusť \`Deploy-StockTool.bat v3\` a nasad novou webovou část \`site/\` na FORPSI.
3. Spusť **druhý terminál MT5**, přihlas účet s indexy/forexem/kovy a ověř, že obsahuje požadované trhy.
4. Stáhni a spusť \`StockTool-MT5-MARKET-TEST.bat\`; vyber přesné \`terminal64.exe\` druhého MT5. Přihlášení k API používá už uložený Windows DPAPI klíč. Launcher stáhne aktuální oba Python soubory z GitHubu.
5. Po potvrzení testovacích instrumentů v **Market Data Manageru** spusť \`StockTool-MT5-MARKET-START.bat\`. Ponech zapnutý odpovídající druhý MT5.
6. Otevři https://www.stocktool.eu/test/strategy-lab/ – na výběr budou trhy a uložené originální H1/H4/D1/W1 intervaly. Původní **Equity Data Manager** zůstane nedotčený.

**Bezpečnostní pojistka:** market sync kontroluje, že cílové API explicitně potvrzuje \`dataset=market\`; pokud ne, nepřenáší data. Stávající sync tento nový režim nepoužívá. Automatické testy jsou uložené, ale finální ověření přenosu z druhého lokálního MT5 a provoz na FORPSI je třeba provést až na uživatelově počítači.


---

## Market Intelligence v0.1 – News / Hot Stories / Calendar / Sessions (aplikace 09)

**Adresa po Deploy v3:** https://www.stocktool.eu/test/market-intelligence/

StockTool má novou samostatnou webovou aplikaci se čtyřmi záložkami, v tmavém stylu platformy. Zdrojová data se obnovují automaticky s **15minutovou mezipamětí** na serveru a nevyžadují StockTool API klíč (nejde o soukromá MT5 data). Propojení ze Strategy Lab a katalogu platformy.

### Autorská práva a přínos pro projekt

Forex Factory na https://www.forexfactory.com/notices zakazuje bez písemného souhlasu kopírování, republicaci a redistribuci zpráv, žebříčků, obsahu News a ekonomického kalendáře FEED. **StockTool proto nenačítá, neparsuje ani nekopíruje jejich obsah.** Nabízí na Forex Factory přímé odkazy a vlastní agregaci z *oficiálních primárních zdrojů*; není to zrcadlo jejich webu.

### Složky

- \`site/market-intelligence/index.html\` – všechny čtyři záložky; filtr zdroje, témat, období, důležitosti a přepínání.
- \`site/market-intelligence/styles.css\` – responzivní vizuální prostředí.
- \`site/market-intelligence/app.js\` – výpisy zpráv, datum Praha, bezpečné odkazy, kalendář a interaktivní hlavní forexové seance.
- \`site/market-intelligence/api/source_lib.php\` – parser oficiálních RSS, BEA JSON a BLS iCalendar; kategoriální čeština, hodnocení důležitosti a serverová cache.
- \`site/market-intelligence/api/overview.php\` – veřejné, kešované PHP API, pouze pevně zadané HTTPS zdroje, žádné uživatelské URL.
- \`tests/market_intelligence_test.php\` – offline syntetické testy parserů a přechodu časového pásma.
- \`.github/workflows/market-intelligence-tests.yml\` – GitHub CI.

### News a Hot Stories

Zdroje (pouze titulek, čas, vydavatel a odkaz na originál; nikoliv celé články):
- Fed: \`https://www.federalreserve.gov/feeds/press_all.xml\`
- ECB: \`https://www.ecb.europa.eu/rss/press.html\`
- BLS: \`https://www.bls.gov/feed/bls_latest.rss\`
- EIA: \`https://www.eia.gov/rss/todayinenergy.xml\`

Český **tematický kontext** je sestaven podle známých finančních témat: inflace, centrální banky, zaměstnanost, HDP, průmysl, ropa, zlato atd. To **není přesný překlad titulků**, ani investiční interpretace konkrétního článku. **Hot Stories jsou vlastní tematický výběr**, řazený podle významu sledovaného makro tématu a stáří článku; nejsou to Hot Stories přímo z Forex Factory ani pravá měření popularity trhu.

Každá zpráva má původní nadpis v angličtině a odkaz **Přeložit článek ↗** pro otevření v externím překladači, pokud server nemá nakonfigurovaný překladač. **Plný automatický překlad titulků přímo na stránce** je podporován *volitelně* přes soukromě nakonfigurovaný DeepL API klíč (bez jeho nastavení web titulky česky nepředstírá).

Pokud je DeepL k dispozici, webmaster může do existujícího neveřejného \`/stocktool.eu/stocktool-private/config.php\` přidat např. \`'deepl_api_key'=>'...'\`. Pro placený tarif lze přidat \`'deepl_endpoint'=>'pro'\`, jinak se použije oficiální DeepL Free endpoint. Klíč se nikdy nevystavuje na webu ani na GitHubu. Překlady až 24 titulků se požadují při aktualizaci zdrojů jedním serverovým požadavkem a ukládají do 15min cache. Pokud připojení DeepL selže, zobrazí se původní nadpis a české shrnutí tématu.

### Economic Calendar

Automaticky pracuje s primárními veřejnými plánovanými zveřejněními:
- BEA machine-readable JSON: \`https://apps.bea.gov/API/signup/release_dates.json\`;
- BLS oficiální kalendář iCalendar: \`https://www.bls.gov/schedule/news_release/bls.ics\`.

Převádí čas na **Europe/Prague** s automatickým CET/CEST a umožňuje filtry na 7 / 30 / 60 dní, zdroj a vlastní jednoduchou makro důležitost. Obsahuje převod známých názvů: CPI, NFP, PPI, HDP, osobní spotřeba, obchod USA, JOLTS.

**Není to celý světový FX kalendář.** BEA/BLS dodávají jen vybrané události USA, ne předpovědi, skutečné výsledky, historické revize, ECB sazby, eurozónu, UK ani Japonsko. Web proto nikdy nevymýšlí sloupce Actual/Forecast/Previous; pro kompletní světový kontext je přímo odkaz na originální Forex Factory kalendář. Důležitost \`high / medium / low\` představuje **StockTool heuristiku**, nikoliv proprietární impact rating FF.

### Trading Sessions

Čistě klientský časový přehled čtyř orientačních FX obchodních center:
- Sydney 09:00–18:00 místního času \`Australia/Sydney\`.
- Tokio 09:00–18:00 \`Asia/Tokyo\`.
- Londýn 08:00–17:00 \`Europe/London\`.
- New York 08:00–17:00 \`America/New_York\`.

Graf po 15 minutách ukazuje časovou osu od -12h do +12h v pražském čase. Jde o **hlavní časové zóny aktivity forexového trhu**, ne o přesné obchodní hodiny burz, CFD brokera, výjimky o svátcích nebo záruku likvidity. IANA pásma správně zohledňují rozdílný přechod na letní a zimní čas.

### Nasazení a validace

1. Spusť dosavadní **Deploy-StockTool.bat v3** a aktualizuj \`site/\` na FORPSI.
2. Otevři https://www.stocktool.eu/test/market-intelligence/ a případně dej \`Ctrl+F5\`.
3. Vyzkoušej všechny čtyři záložky, filtry a odkazy. Není potřeba nový MT5, API klíč ani soukromá konfigurace pro základní přehled.
4. Server musí mít PHP 8+, přístup na HTTPS k oficiálním zdrojům a právo zapisovat do \`stocktool-private/intelligence-cache\`. Pokud hosting nedovolí odchozí HTTPS nebo zdroj vrátí 403, aplikace zobrazí skutečnou nedostupnost; bez nahraných dat nevytváří umělý obsah.
5. Offline kontrola: \`php tests/market_intelligence_test.php\`; JS \`node --check site/market-intelligence/app.js\`. Pro GitHub je připravené CI.

**Důležité omezení v0.1:** Spuštění PHP na skutečném FORPSI nad externími feedy a DeepL (není nastaven) se ověří až po webovém deployi. Teprve pak uvidíme, zda všechny oficiální servery povolují přístup z IP hostingu. StockTool nezajišťuje licencovaný Bloomberg/Reuters/ForexFactory zpravodajský přenos.


---

## Calendar v2 – kompaktní ekonomický kalendář (Market Intelligence v0.2)

**Web po nasazení přes Deploy v3:** https://www.stocktool.eu/test/market-intelligence/?tab=calendar

Tato změna nahrazuje původní jednoduchou tabulku v aplikaci 09 kompaktním **Trader View**, vycházejícím z uživatelsky praktického rozvržení Forex Factory, ale s vlastním designem, logikou a oficiálními zdroji. **Forex Factory není scrapován, kopírován ani zrcadlen.** Záložky **News, Hot Stories a Sessions** zůstaly funkční.

### Funkce Calendar v2

- **Výchozí zhuštěný pracovní pohled** při otevření aplikace: místo vysokého úvodního dashboardu se hned zobrazuje kalendář.
- **Levý mini kalendář** s měsíčními šipkami, označením dnešního dne, vybraného období a dnů s událostmi.
- **Rychlá navigace:** dnes, zítra, tento/příští/minulý týden, tento/příští/minulý měsíc; klik na datum nastaví denní pohled.
- **Navigace nahoře:** minulé/následující období, dnes a **Up Next** (nejbližší budoucí událost vyhovující nastaveným filtrům).
- **Hustá tabulka 10 sloupců:** Den, Čas, Měna, Impact, Událost, Detail, Actual, Forecast, Previous, Graf. Události se řadí chronologicky a sdružují do samostatných denních bloků.
- **Vyhledávání a kombinované filtry:** měna, tematická důležitost, kategorie, instituce, nadcházející události, přepínač Compact/Insight.
- **Detail události:** český standardizovaný název, případný originál, obecný český tematický kontext, původní zdroj a případné dostupné výsledky. Žádné odhadované obchodní signály.
- **Časová pásma:** Praha \`Europe/Prague\` s automatickým CET/CEST, UTC nebo ručně nastavený fixní UTC offset pro druhý MT5. Brokerův offset si musí uživatel ověřit (nelze bezpečně odhadnout DST nastavení každého brokera).
- **Deep linky:** \`?tab=calendar&date=2026-11-18&event=<64hex>\`; Strategy Lab na konkrétní makro událost odkazuje přímo.
- **Omezení výchozího pohledu** na oficiální zveřejnění BEA/BLS USA (typicky USD). Ostatní země/měny se objeví až po přidání oficiálního nebo licencovaného zdroje. Prázdné řádky se nevytváří. Odkaz na původní globální kalendář Forex Factory je vždy dostupný.

**Interpretace Actual / Forecast / Previous:** Stávající BEA/BLS feedy poskytují plánované termíny. Neobsahují v tomto exportu výsledky ani konsensus. Prázdná hodnota se proto zobrazí jako \`—\`, zatímco skutečná numerická nula se zobrazuje jako \`0\`. Barevný výsledek proti konsenzu je dovolen pouze při existenci jak dvou hodnot, tak explicitně ověřeného významu směru překvapení (\`better_direction\` od legitimního poskytovatele). Čísla, historii ani grafy nesmíme vytvářet heuristicky.

### Technické změny

- \`site/market-intelligence/index.html\` – nové HTML pracovní prostředí.
- \`site/market-intelligence/styles.css\` – hustá tabulka, mini kalendář, panely, kompaktní režim, mobilní layout.
- \`site/market-intelligence/calendar-core.js\` – čisté funkce pro datum, ISO týdny, CET/CEST, filtry a up-next.
- \`site/market-intelligence/calendar-v2.js\` – přepínání období, ovládání, rozbalovací detail a tabulka. Nevyužívá HTML injekci z externího zdroje: uživatelské texty a názvy událostí se vkládají pomocí \`textContent\`.
- \`site/market-intelligence/app.js\` – NEWS/HOT/SESSIONS dále běží jako předtím; na \`stocktool:calendar-data\` předává calendar-v2 pouze jednu společnou serverovou odpověď.
- \`site/market-intelligence/api/source_lib.php\` – pro BEA/BLS uchovává dostupné termíny přibližně 13 měsíců zpětně i dopředu, aby fungovala historická navigace.
- \`site/market-intelligence/api/overview.php\` – zvýšen limit událostí na 1200, nová cache \`overview_official_v2\` pro okamžitou invalidaci staršího 65denního výběru, verze \`market-intelligence-v0.2\`.
- \`site/strategy-lab/app.js\` a \`site/strategy-lab/index.html\` – makro upozornění odkazuje na přesné datum a id události v Calendar v2.
- \`tests/calendar_v2_test.cjs\` – 11 offline regresních testů zahrnuje DST, datum, týdny, filtry, nulové hodnoty.
- \`tests/calendar_v2_ui_test.cjs\` – bez externích závislostí testuje mini kalendář, event feed, Up Next, tabulku, rozbalení detailu a filtry.
- \`.github/workflows/market-intelligence-tests.yml\` – doplněno ověření obou nových JS modulů a obou testů.

### Jak vyzkoušet

1. Spustit stávající \`Deploy-StockTool.bat v3\` do \`/stocktool.eu/www/test/\`.
2. Otevřít https://www.stocktool.eu/test/market-intelligence/?tab=calendar a stisknout \`Ctrl+F5\`.
3. Vyzkoušet šipky týdne, kalendář vlevo, filtry a tlačítko \`Up Next\`.
4. Otevřít detail některého skutečně dostupného amerického zveřejnění, ověřit originál a český čas.
5. V Market Data → Strategy Lab kliknout na nejbližší událost: měl by se otevřít přímo detail stejné události v Calendar v2.
6. Pokud zůstanou tabulky prázdné, ověřit PHP odchozí HTTPS na BEA/BLS a stav zdrojů; nesnažit se prázdné údaje nahradit simulovanými termíny.

Testy: \`node tests/calendar_v2_test.cjs\` a \`node tests/calendar_v2_ui_test.cjs\`; Python/MT5 synchronizátor ani původní akciové analýzy se nemění. Ověření nových endpointů na reálném FORPSI hostingu je stále nutné po nasazení.


---

## Market Intelligence v0.3 – oprava češtiny a mezinárodního kalendáře

**Web po ručním Deploy v3:** https://www.stocktool.eu/test/market-intelligence/

- **News + Hot Stories:** české zobrazení před anglickým originálem. Přesný překlad vzniká z volitelně nakonfigurovaného DeepL nebo nově z veřejné služby MyMemory, omezované na 3200 znaků za UTC den a nejvýše 12 nových veřejných titulků na jednu aktualizaci. Trvalá cache překladů leží mimo www ve stocktool-private/intelligence-cache. Při nedostupném překladači je jako české shrnutí uvedeno pouze bezpečně určitelné makrotéma, nikoli předstíraný přesný překlad. Originální anglický titulek zůstává pro ověření.
- **Calendar:** veřejné API ShowMyTrades přináší do vlastní české tabulky události pro USD, EUR, GBP, JPY, AUD, NZD, CAD, CHF a CNY, včetně skutečnosti/odhadu/předchozí hodnoty tam, kde jsou dostupné. Vždy je zobrazen původ dat a viditelný odkaz na zdroj. Oficiální BEA/BLS zůstávají jako záloha a pro širší časové období, ale bez konsensu.
- **Světový kalendář:** samostatný volitelný režim využívá přímo autorizovaný bezplatný widget TraderWaves s nezměněným viditelným autorským odkazem. Externí skript se načítá až po kliknutí návštěvníka, nikoli automaticky. Překlady a dostupnost tohoto iframe řeší jeho provider.
- **UI v češtině:** Zprávy, Hlavní témata, Kalendář, Seance, Skutečnost, Odhad, Předchozí, Důležitost, Další událost. Standardizované české popisy makro indikátorů zachovávají údaje meziročně/mezikvartálně/meziměsíčně.
- **Výkon:** paralelní načítání sedmi zdrojů PHP cURL multi s osmivteřinovým limitem; 15minutová serverová cache. MyMemory překlady se ukládají do neveřejné cache a mají konzervativní denní kvótu.
- **Bez zásahu do MT5:** Equity a Market Data Manager, Strategy Lab backtest, BUY a SHORT skenery zůstávají beze změny.
- **Právní hranice:** žádné kopírování Forex Factory; pouze veřejné nebo samostatně licencované/volně vložitelné zdroje s příslušným kreditem.

### Technické soubory a testování

Nové: site/market-intelligence/api/localization.php, translation.php a calendar_provider.php.
Aktualizované: source_lib.php, overview.php, index.html, app.js, calendar-v2.js, styles.css a tests/market_intelligence_test.php.

Po nasazení aktualizovaného site/ přes Deploy-StockTool.bat v3 zkontroluj stránku a API na FORPSI a obnov Ctrl+F5. Výpis musí být český, čísla pocházet z aktuálního providera, kredit musí být vidět. Pokud odchozí HTTPS z FORPSI není dostupné, zobrazuje se pouze oficiální kalendář BEA/BLS a nedoplněné hodnoty se nefalšují. Živý provoz FORPSI je třeba ověřit po deployi.

Automatický GitHub FTP deploy i Market Intelligence CI zůstávají manual-only kvůli dřívějším chybovým e-mailům. Testy lze spustit ručně: php tests/market_intelligence_test.php; node tests/calendar_v2_test.cjs; node tests/calendar_v2_ui_test.cjs.

Dokumentace zdrojů:
- https://showmytrades.com/docs/api/economic-calendar
- https://traderwaves.com/business/widgets/economic-calendar
- https://mymemory.translated.net/doc/usagelimits.php
