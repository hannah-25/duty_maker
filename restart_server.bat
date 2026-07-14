@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM 포트: 첫 번째 인자로 지정, 없으면 8000. 예) restart_server.bat 9000
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8000"

echo ============================================
echo   Duty Maker 서버 재시작  (포트 %PORT%)
echo ============================================
echo.
echo [1/2] 기존 서버 종료 중...

REM 해당 포트를 잡고 있는 프로세스를 종료 (reload 미사용이라 프로세스는 하나)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":%PORT% " ^| findstr LISTENING') do taskkill /F /PID %%p >nul 2>&1

timeout /t 1 /nobreak >nul
echo     완료.
echo.
echo [2/2] 서버 시작: http://127.0.0.1:%PORT%
echo     (이 창을 닫으면 서버가 종료됩니다. 코드를 바꾸면 이 파일을 다시 실행하세요.)
echo.

".venv\Scripts\python.exe" -m uvicorn api.main:app --port %PORT%

echo.
echo 서버가 종료되었습니다.
pause
