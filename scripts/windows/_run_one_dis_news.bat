@echo off
setlocal EnableExtensions
chcp 65001 >nul

REM DIS film news ^(all active^) + import DB — khong can Chrome

cd /d "%~dp0..\.."

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%CD%\src"
set "PY=py -3"
set "CHROMEDRIVER_PATH="

echo ========================================
echo   DIS news ^(all active films^)
echo   Folder: %CD%
echo ========================================
echo.
echo [RUN] %PY% scripts\dis\crawl\crawl_film_news.py --import-db
echo.

%PY% scripts\dis\crawl\crawl_film_news.py --import-db
set "ERR=%ERRORLEVEL%"

echo.
if "%ERR%"=="0" (
  echo [OK] Xong DIS-news
) else (
  echo [FAIL] DIS-news exit=%ERR%
)
echo.
pause
exit /b %ERR%
