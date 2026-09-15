@echo off
setlocal EnableExtensions
chcp 65001 >nul

REM DIS continuous — 1 platform / cua so, --all-active, loop vo han.
REM Usage: _run_one_dis.bat <platform>

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
echo   DIS CONTINUOUS platform=%~1
echo   Ctrl+C de dung
echo   Folder: %CD%
echo ========================================
echo.
echo [RUN] %PY% scripts\dis\run_by_platform.py %~1 --all-active --import-db --continue-on-error --continuous --sleep 180
echo.

%PY% scripts\dis\run_by_platform.py %~1 --all-active --import-db --continue-on-error --continuous --sleep 180
set "ERR=%ERRORLEVEL%"

echo.
if "%ERR%"=="0" (
  echo [OK] Stopped DIS platform=%~1
) else (
  echo [FAIL] DIS platform=%~1 exit=%ERR%
)
echo.
pause
exit /b %ERR%
