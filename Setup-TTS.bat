@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Attendance - Setup Offline Vietnamese TTS

set "VOICE_ID=calmwoman3688"
set "VOICE_REVISION=62e57b18157ed213b3863a7a8a35b14d3404554b"
set "MODEL_SHA256=8db60d8afc50dc0921fd3a1b0b942813f44cc3744dbe2534617f2b8726096e7e"
set "CONFIG_SHA256=971f57f8d504223fee5b40d664f503cf769baf7db21f7d2ae0554a75d07de2f8"
set "VOICE_DIR=%~dp0tts\voices"
set "MODEL_PATH=%VOICE_DIR%\%VOICE_ID%.onnx"
set "CONFIG_PATH=%VOICE_DIR%\%VOICE_ID%.onnx.json"
set "MODEL_URL=https://huggingface.co/sannht/vi_voice/resolve/%VOICE_REVISION%/tts-model/%VOICE_ID%.onnx?download=true"
set "CONFIG_URL=https://huggingface.co/sannht/vi_voice/resolve/%VOICE_REVISION%/tts-model/%VOICE_ID%.onnx.json?download=true"

set "PIPER_VERSION=1.8.0"
set "TTS_PYTHON=%~dp0.venv-tts\Scripts\python.exe"

set "RUNTIME_ROOT=%~dp0tts\runtime"
set "NODE_VERSION=22.23.3"
set "NODE_ZIP_NAME=node-v%NODE_VERSION%-win-x64.zip"
set "NODE_DIR=%RUNTIME_ROOT%\node"
set "NODE_EXE=%NODE_DIR%\node.exe"
set "NPM_CMD=%NODE_DIR%\npm.cmd"
set "NODE_URL=https://nodejs.org/download/release/v%NODE_VERSION%/%NODE_ZIP_NAME%"
set "NODE_SHASUMS_URL=https://nodejs.org/download/release/v%NODE_VERSION%/SHASUMS256.txt"
set "NODE_ZIP=%TEMP%\attendance-node-%NODE_VERSION%-%RANDOM%-%RANDOM%.zip"
set "NODE_SHASUMS=%TEMP%\attendance-node-shasums-%RANDOM%-%RANDOM%.txt"
set "NODE_EXTRACT=%TEMP%\attendance-node-extract-%RANDOM%-%RANDOM%"

set "NGHI_COMMIT=46d160da32041f7e176607203b958069265df7da"
set "NGHI_ROOT=%RUNTIME_ROOT%\nghitts"
set "NGHI_URL=https://github.com/nghimestudio/nghitts.git"
set "NGHI_MARKER=%NGHI_ROOT%\.attendance-nghi-commit"
set "NGHI_ADAPTER=%~dp0tts\nghi_frontend.mjs"

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

if not exist "%NGHI_ADAPTER%" (
    echo [LOI] Khong tim thay tts\nghi_frontend.mjs trong bo ma Attendance.
    exit /b 1
)

if not exist "%RUNTIME_ROOT%" mkdir "%RUNTIME_ROOT%"
if not exist "%VOICE_DIR%" mkdir "%VOICE_DIR%"

if not exist ".venv-tts\Scripts\python.exe" (
    echo [1/8] Tao moi truong TTS rieng .venv-tts ...
    %PYTHON_CMD% -m venv ".venv-tts"
    if errorlevel 1 goto :fail
) else (
    echo [1/8] .venv-tts da ton tai.
)

if not exist "%TTS_PYTHON%" (
    echo [LOI] Khong tim thay Python trong .venv-tts.
    goto :fail
)

echo [2/8] Cai Piper Python inference %PIPER_VERSION% ...
"%TTS_PYTHON%" -m pip install --disable-pip-version-check "piper-tts==%PIPER_VERSION%"
if errorlevel 1 goto :fail
"%TTS_PYTHON%" -c "import importlib.metadata; assert importlib.metadata.version('piper-tts') == '%PIPER_VERSION%'"
if errorlevel 1 goto :fail

