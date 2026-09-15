@echo off
setlocal EnableExtensions
chcp 65001 >nul

REM Helper: 1 platform DIS trong 1 cua so.
REM Usage: _run_one_dis.bat <platform> [--all-active|--film slug] [--import-db] ...

cd /d "%~dp0..\.."

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%CD%\src"
set "PY=py -3"

if "%~1"=="" (
  echo [ERROR] Thieu platform
  pause
  exit /b 1
)

echo ========================================
echo   DIS platform=%~1
echo   Folder: %CD%
echo ========================================
echo.
echo [RUN] %PY% scripts\dis\run_by_platform.py %*
echo.

%PY% scripts\dis\run_by_platform.py %*
set "ERR=%ERRORLEVEL%"

echo.
if "%ERR%"=="0" (
  echo [OK] Xong DIS platform=%~1
) else (
  echo [FAIL] DIS platform=%~1 exit=%ERR%
)
echo.
pause
exit /b %ERR%
