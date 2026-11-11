@echo off
setlocal EnableExtensions
title STOCKTOOL - MT5 MULTI TF TEST 10
cd /d "%~dp0"
echo.
echo ==================================================
echo STOCKTOOL - TEST 10 AKCII
echo Casove ramce: H1 H4 D1 W1, bez CSV a bez EA.
echo ==================================================
echo.
echo Overuji Python...
py -3 --version
if errorlevel 1 goto failed
py -3 -c "import MetaTrader5" >nul 2>&1
if errorlevel 1 (
  echo Instaluji potrebnou knihovnu MetaTrader5...
  py -3 -m pip install --disable-pip-version-check MetaTrader5
  if errorlevel 1 goto failed
)
py -3 -c "import truststore" >nul 2>&1
if errorlevel 1 (
  echo Instaluji zabezpecene overovani certifikatu Windows...
  py -3 -m pip install --disable-pip-version-check truststore
  if errorlevel 1 goto failed
)
echo.
echo Nacitam aktualni konektor ze sveho GitHub projektu...
set "PYFILE=%TEMP%\StockTool_Multi_%RANDOM%_%RANDOM%.py"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/littleleg198602/STOCKTOOL/main/scripts/stocktool_mt5_sync.py' -OutFile '%PYFILE%'"
if errorlevel 1 goto failed
echo.
echo KROK 1/2: Bezpecna kontrola FORPSI a API klice.
py -3 "%PYFILE%" --check-api
if errorlevel 1 goto cleanup_failed
echo.
echo KROK 2/2: Cteni dat z beziciho MetaTraderu 5.
echo TEST: 10 akcii, vsechny 4 casove ramce. Bez trvaleho behu.
py -3 "%PYFILE%" --once --universe stocks --max-symbols 10 --timeframes H1,H4,D1,W1 --initial-bars 120
if errorlevel 1 goto cleanup_failed
del /q "%PYFILE%" >nul 2>&1
echo.
echo Test dokoncen. Na webu over prislusne casove ramce.
pause
exit /b 0
:cleanup_failed
del /q "%PYFILE%" >nul 2>&1
:failed
echo.
echo CHYBA: Zkontroluj vypis vyse. API klic nikomu neposilej.
pause
exit /b 1
