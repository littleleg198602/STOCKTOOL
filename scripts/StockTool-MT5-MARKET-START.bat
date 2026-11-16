@echo off
setlocal EnableExtensions DisableDelayedExpansion
title STOCKTOOL - MARKET MT5 SYNCHRONIZACE
cd /d "%~dp0"
echo.
echo ======================================================
echo STOCKTOOL - MARKET MT5 (SYNCHRONIZACE)
echo DRUHY TERMINAL - INDEXY / FOREX / KOVY / KOMODITY
echo PUVODNI AKCIOVY DATA MANAGER ZUSTAVA BEZE ZMENY.
echo ======================================================
echo.
set "USERCONF=%USERPROFILE%\.stocktool"
set "PATHFILE=%USERCONF%\market_terminal_path.txt"
if not exist "%USERCONF%" mkdir "%USERCONF%"
set "MARKET_MT5="
if defined STOCKTOOL_MARKET_MT5 set "MARKET_MT5=%STOCKTOOL_MARKET_MT5%"
if not defined MARKET_MT5 if exist "%PATHFILE%" set /p MARKET_MT5=<"%PATHFILE%"
if not defined MARKET_MT5 (
  echo Zadej cestu k DRUHEMU MT5, napriklad C:\Program Files\Broker MT5\terminal64.exe
  set /p "MARKET_MT5=Cesta k druhemu terminal64.exe: "
)
set "MARKET_MT5=%MARKET_MT5:"=%"
if not exist "%MARKET_MT5%" (
  echo CHYBA: Tento terminal neexistuje: "%MARKET_MT5%"
  goto failed
)
for %%F in ("%MARKET_MT5%") do if /I not "%%~nxF"=="terminal64.exe" (
  echo CHYBA: vyber soubor terminal64.exe, ne slozku.
  goto failed
)
> "%PATHFILE%" echo(%MARKET_MT5%
echo Pouzivam druhy MT5: "%MARKET_MT5%"
echo.
py -3 --version
if errorlevel 1 goto failed
py -3 -c "import MetaTrader5" >nul 2>&1
if errorlevel 1 (
  echo Instaluji MetaTrader5 Python...
  py -3 -m pip install --disable-pip-version-check MetaTrader5
  if errorlevel 1 goto failed
)
py -3 -c "import truststore" >nul 2>&1
if errorlevel 1 (
  py -3 -m pip install --disable-pip-version-check truststore
  if errorlevel 1 goto failed
)
set "WORK=%TEMP%\StockToolMarket_%RANDOM%_%RANDOM%"
mkdir "%WORK%"
if errorlevel 1 goto failed
echo Stahuji aktuální konektor z GitHubu...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop';$base='https://raw.githubusercontent.com/littleleg198602/STOCKTOOL/main/scripts/'; Invoke-WebRequest -UseBasicParsing -Uri ($base+'stocktool_mt5_sync.py') -OutFile '%WORK%\stocktool_mt5_sync.py'; Invoke-WebRequest -UseBasicParsing -Uri ($base+'stocktool_mt5_market_sync.py') -OutFile '%WORK%\stocktool_mt5_market_sync.py'"
if errorlevel 1 goto failed_cleanup
echo.
echo KROK 1/2: Overeni zabezpeceneho API Market Data Manageru.
py -3 "%WORK%\stocktool_mt5_market_sync.py" --check-api
if errorlevel 1 goto failed_cleanup
echo.
echo KROK 2/2: Spoustim samostatny Market MT5 sync.
echo Indexy, forex, kovy, komodity: H1 H4 D1 W1.
echo Pri prvnim nacteni max 1800 dokoncenych svicek na interval.
echo Ukonceni: Ctrl+C. Akciovy synchronizator muze bezet v jinem terminalu.
py -3 "%WORK%\stocktool_mt5_market_sync.py" --terminal-path "%MARKET_MT5%" --loop --max-symbols 200 --timeframes H1,H4,D1,W1 --initial-bars 1800 --interval-minutes 30
if errorlevel 1 goto failed_cleanup
echo.
echo HOTOVO. Data jsou v Market Data Manageru a Strategy Lab.
rmdir /s /q "%WORK%" >nul 2>&1
pause
exit /b 0
:failed_cleanup
if defined WORK if exist "%WORK%" rmdir /s /q "%WORK%" >nul 2>&1
:failed
echo.
echo CHYBA: Zkontroluj vypis. Nikdy neposilej API klic do chatu.
echo Pri neobvyklych nazvech slozek MT5 muzeme zvolit seznam instrumentu.
pause
exit /b 1
