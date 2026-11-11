@echo off
setlocal EnableExtensions
title STOCKTOOL - OPRAVA SSL A TEST MT5
cd /d "%~dp0"
echo.
echo ============================================================
echo STOCKTOOL - OPRAVA HTTPS CERTIFIKATU A TEST 10 AKCII
echo ============================================================
echo.
echo Kontroluji Python a nastroj pro bezpecne certifikaty Windows...
py -3 --version
if errorlevel 1 goto failed
py -3 -c "import truststore" >nul 2>&1
if errorlevel 1 (
  echo Instaluji truststore - overeni HTTPS pomoci Windows...
  py -3 -m pip install --disable-pip-version-check truststore
  if errorlevel 1 goto failed
)
echo.
echo Stahuji aktualni opraveny StockTool konektor z GitHubu...
set "PYFILE=%TEMP%\StockTool_Fix_%RANDOM%_%RANDOM%.py"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/littleleg198602/STOCKTOOL/main/scripts/stocktool_mt5_sync.py' -OutFile '%PYFILE%'"
if errorlevel 1 goto failed
echo.
echo KROK 1 / 2 - Kontrola HTTPS a API klice (zadne svicky)...
py -3 "%PYFILE%" --check-api
if errorlevel 1 goto cleanup_failed
echo.
echo KROK 2 / 2 - Test prvnich 10 akcii z beziciho MT5...
py -3 "%PYFILE%" --once --universe stocks --max-symbols 10 --timeframe D1 --initial-bars 300
if errorlevel 1 goto cleanup_failed
echo.
echo HOTOVO: Testovaci synchronizace probehla. Zkontroluj pocet svicek ve vypisu.
del /q "%PYFILE%" >nul 2>&1
pause
exit /b 0
:cleanup_failed
del /q "%PYFILE%" >nul 2>&1
:failed
echo.
echo CHYBA: Posli screenshot vypisu. API klic na screenshot nedavej.
echo Certifikat NENI obchazen, overovani zustava zapnute.
pause
exit /b 1
