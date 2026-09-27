@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Attendance - Check Offline TTS

set "PYTHON_CMD="
for %%P in (py python python3) do (
    if not defined PYTHON_CMD (
        %%P --version >nul 2>&1 && set "PYTHON_CMD=%%P"
    )
)

if not defined PYTHON_CMD (
    echo [LOI] Khong tim thay Python trong PATH.
    exit /b 1
)

%PYTHON_CMD% -c "import tts_service; s=tts_service.get_status(); print('Piper: ' + ('READY' if s['available'] else 'NOT READY')); print('Voice: ' + s['voice']); print('Backend: ' + s['backend']); print('Runtime: ' + ('OK' if s['runtime_present'] else 'MISSING')); print('Model: ' + ('OK' if s['model_present'] else 'MISSING')); print('Cache: ' + str(s['cache_files']) + ' WAV file(s)')"
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo De cai dat/kiem tra lai runtime, chay Setup-TTS.bat.
) else (
    echo [LOI] Khong doc duoc trang thai TTS.
)

endlocal & exit /b %RC%
