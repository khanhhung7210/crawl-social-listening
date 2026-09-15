@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul

REM ============================================================
REM  Social Listening - Crawl (Windows)
REM  Clone repo personal, copy .env, double-click this file.
REM
REM  Repo: khanhhung7210/crawl-social-listening  (branch socialDotAI)
REM ============================================================

cd /d "%~dp0"

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%CD%\src"

REM Windows: dung "py" launcher (khong dung "python")
set "PY=py -3"

where py >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Khong tim thay lenh "py" ^(Python Launcher^).
  echo.
  echo  Cai Python 3.10+ tu https://www.python.org/downloads/
  echo  ROI MO CMD MOI, thu:  py -3 --version
  echo.
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
  echo [ERROR] Khong thay thu muc src\social_listening
  echo         Hay chay file nay trong root repo social-listening.
  pause
  exit /b 1
)

if not exist ".env" (
  echo [WARN] Chua co file .env
  if exist ".env.example" (
    echo        Copy .env.example -^> .env roi dien PGHOST/PGUSER/PGPASSWORD...
  )
  echo.
)

echo.
echo ========================================
echo   Social Listening - Crawl Windows
echo   Folder: %CD%
echo   Python: %PY%
echo ========================================
echo.
echo  Chon platform:
echo    1^) facebook
echo    2^) tiktok
echo    3^) threads
echo    4^) instagram
echo    5^) youtube
echo    6^) google_maps
echo    7^) all ^(tat ca MXH + maps^)
echo    0^) thoat
echo.
set /p "CHOICE=Nhap so (1-7): "

if "%CHOICE%"=="0" exit /b 0
if "%CHOICE%"=="1" set "PLATFORM=facebook"
if "%CHOICE%"=="2" set "PLATFORM=tiktok"
if "%CHOICE%"=="3" set "PLATFORM=threads"
if "%CHOICE%"=="4" set "PLATFORM=instagram"
if "%CHOICE%"=="5" set "PLATFORM=youtube"
if "%CHOICE%"=="6" set "PLATFORM=google_maps"
if "%CHOICE%"=="7" set "PLATFORM=all"

if not defined PLATFORM (
  echo [ERROR] Lua chon khong hop le.
  pause
  exit /b 1
)

echo.
echo  Che do:
echo    1^) Full = crawl + filter + import DB + sentiment ^(khuyen nghi^)
echo    2^) Chi crawl/filter ^(khong import DB^)  [--only-crawl]
echo.
set /p "MODE=Nhap so (1-2, mac dinh 1): "
if "%MODE%"=="" set "MODE=1"

set "EXTRA="
if "%MODE%"=="2" set "EXTRA=--only-crawl"

echo.
echo [INFO] Can Chrome debug dang mo ^(port theo platform^).
echo        Facebook :9226  TikTok :9223  Threads :9222
echo        Instagram :9224 YouTube :9225  Maps :9227
echo.
echo [RUN] %PY% scripts\mkt\run_full_pipeline.py %PLATFORM% %EXTRA%
echo.

%PY% scripts\mkt\run_full_pipeline.py %PLATFORM% %EXTRA%
set "ERR=%ERRORLEVEL%"

echo.
if "%ERR%"=="0" (
  echo [OK] Xong platform=%PLATFORM%
  if "%MODE%"=="1" (
    echo       Da import DB + gan sentiment ^(neu .env Postgres OK^).
  ) else (
    echo       Chi co file JSON. Import sau:
    echo       %PY% scripts\source_b\import_keyword_mentions.py --film galaxy_cinema
  )
) else (
  echo [FAIL] Exit code %ERR%
)

echo.
pause
exit /b %ERR%
