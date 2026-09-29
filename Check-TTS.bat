@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Attendance - Check Offline TTS

set "TTS_PYTHON=%~dp0.venv-tts\Scripts\python.exe"

if not exist "%TTS_PYTHON%" (
    echo [NOT READY] Khong tim thay .venv-tts\Scripts\python.exe
    echo Chay Setup-TTS.bat khi co Internet.
    endlocal
    exit /b 1
)

"%TTS_PYTHON%" -c "import sys,tts_service; s=tts_service.get_status(); print('Voice: ' + s['voice']); print('Engine: ' + s['engine']); print('Version: ' + s['engine_version']); print('Backend: ' + s['backend']); print('Runtime: ' + ('READY' if s['runtime_present'] else 'MISSING')); print('Offline assets: ' + ('READY' if s['offline_assets_present'] else 'MISSING')); print('Cache: ' + str(s['cache_files']) + ' WAV file(s)'); sys.exit(0 if s['available'] else 1)"
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
    echo [OK] VieNeu offline TTS san sang.
) else (
    echo [NOT READY] Chay Setup-TTS.bat khi co Internet.
)

endlocal & exit /b %RC%
