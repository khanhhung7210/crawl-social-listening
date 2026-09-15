@echo off
setlocal EnableExtensions
chcp 65001 >nul

REM DIS film news continuous — all active films, loop vo han

cd /d "%~dp0..\.."

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%CD%\src"
set "PY=py -3"
set "CHROMEDRIVER_PATH="

echo ========================================
echo   DIS-news CONTINUOUS ^(all active^)
echo   Ctrl+C de dung
echo   Folder: %CD%
echo ========================================
echo.

:loop
echo.
echo [RUN] %PY% scripts\dis\crawl\crawl_film_news.py --import-db
echo       %date% %time%
echo.
%PY% scripts\dis\crawl\crawl_film_news.py --import-db
echo.
echo [DIS-news] round done exit=%ERRORLEVEL% — sleep 300s...
timeout /t 300 /nobreak
goto loop
