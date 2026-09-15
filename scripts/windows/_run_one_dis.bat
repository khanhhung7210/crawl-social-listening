@echo off
setlocal EnableExtensions
chcp 65001 >nul

REM Helper: 1 platform DIS trong 1 cua so. Goi tu run_crawl_dis_windows.bat
REM Usage: _run_one_dis.bat <platform> [--all-active|--film slug] [--import-db|--no-import-db] ...

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
echo   DIS platform=%PLATFORM%
echo   Folder: %CD%
echo ========================================
echo.
echo [RUN] %PY% scripts\dis\run_by_platform.py %PLATFORM% %EXTRA%
echo.

%PY% scripts\dis\run_by_platform.py %PLATFORM% %EXTRA%
set "ERR=%ERRORLEVEL%"

echo.
if "%ERR%"=="0" (
  echo [OK] Xong DIS platform=%PLATFORM%
) else (
  echo [FAIL] DIS platform=%PLATFORM% exit=%ERR%
)
echo.
pause
exit /b %ERR%