if not exist "%NODE_EXE%" (
    echo [3/8] Tai Node.js portable %NODE_VERSION% va kiem tra SHA-256 ...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri $env:NODE_URL -OutFile $env:NODE_ZIP; Invoke-WebRequest -UseBasicParsing -Uri $env:NODE_SHASUMS_URL -OutFile $env:NODE_SHASUMS; $pattern='^([0-9a-fA-F]{64})\s+' + [regex]::Escape($env:NODE_ZIP_NAME) + '$'; $match=Select-String -LiteralPath $env:NODE_SHASUMS -Pattern $pattern | Select-Object -First 1; if (-not $match) { throw ('Khong tim thay hash cho ' + $env:NODE_ZIP_NAME) }; $expected=[regex]::Match($match.Line,$pattern).Groups[1].Value.ToLower(); $actual=(Get-FileHash -Algorithm SHA256 -LiteralPath $env:NODE_ZIP).Hash.ToLower(); if ($actual -ne $expected) { throw ('Sai SHA-256 Node ZIP. Expected ' + $expected + ', got ' + $actual) }; if (Test-Path -LiteralPath $env:NODE_EXTRACT) { Remove-Item -Recurse -Force -LiteralPath $env:NODE_EXTRACT }; Expand-Archive -LiteralPath $env:NODE_ZIP -DestinationPath $env:NODE_EXTRACT -Force; $src=Join-Path $env:NODE_EXTRACT ('node-v' + $env:NODE_VERSION + '-win-x64'); if (-not (Test-Path -LiteralPath (Join-Path $src 'node.exe'))) { throw 'Node ZIP khong co node.exe nhu mong doi' }; New-Item -ItemType Directory -Force -Path $env:NODE_DIR | Out-Null; Copy-Item -Path (Join-Path $src '*') -Destination $env:NODE_DIR -Recurse -Force"
    if errorlevel 1 goto :fail
) else (
    echo [3/8] Node.js portable da ton tai.
)

if not exist "%NODE_EXE%" (
    echo [LOI] Khong tim thay Node portable sau khi cai dat.
    goto :fail
)
if not exist "%NPM_CMD%" (
    echo [LOI] Khong tim thay npm.cmd trong Node portable.
    goto :fail
)
"%NODE_EXE%" --version | findstr /x /c:"v%NODE_VERSION%" >nul
if errorlevel 1 (
    echo [LOI] Node runtime khong dung version %NODE_VERSION%.
    goto :fail
)

where git >nul 2>&1
if errorlevel 1 (
    echo [LOI] Setup can Git de lay NGHI-TTS dung commit da pin.
    echo Cai Git for Windows roi chay lai Setup-TTS.bat. Sau setup, synthesis khong can Internet.
    goto :fail
)

if not exist "%NGHI_ROOT%\.git" (
    echo [4/8] Clone NGHI-TTS ...
    if exist "%NGHI_ROOT%" rmdir /s /q "%NGHI_ROOT%"
    git clone --no-checkout "%NGHI_URL%" "%NGHI_ROOT%"
    if errorlevel 1 goto :fail
) else (
    echo [4/8] NGHI-TTS checkout da ton tai.
)

echo [5/8] Pin NGHI-TTS commit %NGHI_COMMIT% va cai dependencies ...
git -C "%NGHI_ROOT%" fetch --depth 1 origin "%NGHI_COMMIT%"
if errorlevel 1 goto :fail
git -C "%NGHI_ROOT%" checkout --detach "%NGHI_COMMIT%"
if errorlevel 1 goto :fail
set "NGHI_ACTUAL="
for /f "usebackq delims=" %%H in (`git -C "%NGHI_ROOT%" rev-parse HEAD`) do set "NGHI_ACTUAL=%%H"
if /i not "%NGHI_ACTUAL%"=="%NGHI_COMMIT%" (
    echo [LOI] NGHI checkout khong dung commit da pin.
    echo Expected: %NGHI_COMMIT%
    echo Actual:   %NGHI_ACTUAL%
    goto :fail
)
> "%NGHI_MARKER%" echo %NGHI_COMMIT%
pushd "%NGHI_ROOT%"
call "%NPM_CMD%" ci --omit=dev
set "NPM_RC=%ERRORLEVEL%"
popd
if not "%NPM_RC%"=="0" goto :fail

