@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Attendance - Setup Offline Vietnamese TTS

set "VOICE_ID=calmwoman3688"
set "VOICE_REVISION=62e57b18157ed213b3863a7a8a35b14d3404554b"
set "MODEL_SHA256=8db60d8afc50dc0921fd3a1b0b942813f44cc3744dbe2534617f2b8726096e7e"
set "CONFIG_SHA256=971f57f8d504223fee5b40d664f503cf769baf7db21f7d2ae0554a75d07de2f8"
set "PIPER_VERSION=1.8.0"
set "VOICE_DIR=%~dp0tts\voices"
set "MODEL_PATH=%VOICE_DIR%\%VOICE_ID%.onnx"
set "CONFIG_PATH=%VOICE_DIR%\%VOICE_ID%.onnx.json"
set "MODEL_URL=https://huggingface.co/sannht/vi_voice/resolve/%VOICE_REVISION%/tts-model/%VOICE_ID%.onnx?download=true"
set "CONFIG_URL=https://huggingface.co/sannht/vi_voice/resolve/%VOICE_REVISION%/tts-model/%VOICE_ID%.onnx.json?download=true"
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
    echo [1/6] Tao moi truong TTS rieng .venv-tts ...
    %PYTHON_CMD% -m venv ".venv-tts"
    if errorlevel 1 goto :fail
) else (
    echo [1/6] .venv-tts da ton tai.
)

if not exist "%TTS_PYTHON%" (
    echo [LOI] Khong tim thay Python trong .venv-tts.
    goto :fail
)

"%TTS_PYTHON%" -c "import importlib.metadata as m; raise SystemExit(0 if m.version('piper-tts') == '%PIPER_VERSION%' else 1)" >nul 2>&1
if errorlevel 1 (
    echo [2/6] Cai Piper TTS %PIPER_VERSION% trong .venv-tts ...
    "%TTS_PYTHON%" -m pip install --disable-pip-version-check --upgrade "piper-tts==%PIPER_VERSION%"
    if errorlevel 1 goto :fail
) else (
    echo [2/6] Piper TTS %PIPER_VERSION% da san sang.
)

if not exist "%VOICE_DIR%" mkdir "%VOICE_DIR%"

if not exist "%MODEL_PATH%" (
    echo [3/6] Tai NGHI-TTS %VOICE_ID% ^(~64 MB^) ...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri $env:MODEL_URL -OutFile ($env:MODEL_PATH + '.download'); Move-Item -Force ($env:MODEL_PATH + '.download') $env:MODEL_PATH"
    if errorlevel 1 goto :fail
) else (
    echo [3/6] Model da ton tai.
)

if not exist "%CONFIG_PATH%" (
    echo [4/6] Tai cau hinh voice ...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri $env:CONFIG_URL -OutFile ($env:CONFIG_PATH + '.download'); Move-Item -Force ($env:CONFIG_PATH + '.download') $env:CONFIG_PATH"
    if errorlevel 1 goto :fail
) else (
    echo [4/6] Cau hinh voice da ton tai.
)

echo [5/6] Kiem tra SHA-256 model va config ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$actual=(Get-FileHash -Algorithm SHA256 -LiteralPath $env:MODEL_PATH).Hash.ToLower(); if ($actual -ne $env:MODEL_SHA256) { Write-Error ('Sai SHA-256 model. Expected ' + $env:MODEL_SHA256 + ', got ' + $actual); exit 1 }"
if errorlevel 1 (
    echo [LOI] Model khong dung ban da pin. Xoa file model va chay lai Setup-TTS.bat.
    goto :fail
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$actual=(Get-FileHash -Algorithm SHA256 -LiteralPath $env:CONFIG_PATH).Hash.ToLower(); if ($actual -ne $env:CONFIG_SHA256) { Write-Error ('Sai SHA-256 config. Expected ' + $env:CONFIG_SHA256 + ', got ' + $actual); exit 1 }"
if errorlevel 1 (
    echo [LOI] Config khong dung ban da pin. Xoa file config va chay lai Setup-TTS.bat.
    goto :fail
)

echo [6/6] Smoke test ten sinh vien tieng Viet bang Piper TTS %PIPER_VERSION% ...
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
echo Voice: %VOICE_ID% ^(NGHI-TTS^)
echo Runtime: piper-tts %PIPER_VERSION% trong .venv-tts
echo Sentence splitting va phonemization duoc xu ly boi Piper frontend.
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
