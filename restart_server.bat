@echo off
cd /d "%~dp0"

set "PORT=%~1"
if "%PORT%"=="" set "PORT=8000"

echo ============================================
echo  Restarting Duty Maker Server (Port %PORT%)
echo ============================================
echo.
echo [1/2] Stopping existing server on port %PORT%...

for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT% " ^| findstr LISTENING') do taskkill /F /PID %%p >nul 2>&1

timeout /t 1 /nobreak >nul
echo      Done.
echo.
echo [2/2] Starting server: http://127.0.0.1:%PORT%
echo.

".venv\Scripts\python.exe" -m uvicorn api.main:app --port %PORT%

echo.
echo Server stopped.
pause