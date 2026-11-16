@echo off
setlocal
cd /d "%~dp0desktop-app"
if errorlevel 1 (
  echo ERROR: Could not open the desktop-app folder.
  pause
  exit /b 1
)
where node >nul 2>nul
if errorlevel 1 (
  echo ERROR: Node.js LTS is required. Install Node.js LTS, then run this file again.
  pause
  exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
  echo ERROR: npm was not found. Reinstall Node.js LTS with npm enabled.
  pause
  exit /b 1
)
if not exist "node_modules\electron\dist\electron.exe" (
  echo First run: installing Electron and required packages...
  call npm install
  if errorlevel 1 goto install_failed
)
call npm start
exit /b %errorlevel%

:install_failed
echo ERROR: Package installation failed. Check your internet connection and npm registry access.
pause
exit /b 1
