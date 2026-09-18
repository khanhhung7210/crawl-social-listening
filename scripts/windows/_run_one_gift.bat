@echo off
setlocal EnableExtensions
chcp 65001 >nul

REM Gift Leads continuous — 1 platform / cua so, loop vo han.
REM Usage: _run_one_gift.bat <platform>
REM Platforms: facebook | threads | instagram | tiktok
REM Chrome ports Gift = MKT+20 (FB 9246, Threads 9242, …)

cd /d "%~dp0..\.."

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%CD%\src"
set "PY=py -3"
set "CHROMEDRIVER_PATH="
set "SOCIAL_CONFIG_SOURCE=db"
set "SOCIAL_LISTENING_PROCESS=gift_leads"
set "KEYWORD_PROCESS=gift_leads"

if "%~1"=="" (
  echo [ERROR] Thieu platform. Vi du: _run_one_gift.bat facebook
  pause
  exit /b 1
)

echo ========================================
echo   GIFT LEADS CONTINUOUS platform=%~1
echo   Ctrl+C de dung
echo   Folder: %CD%
echo   Keyword: Admin -^> Gift Leads ^(DB^)
echo ========================================
echo.
echo [RUN] %PY% scripts\mkt\run_continuous_gift_leads.py --platform %~1 --sleep 180
echo.

%PY% scripts\mkt\run_continuous_gift_leads.py --platform %~1 --sleep 180
set "ERR=%ERRORLEVEL%"

echo.
if "%ERR%"=="0" (
  echo [OK] Stopped GIFT platform=%~1
) else (
  echo [FAIL] GIFT platform=%~1 exit=%ERR%
)
echo.
pause
exit /b %ERR%
