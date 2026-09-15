@echo off
setlocal EnableExtensions
chcp 65001 >nul

REM ============================================================
REM  Social Listening Crawl Windows
REM  Double-click = full pipeline MKT + DIS, 1 terminal / platform.
REM  13 cua so: MKT 6 MXH + news | DIS 5 MXH + news
REM ============================================================

cd /d "%~dp0"
set "ROOT=%CD%"

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%CD%\src"
set "PY=py -3"

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
echo   MKT + DIS full pipeline ^(13 terminals^)
echo   Folder: %CD%
echo ========================================
echo.
echo [INFO] Chrome ports:
echo   MKT  Threads:9222 TikTok:9223 IG:9224 YT:9225 FB:9226 Maps:9227
echo   DIS  Threads:9232 TikTok:9233 IG:9234 YT:9235 FB:9236
echo   News ^(MKT+DIS^) khong can Chrome
echo.
echo [RUN] Mo 13 terminal...
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
  start "DIS-%%P" cmd /k call "%ROOT%\scripts\windows\_run_one_dis.bat" "%%P" --all-active --import-db --continue-on-error
)
echo   - DIS-news
start "DIS-news" cmd /k call "%ROOT%\scripts\windows\_run_one_dis_news.bat"

echo.
echo [OK] Da mo 13 cua so. Co the dong cua so nay.
echo.
pause
exit /b 0
