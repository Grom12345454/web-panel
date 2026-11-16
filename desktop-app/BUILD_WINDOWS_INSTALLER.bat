@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if errorlevel 1 (
  echo ERROR: Could not open the desktop-app folder.
  pause
  exit /b 1
)
where node >nul 2>nul
if errorlevel 1 (
  echo ERROR: Node.js 22 or newer is required.
  pause
  exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
  echo ERROR: npm was not found. Reinstall Node.js with npm enabled.
  pause
  exit /b 1
)

echo [1/6] Checking Node and npm versions...
node --version
call npm --version
if errorlevel 1 goto npm_version_failed

echo.
echo [2/6] Checking whether package-lock.json matches package.json...
set "REFRESH_LOCK=0"
if not exist package-lock.json set "REFRESH_LOCK=1"
if exist package-lock.json (
  node -e "const fs=require('fs');const p=JSON.parse(fs.readFileSync('package.json','utf8'));const l=JSON.parse(fs.readFileSync('package-lock.json','utf8'));const r=l.packages&&l.packages[''];if(!r||r.version!==p.version||JSON.stringify(r.devDependencies||{})!==JSON.stringify(p.devDependencies||{}))process.exit(1)"
  if errorlevel 1 set "REFRESH_LOCK=1"
)
if "%REFRESH_LOCK%"=="1" (
  echo Updating lockfile for this project version and its security overrides...
  call npm install --package-lock-only --ignore-scripts --no-audit --no-fund
  if errorlevel 1 goto lock_failed
)
if not exist package-lock.json goto lock_failed

echo.
echo [3/6] Installing the exact locked dependency tree...
call npm ci
if errorlevel 1 goto install_failed

echo.
echo [4/6] Checking the resolved packaging dependency tree...
call npm ls minimatch @electron/universal app-builder-lib electron-builder --all
if errorlevel 1 goto dependency_tree_failed

echo.
echo [5/6] Running full npm dependency security audit...
call npm audit --json > npm-audit-report.json
if errorlevel 1 goto security_failed
call npm audit --audit-level=low
if errorlevel 1 goto security_failed

echo.
echo [6/6] Building StudSovet Messenger Windows installer...
call npm run build:win
if errorlevel 1 goto build_failed

echo.
echo SUCCESS: dependency audit passed and installer was built.
echo Installer location: %CD%\release
explorer "%CD%\release"
pause
exit /b 0

:npm_version_failed
echo ERROR: npm was found but could not report its version. Reinstall Node.js with npm enabled.
pause
exit /b 1

:lock_failed
echo ERROR: Could not create or refresh package-lock.json.
echo Check npm registry access. Do not delete package.json or the overrides section.
pause
exit /b 1

:install_failed
echo ERROR: npm ci failed. Check the npm output and registry access.
pause
exit /b 1

:security_failed
echo SECURITY CHECK FAILED: npm reports unresolved advisories or could not complete the audit.
echo Audit details: %CD%\npm-audit-report.json
call npm ls minimatch @electron/universal app-builder-lib electron-builder --all > npm-security-dependency-tree.txt 2>&1
echo Dependency tree: %CD%\npm-security-dependency-tree.txt
echo The installer will NOT be built. Do not use npm audit fix --force.
pause
exit /b 1

:dependency_tree_failed
echo ERROR: npm dependency tree is inconsistent; build is blocked.
call npm ls minimatch @electron/universal app-builder-lib electron-builder --all > npm-security-dependency-tree.txt 2>&1
echo Dependency tree: %CD%\npm-security-dependency-tree.txt
pause
exit /b 1

:build_failed
echo ERROR: electron-builder failed. Review the build output above.
pause
exit /b 1
