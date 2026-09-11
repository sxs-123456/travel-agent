@echo off
rem ============================================================
rem  Trip Planner Agent - One-click stop
rem  Double-click this file to stop the backend on port 8000.
rem ============================================================

set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    set FOUND=1
    echo [INFO] Stopping backend process PID %%a ...
    taskkill /F /PID %%a >nul 2>&1
)

if "%FOUND%"=="0" (
    echo [INFO] No backend process found on port 8000. Already stopped.
) else (
    echo [INFO] Backend stopped.
)
pause
