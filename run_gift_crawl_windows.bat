@echo off
setlocal EnableExtensions
chcp 65001 >nul

REM ============================================================
REM  Gift Leads Crawl Windows — CONTINUOUS
REM  Double-click = mo Facebook + Threads (2 cua so).
REM  Ctrl+C trong tung cua so de dung.
REM ============================================================

cd /d "%~dp0"
set "ROOT=%CD%"

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%CD%\src"
set "PY=py -3"
set "CHROMEDRIVER_PATH="

where py >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Khong tim thay "py". Cai Python 3.10+ roi mo CMD moi.
  pause
  exit /b 1
)

%PY% --version
if errorlevel 1 (
  echo [ERROR] "py -3" khong chay duoc. Thu: py --list
  pause
  exit /b 1
)

if not exist "src\social_listening" (
  echo [ERROR] Chay file nay trong root repo social-listening.
  pause
  exit /b 1
)

if not exist ".env" (
  echo [WARN] Chua co .env — import/classify can Postgres.
  echo.
)

echo.
echo ========================================
echo   GIFT LEADS CONTINUOUS
echo   Loop vo han — Ctrl+C de dung tung cua so
echo   Folder: %CD%
echo ========================================
echo.
echo [INFO] Chrome ports Gift ^(MKT+20^):
echo   Threads:9242  TikTok:9243  IG:9244  YT:9245  FB:9246
echo.
echo [INFO] Keyword config: Admin -^> Gift Leads tren dashboard
echo.
echo [RUN] Seed gift_leads ^(skip neu da co^)...
%PY% scripts\mkt\seed_gift_leads_config.py
echo.

echo [RUN] Mo terminal continuous...
for %%P in (facebook threads) do (
  echo   - GIFT-%%P
  start "GIFT-%%P" cmd /k call "%ROOT%\scripts\windows\_run_one_gift.bat" "%%P"
)

echo.
echo [OK] Da mo cua so GIFT CONTINUOUS. Co the dong cua so nay.
echo   Them platform: scripts\windows\_run_one_gift.bat instagram
echo.
pause
exit /b 0
