@echo off
setlocal EnableExtensions
chcp 65001 >nul

REM ============================================================
REM  Social Listening Crawl Windows — CONTINUOUS (vo han)
REM  Double-click = 13 terminals, moi platform loop forever.
REM  Ctrl+C trong tung cua so de dung.
REM ============================================================

cd /d "%~dp0"
set "ROOT=%CD%"

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%CD%\src"
set "PY=py -3"
set "CHROMEDRIVER_PATH="
if exist "runtime\bin\chromedriver" (
  echo [WARN] Tim thay runtime\bin\chromedriver — neu la binary Mac hay xoa:
  echo        del runtime\bin\chromedriver
  echo.
)

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
  echo [WARN] Chua co .env — import/sentiment can Postgres.
  echo.
)

echo.
echo ========================================
echo   MKT + DIS CONTINUOUS ^(13 terminals^)
echo   Loop vo han — Ctrl+C de dung tung cua so
echo   Folder: %CD%
echo ========================================
echo.
echo [INFO] Chrome ports:
echo   MKT  Threads:9222 TikTok:9223 IG:9224 YT:9225 FB:9226 Maps:9227
echo   DIS  Threads:9232 TikTok:9233 IG:9234 YT:9235 FB:9236
echo   News ^(MKT+DIS^) khong can Chrome
echo.
echo [RUN] Mo 13 terminal continuous...
echo.

echo --- MKT ^(7^) ---
for %%P in (facebook tiktok threads instagram youtube google_maps) do (
  echo   - MKT-%%P
  start "MKT-%%P" cmd /k call "%ROOT%\scripts\windows\_run_one_mkt.bat" "%%P"
)
echo   - MKT-news
start "MKT-news" cmd /k call "%ROOT%\scripts\windows\_run_one_mkt_news.bat"

echo.
echo --- DIS ^(6^) ---
for %%P in (facebook tiktok threads instagram youtube) do (
  echo   - DIS-%%P
  start "DIS-%%P" cmd /k call "%ROOT%\scripts\windows\_run_one_dis.bat" "%%P"
)
echo   - DIS-news
start "DIS-news" cmd /k call "%ROOT%\scripts\windows\_run_one_dis_news.bat"

echo.
echo [OK] Da mo 13 cua so CONTINUOUS. Co the dong cua so nay.
echo.
pause
exit /b 0
