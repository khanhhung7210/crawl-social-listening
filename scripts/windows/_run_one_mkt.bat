@echo off
setlocal EnableExtensions
chcp 65001 >nul

REM Helper: 1 platform MKT trong 1 cua so. Goi tu run_crawl_windows.bat
REM Usage: _run_one_mkt.bat <platform> [--only-crawl]

cd /d "%~dp0..\.."

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%CD%\src"
set "PY=py -3"

set "PLATFORM=%~1"
if "%PLATFORM%"=="" (
  echo [ERROR] Thieu platform
  pause
  exit /b 1
)
shift
set "EXTRA=%*"

echo ========================================
echo   MKT platform=%PLATFORM%
echo   Folder: %CD%
echo ========================================
echo.
echo [RUN] %PY% scripts\mkt\run_full_pipeline.py %PLATFORM% %EXTRA%
echo.

%PY% scripts\mkt\run_full_pipeline.py %PLATFORM% %EXTRA%
set "ERR=%ERRORLEVEL%"

echo.
if "%ERR%"=="0" (
  echo [OK] Xong MKT platform=%PLATFORM%
) else (
  echo [FAIL] MKT platform=%PLATFORM% exit=%ERR%
)
echo.
pause
exit /b %ERR%