if not exist "%MODEL_PATH%" (
    echo [6/8] Tai NGHI-TTS voice %VOICE_ID% ...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri $env:MODEL_URL -OutFile ($env:MODEL_PATH + '.download'); Move-Item -Force ($env:MODEL_PATH + '.download') $env:MODEL_PATH"
    if errorlevel 1 goto :fail
) else (
    echo [6/8] Model da ton tai.
)

if not exist "%CONFIG_PATH%" (
    echo [7/8] Tai va kiem tra voice config/model ...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri $env:CONFIG_URL -OutFile ($env:CONFIG_PATH + '.download'); Move-Item -Force ($env:CONFIG_PATH + '.download') $env:CONFIG_PATH"
    if errorlevel 1 goto :fail
) else (
    echo [7/8] Voice config da ton tai; kiem tra hash ...
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$actual=(Get-FileHash -Algorithm SHA256 -LiteralPath $env:MODEL_PATH).Hash.ToLower(); if ($actual -ne $env:MODEL_SHA256) { throw ('Sai SHA-256 model. Expected ' + $env:MODEL_SHA256 + ', got ' + $actual) }"
if errorlevel 1 goto :fail
powershell -NoProfile -ExecutionPolicy Bypass -Command "$actual=(Get-FileHash -Algorithm SHA256 -LiteralPath $env:CONFIG_PATH).Hash.ToLower(); if ($actual -ne $env:CONFIG_SHA256) { throw ('Sai SHA-256 config. Expected ' + $env:CONFIG_SHA256 + ', got ' + $actual) }"
if errorlevel 1 goto :fail

echo [8/8] Smoke test production pipeline NGHI frontend -^> phoneme IDs -^> ONNX ...
if exist "%SMOKE_WAV%" del /q "%SMOKE_WAV%" >nul 2>&1
"%TTS_PYTHON%" tts_worker.py --smoke-test "%SMOKE_WAV%" --model "%MODEL_PATH%" --config "%CONFIG_PATH%" --node "%NODE_EXE%" --nghi-adapter "%NGHI_ADAPTER%" --nghi-root "%NGHI_ROOT%" --nghi-commit "%NGHI_COMMIT%"
if errorlevel 1 goto :fail
if not exist "%SMOKE_WAV%" (
    echo [LOI] Smoke test khong tao duoc WAV.
    goto :fail
)
del /q "%SMOKE_WAV%" >nul 2>&1

echo.
echo [OK] Offline Vietnamese TTS da san sang.
echo Voice: %VOICE_ID% ^(NGHI-TTS^)
echo Frontend: NGHI %NGHI_COMMIT%
echo Inference: piper-tts %PIPER_VERSION% / ONNX
echo Node: v%NODE_VERSION% portable
echo Sau buoc nay Attendance co the synthesize khi khong co Internet.
echo.
call :cleanup_temp
endlocal
exit /b 0

:cleanup_temp
if exist "%NODE_ZIP%" del /q "%NODE_ZIP%" >nul 2>&1
if exist "%NODE_SHASUMS%" del /q "%NODE_SHASUMS%" >nul 2>&1
if exist "%NODE_EXTRACT%" rmdir /s /q "%NODE_EXTRACT%" >nul 2>&1
if exist "%SMOKE_WAV%" del /q "%SMOKE_WAV%" >nul 2>&1
if exist "%MODEL_PATH%.download" del /q "%MODEL_PATH%.download" >nul 2>&1
if exist "%CONFIG_PATH%.download" del /q "%CONFIG_PATH%.download" >nul 2>&1
exit /b 0

:fail
call :cleanup_temp
echo.
echo [LOI] Cai dat Offline TTS khong hoan tat.
echo Kiem tra Internet, Python x64, Git va dung luong dia roi chay lai.
echo.
endlocal
exit /b 1
