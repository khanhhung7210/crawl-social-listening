@echo off
setlocal EnableExtensions
chcp 65001 >nul

REM MKT News + App Reviews + classify (1 lan, khong can Chrome)

cd /d "%~dp0..\.."

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%CD%\src"
set "PY=py -3"

echo ========================================
echo   MKT news + app reviews
echo   Folder: %CD%
echo ========================================
echo.
echo [RUN] %PY% scripts\mkt\run_continuous.py news --import-db --max-rounds 1
echo.

%PY% scripts\mkt\run_continuous.py news --import-db --max-rounds 1
set "ERR=%ERRORLEVEL%"

echo.
if "%ERR%"=="0" (
  echo [OK] Xong MKT-news
) else (
  echo [FAIL] MKT-news exit=%ERR%
)
echo.
pause
exit /b %ERR%
