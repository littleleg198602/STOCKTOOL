@echo off
chcp 65001 >nul
title STOCKTOOL - MT5 TEST 10 AKCII
cd /d "%~dp0"
echo.
echo ===============================================
echo   STOCKTOOL - TEST PRIMYCH DAT Z MT5
echo   Maximalne 10 akcii, 300 D1 svíček na akcii.
echo ===============================================
echo.
echo Nezapomen mit otevreny a prihlaseny MetaTrader 5.
echo.
py -3 -c "import MetaTrader5" >nul 2>&1
if errorlevel 1 (
  echo Instaluji chybejici oficialni knihovnu MetaTrader5...
  py -3 -m pip install MetaTrader5
  if errorlevel 1 goto error
)
py -3 "%~dp0stocktool_mt5_sync.py" --once --universe stocks --max-symbols 10 --timeframe D1 --initial-bars 300
if errorlevel 1 goto error
echo.
echo Test ukoncen. Zkontroluj pocet odeslanych svíček vyse.
pause
exit /b 0
:error
echo.
echo Problem pri prvnim testu. Posli nam vypis chyby BEZ tajneho klice.
pause
exit /b 1
