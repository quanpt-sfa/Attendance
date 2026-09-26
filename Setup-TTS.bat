@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Attendance - Setup Offline Vietnamese TTS

set "VOICE_ID=vi_VN-vais1000-medium"
set "VOICE_REVISION=v1.0.0"
set "MODEL_SHA256=ec7c89e2c85f4d1edc24b6120c18aaf1bda614f06b511567eb9c7c0de15e2dab"
set "VOICE_DIR=%~dp0tts\voices"
set "MODEL_PATH=%VOICE_DIR%\%VOICE_ID%.onnx"
set "CONFIG_PATH=%VOICE_DIR%\%VOICE_ID%.onnx.json"
set "MODEL_URL=https://huggingface.co/rhasspy/piper-voices/resolve/%VOICE_REVISION%/vi/vi_VN/vais1000/medium/%VOICE_ID%.onnx?download=true"
set "CONFIG_URL=https://huggingface.co/rhasspy/piper-voices/resolve/%VOICE_REVISION%/vi/vi_VN/vais1000/medium/%VOICE_ID%.onnx.json?download=true"
set "TTS_PYTHON=%~dp0.venv-tts\Scripts\python.exe"
set "SMOKE_WAV=%TEMP%\attendance-tts-smoke-%RANDOM%-%RANDOM%.wav"

set "PYTHON_CMD="
for %%P in (py python python3) do (
    if not defined PYTHON_CMD (
        %%P --version >nul 2>&1 && set "PYTHON_CMD=%%P"
    )
)

if not defined PYTHON_CMD (
    echo.
    echo [LOI] Khong tim thay Python trong PATH.
    echo Cai Python 3.9+ x64 roi chay lai Setup-TTS.bat.
    exit /b 1
)

if not exist ".venv-tts\Scripts\python.exe" (
    echo [1/5] Tao moi truong TTS rieng .venv-tts ...
    %PYTHON_CMD% -m venv ".venv-tts"
    if errorlevel 1 goto :fail
) else (
    echo [1/5] .venv-tts da ton tai.
)

if not exist "%TTS_PYTHON%" (
    echo [LOI] Khong tim thay Python trong .venv-tts.
    goto :fail
)

echo [2/5] Cai piper-tts==1.8.0 trong .venv-tts ...
"%TTS_PYTHON%" -m pip install "piper-tts==1.8.0"
if errorlevel 1 goto :fail

if not exist "%VOICE_DIR%" mkdir "%VOICE_DIR%"

if not exist "%MODEL_PATH%" (
    echo [3/5] Tai model %VOICE_ID% ^(~63 MB^) ...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri $env:MODEL_URL -OutFile ($env:MODEL_PATH + '.download'); Move-Item -Force ($env:MODEL_PATH + '.download') $env:MODEL_PATH"
    if errorlevel 1 goto :fail
) else (
    echo [3/5] Model da ton tai.
)

if not exist "%CONFIG_PATH%" (
    echo [4/5] Tai cau hinh voice ...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri $env:CONFIG_URL -OutFile ($env:CONFIG_PATH + '.download'); Move-Item -Force ($env:CONFIG_PATH + '.download') $env:CONFIG_PATH"
    if errorlevel 1 goto :fail
) else (
    echo [4/5] Cau hinh voice da ton tai.
)

echo Kiem tra SHA-256 model ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$actual=(Get-FileHash -Algorithm SHA256 -LiteralPath $env:MODEL_PATH).Hash.ToLower(); if ($actual -ne $env:MODEL_SHA256) { Write-Error ('Sai SHA-256. Expected ' + $env:MODEL_SHA256 + ', got ' + $actual); exit 1 }"
if errorlevel 1 (
    echo [LOI] Model khong dung ban da pin. Xoa file model va chay lai Setup-TTS.bat.
    goto :fail
)

echo [5/5] Smoke test Piper local ...
if exist "%SMOKE_WAV%" del /q "%SMOKE_WAV%" >nul 2>&1
"%TTS_PYTHON%" tts_worker.py --smoke-test "%SMOKE_WAV%" --model "%MODEL_PATH%" --config "%CONFIG_PATH%"
if errorlevel 1 goto :fail
if not exist "%SMOKE_WAV%" (
    echo [LOI] Smoke test khong tao duoc WAV.
    goto :fail
)
del /q "%SMOKE_WAV%" >nul 2>&1

echo.
echo [OK] Offline Vietnamese TTS da san sang.
echo Voice: %VOICE_ID%
echo Sau buoc nay Attendance co the tao giong doc khi khong co Internet.
echo.
endlocal
exit /b 0

:fail
if exist "%SMOKE_WAV%" del /q "%SMOKE_WAV%" >nul 2>&1
if exist "%MODEL_PATH%.download" del /q "%MODEL_PATH%.download" >nul 2>&1
if exist "%CONFIG_PATH%.download" del /q "%CONFIG_PATH%.download" >nul 2>&1
echo.
echo [LOI] Cai dat Offline TTS khong hoan tat.
echo Kiem tra ket noi Internet, Python x64 va dung luong dia roi chay lai.
echo.
endlocal
exit /b 1
