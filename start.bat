@echo off
rem ============================================================
rem  Trip Planner Agent - One-click start
rem  Double-click this file to start the backend and open browser.
rem  The backend runs in its own window; close that window to stop.
rem ============================================================
cd /d "%~dp0"

rem Check if port 8000 is already running
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul
if %errorlevel%==0 (
    echo [INFO] Backend already running on port 8000. Opening browser...
    start "" http://localhost:8000
    exit /b 0
)

echo [INFO] Starting backend on http://localhost:8000 ...
start "TripPlanner Backend" cmd /k "venv\Scripts\python.exe -m backend.run --port 8000"

rem Wait a few seconds for the server to boot, then open browser
timeout /t 4 /nobreak >nul
start "" http://localhost:8000

echo [INFO] Backend started in a separate window.
echo [INFO] To stop the service, close that window or run stop.bat.
exit /b 0
