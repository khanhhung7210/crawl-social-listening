@echo off
setlocal EnableExtensions
chcp 65001 >nul

REM MKT continuous — 1 platform / cua so, loop vo han.
REM Usage: _run_one_mkt.bat <platform>

cd /d "%~dp0..\.."

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%CD%\src"
set "PY=py -3"
set "CHROMEDRIVER_PATH="

if "%~1"=="" (
  echo [ERROR] Thieu platform
  pause
  exit /b 1
)

echo ========================================
echo   MKT CONTINUOUS platform=%~1
echo   Ctrl+C de dung
echo   Folder: %CD%
echo ========================================
echo.
echo [RUN] %PY% scripts\mkt\run_continuous.py %~1 --import-db --sleep 120
echo.

%PY% scripts\mkt\run_continuous.py %~1 --import-db --sleep 120
set "ERR=%ERRORLEVEL%"

echo.
if "%ERR%"=="0" (
  echo [OK] Stopped MKT platform=%~1
) else (
  echo [FAIL] MKT platform=%~1 exit=%ERR%
)
echo.
pause
exit /b %ERR%
