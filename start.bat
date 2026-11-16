@echo off
setlocal
cd /d "%~dp0"
title Studsovet - Demo

where py >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python Launcher not found. Install Python 3.12 or 3.13 from python.org.
    echo During installation enable "Add Python to PATH".
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Creating virtual environment...
    py -3.12 -m venv .venv 2>nul
    if errorlevel 1 py -3.13 -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Python 3.12/3.13 was not found.
        pause
        exit /b 1
    )
)

echo [2/4] Installing/updating runtime dependencies...
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Dependency installation failed. Check internet access and requirements.txt.
    pause
    exit /b 1
)

echo [3/4] Checking local demo configuration...
.venv\Scripts\python.exe scripts\setup_windows.py
if errorlevel 1 (
    echo [ERROR] Initial configuration failed.
    pause
    exit /b 1
)

echo [4/4] Starting Studsovet through run.py...
echo Open http://127.0.0.1:5000/auth/login
.venv\Scripts\python.exe run.py
set EXIT_CODE=%ERRORLEVEL%
echo.
echo Studsovet stopped with exit code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
