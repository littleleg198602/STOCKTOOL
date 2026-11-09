# STOCKTOOL

Základ projektu **stocktool.eu** – platforma webových finančních a analytických aplikací.

## Aktuální stav
- `site/index.html` – testovací stránka pro ověření GitHub → FORPSI.
- `.github/workflows/deploy-test.yml` – **ručně spouštěné** nasazení přes zabezpečené FTPS pouze do `/www/test/`.

## První nasazení
1. V GitHub repozitáři otevři Settings → Secrets and variables → Actions.
2. Vytvoř repository secret `FORPSI_FTP_PASSWORD` a vlož do něj heslo k FTP hostingu FORPSI. Heslo nikdy nevkládej do zdrojových souborů ani do chatu.
3. Otevři Actions → Deploy test to FORPSI → Run workflow (větev main).
4. Po úspěšném běhu ověř `https://stocktool.eu/test/`.

Použitý server: `ftpx.forpsi.com`, přihlašovací jméno: `f0476608.multi`, FTPS (explicitní TLS) na portu 21.

**Pozor:** Tento workflow nahrává jen obsah složky `site/` do vzdálené složky `/www/test/`. Nesahá na hlavní `/www/index.*` stránku.
