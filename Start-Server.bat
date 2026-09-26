@echo off
setlocal
chcp 65001 >nul
title Diem danh - Server
cd /d "%~dp0"

:: Port: tham so thu nhat, mac dinh 8000
set "PORT=%~1"
if not defined PORT set "PORT=8000"

:: Chi chap nhan port la so nguyen tu 1 den 65535
for /f "delims=0123456789" %%a in ("%PORT%") do goto :invalid_port
if "%PORT:~0,1%"=="0" goto :invalid_port
if not "%PORT:~5,1%"=="" goto :invalid_port
set /a PORT_NUM=%PORT% >nul 2>&1
if %PORT_NUM% LSS 1 goto :invalid_port
if %PORT_NUM% GTR 65535 goto :invalid_port
set "PORT=%PORT_NUM%"

:: Thu cac lenh Python pho bien
for %%p in (py python python3) do (
    %%p --version >nul 2>&1 && (
        echo.
        echo   Server: http://localhost:%PORT%
        echo   Ctrl+C de dung
        echo.
        %%p startup.py %PORT%
        goto :end
    )
)

:: Khong tim thay Python
echo.
echo   [!] Khong tim thay Python
echo   Tai tai: https://www.python.org/downloads/
echo   Nho tich: Add Python to PATH
echo.
goto :end

:invalid_port
echo.
echo   [!] Port khong hop le: %PORT%
echo   Cach dung: Start-Server.bat [PORT]
echo   Vi du:    Start-Server.bat 8080
echo   Port hop le: 1-65535
echo.
exit /b 1

:end
pause
endlocal
