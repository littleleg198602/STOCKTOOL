@echo off
setlocal
title STOCKTOOL - MT5 TEST
cd /d "%~dp0"

echo ==================================================
echo STOCKTOOL - SPOJENI FORPSI A TEST 10 AKCII
echo ==================================================
echo.
echo Nejprve overim spojeni s API (bez odesilani svicek).
py -3 "%~dp0stocktool_mt5_sync.py" --check-api
if errorlevel 1 goto failed
echo.
echo API je OK. Spoustim synchronizaci 10 akcii z MT5.
echo MetaTrader 5 musi byt otevren a prihlasen.
py -3 "%~dp0stocktool_mt5_sync.py" --once --universe stocks --max-symbols 10 --timeframe D1 --initial-bars 300
if errorlevel 1 goto failed
echo.
echo Test dokoncen. Zkontroluj vysledek vyse.
pause
exit /b 0

:failed
echo.
echo Test se nepodaril. Posli screenshot chyby bez API klice.
echo Neni nutne znovu vytvaret klic na FORPSI.
pause
exit /b 1
