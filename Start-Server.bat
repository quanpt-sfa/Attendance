@echo off
chcp 65001 >nul
title Diem danh - Server
cd /d "%~dp0"

:: Thử các lệnh Python phổ biến
for %%p in (py python python3) do (
    %%p --version >nul 2>&1 && (
        echo.
        echo   Server: http://localhost:8000
        echo   Ctrl+C de dung
        echo.
        %%p server.py
        goto :end
    )
)

:: Không tìm thấy
echo.
echo   [!] Khong tim thay Python
echo   Tai tai: https://www.python.org/downloads/
echo   Nho tich: Add Python to PATH
echo.

:end
pause
