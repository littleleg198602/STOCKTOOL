@echo off
setlocal
title STOCKTOOL - MT5 BULK SYNC
cd /d "%~dp0"

echo ==================================================
echo STOCKTOOL - AUTOMATICKA SYNCHRONIZACE AKCII MT5
echo ==================================================
echo.
echo Nejprve overuji spojeni s FORPSI.
py -3 "%~dp0stocktool_mt5_sync.py" --check-api
if errorlevel 1 goto failed
echo.
echo Spojeni OK. Spoustim az 700 akcii na D1.
echo MetaTrader 5 musi byt otevren a prihlasen.
echo Ukonceni programu: Ctrl+C.
py -3 "%~dp0stocktool_mt5_sync.py" --loop --universe stocks --max-symbols 700 --timeframe D1 --initial-bars 300 --interval-minutes 15
if errorlevel 1 goto failed
echo.
echo Program ukoncen.
pause
exit /b 0

:failed
echo.
echo CHYBA: Zkontroluj vypis vyse. Neposilej API klic.
pause
exit /b 1
