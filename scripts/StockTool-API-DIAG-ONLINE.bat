@echo off
setlocal
title STOCKTOOL - API DIAGNOSTIKA
echo.
echo =====================================================
echo    STOCKTOOL - KONTROLA SPOJENI S FORPSI
echo =====================================================
echo.
echo Nactu nejnovejsi diagnostiku z GitHubu.
echo Nic se do MT5 nezapisuje a na server se neposilaji ceny.
echo.
set "TMP_PY=%TEMP%\StockToolDiag_%RANDOM%_%RANDOM%.py"
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/littleleg198602/STOCKTOOL/main/scripts/stocktool_mt5_sync.py' -OutFile '%TMP_PY%'"
if errorlevel 1 goto download_failed
echo.
echo Spoustim kontrolu HTTPS a API klice.
py -3 "%TMP_PY%" --check-api
set "RESULT=%errorlevel%"
del /q "%TMP_PY%" >nul 2>&1
echo.
if not "%RESULT%"=="0" goto test_failed
echo OK: Spojeni na FORPSI je v poradku.
echo.
pause
exit /b 0
:download_failed
echo CHYBA: Nelze stahnout diagnostiku z GitHubu.
echo Over pristup k internetu.
goto end_error
:test_failed
echo CHYBA: Posli screenshot radku CHYBA nebo URLError.
echo NIKDY neposilej samotny API klic.
:end_error
echo.
pause
exit /b 1
