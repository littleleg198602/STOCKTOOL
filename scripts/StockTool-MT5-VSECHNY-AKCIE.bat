@echo off
setlocal EnableExtensions
title STOCKTOOL - VSECHNY AKCIE Z MT5
cd /d "%~dp0"
echo.
echo ====================================================
echo STOCKTOOL - AUTOMATICKA SYNCHRONIZACE VSECH AKCII
echo ====================================================
echo.
echo Zdroj: prihlaseny MetaTrader 5 na tomto pocitaci.
echo Nacitam dostupne akciove symboly automaticky.
echo Bez CSV, bez EA a bez zadavani API klice znovu.
echo.
py -3 --version
if errorlevel 1 goto failed
py -3 -c "import MetaTrader5" >nul 2>&1
if errorlevel 1 (
  echo Instaluji oficalni Python knihovnu MetaTrader5...
  py -3 -m pip install --disable-pip-version-check MetaTrader5
  if errorlevel 1 goto failed
)
py -3 -c "import truststore" >nul 2>&1
if errorlevel 1 (
  echo Instaluji bezpecne Windows HTTPS overovani...
  py -3 -m pip install --disable-pip-version-check truststore
  if errorlevel 1 goto failed
)
echo.
echo Stahuji aktualni konektor StockTool z GitHubu...
set "PYFILE=%TEMP%\StockTool_All_%RANDOM%_%RANDOM%.py"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/littleleg198602/STOCKTOOL/main/scripts/stocktool_mt5_sync.py' -OutFile '%PYFILE%'"
if errorlevel 1 goto failed
echo.
echo KROK 1/2 - Kontrola HTTPS a opravneni...
py -3 "%PYFILE%" --check-api
if errorlevel 1 goto cleanup_failed
echo.
echo KROK 2/2 - Synchronizace akcii z MT5...
echo Prvni pruchod stahne az 300 uzavrenych D1 svicek na akcii.
echo Dalsi aktualizace probiha automaticky pri bezicim MT5.
echo Bezpecne ukonceni: Ctrl+C
echo.
py -3 "%PYFILE%" --loop --universe stocks --max-symbols 700 --timeframe D1 --initial-bars 300 --interval-minutes 15
if errorlevel 1 goto cleanup_failed
del /q "%PYFILE%" >nul 2>&1
echo.
echo Synchronizace byla ukoncena.
pause
exit /b 0
:cleanup_failed
del /q "%PYFILE%" >nul 2>&1
:failed
echo.
echo CHYBA: Zkontroluj posledni hlaseni vyse. API klic neposilej.
echo Zadna data se pri chybe API nezacnou prenaset.
pause
exit /b 1
