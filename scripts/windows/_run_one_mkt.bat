@echo off
setlocal EnableExtensions
chcp 65001 >nul

REM Helper: 1 platform MKT trong 1 cua so.
REM Usage: _run_one_mkt.bat <platform> [--only-crawl]

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
echo   MKT platform=%~1
echo   Folder: %CD%
echo ========================================
echo.
echo [RUN] %PY% scripts\mkt\run_full_pipeline.py %*
echo.

%PY% scripts\mkt\run_full_pipeline.py %*
set "ERR=%ERRORLEVEL%"

echo.
if "%ERR%"=="0" (
  echo [OK] Xong MKT platform=%~1
) else (
  echo [FAIL] MKT platform=%~1 exit=%ERR%
)
echo.
pause
exit /b %ERR%
