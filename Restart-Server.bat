@echo off
echo ============================================
echo   Dang dung server cu...
echo ============================================

:: Kill any existing PowerShell servers on port 8000
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    echo Stopping process ID: %%a
    taskkill /F /PID %%a 2>nul
)

timeout /t 2 /nobreak >nul

echo.
echo ============================================
echo   Khoi dong lai server...
echo ============================================
echo.

start "Attendance Server" powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Server.ps1"

timeout /t 2 /nobreak >nul

echo.
echo ============================================
echo   Server da khoi dong!
echo   Truy cap: http://localhost:8000
echo ============================================
echo.
echo Nhan Ctrl+Shift+R trong trinh duyet de lam moi cache
echo.

:: Open browser
start http://localhost:8000
