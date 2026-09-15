@echo off
setlocal EnableExtensions
chcp 65001 >nul

REM MKT News + App Reviews continuous — loop vo han, khong can Chrome

cd /d "%~dp0..\.."

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%CD%\src"
set "PY=py -3"
set "CHROMEDRIVER_PATH="

echo ========================================
echo   MKT-news CONTINUOUS
echo   Ctrl+C de dung
echo   Folder: %CD%
echo ========================================
echo.
echo [RUN] %PY% scripts\mkt\run_continuous.py news --import-db --sleep 300
echo.

%PY% scripts\mkt\run_continuous.py news --import-db --sleep 300
set "ERR=%ERRORLEVEL%"

echo.
if "%ERR%"=="0" (
  echo [OK] Stopped MKT-news
) else (
  echo [FAIL] MKT-news exit=%ERR%
)
echo.
pause
exit /b %ERR%
