@echo off
setlocal
title STOCKTOOL - FORPSI API KONTROLA
cd /d "%~dp0"
echo.
echo ================================================
echo STOCKTOOL - HTTPS / FORPSI / API KLIC DIAGNOSTIKA
echo ================================================
echo.
echo Bez kontaktu s MT5. Nic se na server neposila.
echo.
echo Kontroluji bezpecne overovani HTTPS certifikatu Windows...
py -3 -c "import truststore" >nul 2>&1
if errorlevel 1 (
  echo Instaluji knihovnu truststore pro systemove certifikaty...
  py -3 -m pip install --disable-pip-version-check truststore
  if errorlevel 1 goto failed
)
py -3 "%~dp0stocktool_mt5_sync.py" --check-api
if errorlevel 1 goto failed
echo.
echo OK: FORPSI spojeni a API klic funguje.
pause
exit /b 0

:failed
echo.
echo CHYBA: Udelej screenshot vyse. API klic neposilej.
pause
exit /b 1
