# JOHNY: Data Manager → GitHub Actions → StockTool

## Co tato verze přenáší

Výpočetní kód a původní lokální Streamlit UI pocházejí z uživatelem určené složky
`JOHNY-SKORE-mainNEW_6 - TESt-Uceni/market_checker_app` (import 2026-11-15).
Verze skórování zůstává `v2.5_uceni_score_audit`. Pravidla výpočtu nejsou přepsána
do PHP ani JavaScriptu. Vstup `external_ohlc` obchází terminál MT5 a používá D1
svíčky z Data Manageru; původní lokální způsob zůstává dostupný.

Web `site/johny/` zobrazuje signály, BUY přehled, zprávy, stav tréninku, detail akcie,
CSV a posledních 100 běhů. Není úplnou náhradou všech ovládacích prvků Streamlitu:
ruční konfigurace vah, správa výkazových providerů, grafy a import staré lokální
databáze zatím zůstávají v původním UI.

## Aktivace

1. Sloučit PR do `main`, potom spustit existující workflow **Deploy test to FORPSI**.
   Používá existující secret `FORPSI_FTP_PASSWORD`. Nové PHP endpointy musejí být
   nahrané dříve než první výpočet. Soukromou konfiguraci Data Manageru neměnit.
2. V repozitáři otevřít **Settings → Secrets and variables → Actions → New repository
   secret**, přidat `STOCKTOOL_API_KEY` se stejným klíčem, který používá Data Manager.
   Klíč neposílat v chatu ani nezapisovat do kódu. Workflows nemají možnost číst
   hodnoty GitHub Secrets zpět.
3. Na FORPSI musí PHP podporovat multipart upload databáze. Doporučená nastavení:
   `upload_max_filesize=128M`, `post_max_size=160M`, `memory_limit=256M`.
   Aplikace přijímá databázi do 128 MiB a výsledky do 16 MiB. Při nižším limitu
   se publikace zastaví; předchozí výsledky i historie zůstanou platné.
4. Otevřít **Actions → JOHNY - calculate scores → Run workflow**.
   První běh může použít `refresh_yahoo=25`, `train=true`. Zpracují se všechny D1
   akcie Data Manageru (do 1000); počet se nikdy potichu nezkracuje.
5. Otevřít `https://www.stocktool.eu/test/johny/`, přihlásit se stejným způsobem
   jako do Data Manageru a ověřit čas posledního dokončeného běhu.

Rozvrh není aktivován. Výpočet se spouští ručně v Actions. Web odkazuje na toto
spuštění; neobsahuje GitHub token ani nepředstírá vlastní tlačítko pro vzdálený start.

## Zdroje a zachování učení

- Data Manager: autentizované `datasets.php` a `candles.php`, pouze dokončené D1
  svíčky. Neplatná nebo více než 7 dní stará data jsou viditelně označena a nejsou
  použita jako současná technická historie. Výpadek API zastaví publikaci.
- Yahoo: volitelná dávka nejvýše 50 požadavků na metadata a 50 na upravené ceny
  v jednom běhu (včetně benchmarku). Původní cache, retry a rate-limit kontroly
  zůstávají aktivní. Další běhy postupně doplňují chybějící data. Nepřevádíme
  brokerovy tickery ručně na domnělé Yahoo symboly; použije se původní normalizace.
- RSS: volitelná Actions variable `STOCKTOOL_RSS_SOURCES`, jedna HTTPS URL na řádek,
  včetně podpory `{ticker}` jako v původní aplikaci. Bez nastavení je news modul
  vypnutý a má chybějící data, nikoli vymyšlené zprávy.
- Výkazy: worker používá již uložené výkazy v obnovené databázi. Tato první verze
  nepřidává jejich síťovou aktualizaci; bez dat se projeví původní kontrola pokrytí.
- Učení: původní `train_from_history` a validační brány. MT5 ceny nejsou označeny
  jako ceny upravené o splity/dividendy. Málo vzorků není úspěšný trénink. Přijatý
  model se uplatní od následujícího běhu. Začíná se novou historií; původní místní
  databáze se automaticky nenahrává ani nepřepisuje.

## Uložení a souběh

Data jsou mimo veřejný web v `/stocktool.eu/stocktool-private/johny/`.
Každá revize obsahuje uzavřený SQLite snapshot, výsledky a souhrn. Ukazatel na
aktuální revizi se změní až po dokončení všech zápisů. Worker načte konkrétní revizi
a ověří SHA-256 i SQLite `quick_check`. Souběžná publikace se zastaví na HTTP 409;
je nutné znovu obnovit stav a výpočet opakovat. Actions mají také společnou frontu.

Čtení výsledků využívá sdílenou přihlašovací session. Stažení databáze a publikace
vyžadují původní klíč v hlavičce. Klíč se neposílá v URL ani při HTTP redirectu.
Databáze a výsledky nejsou GitHub artifacts ani verzované soubory.

Revize se zatím automaticky nemažou: je nutné sledovat místo na FORPSI a zálohovat
soukromý adresář. Limity délky běhu a spotřeba Actions závisí na účtu GitHubu.

## Ověření

`python -m unittest discover -s tests -v` zahrnuje původní regresní sadu i nové testy
externího zdroje a integrace PHP. PHP integrační testy vyžadují PHP CLI; bez něj se
lokálně přeskočí, ale workflow `JOHNY - checks` je vyžaduje. CI kontroluje také syntax
PHP/JavaScriptu. Testy nevyžadují živý StockTool, Yahoo ani skutečné tajné hodnoty.
