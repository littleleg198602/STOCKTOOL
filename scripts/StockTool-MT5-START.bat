@echo off
chcp 65001 >nul
title STOCKTOOL - MT5 BULK SYNC
cd /d "%~dp0"
echo.
echo =======================================================
echo   STOCKTOOL - AUTOMATICKA SYNCHRONIZACE AKCII Z MT5
echo   Jedno spusteni - az 700 akcii - bez CSV a grafu
echo =======================================================
echo.
echo   Zkontroluj, ze MetaTrader 5 je spusteny a prihlaseny.
echo   Prvni synchronizace muze byt objemna podle brokera.
echo   Ukonceni synchronizace: Ctrl+C
echo.
py -3 -c "import MetaTrader5" >nul 2>&1
if errorlevel 1 (
  echo Knihovna MetaTrader5 neni dostupna. Instaluji pouze Python balicek...
  py -3 -m pip install MetaTrader5
  if errorlevel 1 goto error
)
py -3 "%~dp0stocktool_mt5_sync.py" --loop --universe stocks --max-symbols 700 --timeframe D1 --initial-bars 300 --interval-minutes 15
if errorlevel 1 goto error
echo.
echo Synchronizace ukoncena.
pause
exit /b 0
:error
echo.
echo CHYBA: Synchronizace nebyla uspesna. Precti hlasky vyse.
echo Pokud broker pouziva jine nazvy kategorii, spust diagnostiku:
echo py -3 "%~dp0stocktool_mt5_sync.py" --discover --universe marketwatch
pause
exit /b 1
