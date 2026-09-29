@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Attendance - Setup Offline Vietnamese TTS

set "VIENEU_VERSION=3.8.3"
set "TTS_PYTHON=%~dp0.venv-tts\Scripts\python.exe"
set "TTS_RUNTIME_ROOT=%~dp0tts\runtime\vieneu"
set "HF_HOME=%~dp0tts\runtime\vieneu\hf"
set "HF_HUB_CACHE=%HF_HOME%\hub"
set "SETUP_MANIFEST=%TTS_RUNTIME_ROOT%\setup.json"
set "ONLINE_SMOKE_WAV=%TEMP%\attendance-vieneu-online-%RANDOM%-%RANDOM%.wav"
set "OFFLINE_SMOKE_WAV=%TEMP%\attendance-vieneu-offline-%RANDOM%-%RANDOM%.wav"
set "SMOKE_WAV_PATH="

if not exist "%TTS_RUNTIME_ROOT%" mkdir "%TTS_RUNTIME_ROOT%"
if not exist "%HF_HUB_CACHE%" mkdir "%HF_HUB_CACHE%"
if exist "%SETUP_MANIFEST%" del /q "%SETUP_MANIFEST%" >nul 2>&1

set "PYTHON_CMD="
for %%P in (py python python3) do (
    if not defined PYTHON_CMD (
        %%P --version >nul 2>&1 && set "PYTHON_CMD=%%P"
    )
)

if not defined PYTHON_CMD (
    echo.
    echo [LOI] Khong tim thay Python trong PATH.
    echo Cai Python 3.10+ x64 roi chay lai Setup-TTS.bat.
    exit /b 1
)

if not exist "%TTS_PYTHON%" (
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

echo [2/6] Cai VieNeu-TTS %VIENEU_VERSION% ...
"%TTS_PYTHON%" -m pip install "vieneu==%VIENEU_VERSION%"
if errorlevel 1 goto :fail

 echo [3/6] Kiem tra package version ...
"%TTS_PYTHON%" -c "import importlib.metadata,sys; v=importlib.metadata.version('vieneu'); print('VieNeu package:',v); sys.exit(0 if v=='%VIENEU_VERSION%' else 1)"
if errorlevel 1 (
    echo [LOI] VieNeu package khong dung version %VIENEU_VERSION%.
    goto :fail
)

set "HF_HUB_OFFLINE="
if exist "%ONLINE_SMOKE_WAV%" del /q "%ONLINE_SMOKE_WAV%" >nul 2>&1
echo [4/6] Online smoke test va tai model/codec can thiet ...
"%TTS_PYTHON%" tts_worker.py --smoke-test "%ONLINE_SMOKE_WAV%"
if errorlevel 1 goto :fail
set "SMOKE_WAV_PATH=%ONLINE_SMOKE_WAV%"
"%TTS_PYTHON%" -c "import os,sys; p=os.environ['SMOKE_WAV_PATH']; b=open(p,'rb').read(12) if os.path.isfile(p) else b''; sys.exit(0 if len(b)>=12 and b[:4]==b'RIFF' and b[8:12]==b'WAVE' else 1)"
if errorlevel 1 (
    echo [LOI] Online smoke test khong tao WAV hop le.
    goto :fail
)
del /q "%ONLINE_SMOKE_WAV%" >nul 2>&1

set "HF_HUB_OFFLINE=1"
if exist "%OFFLINE_SMOKE_WAV%" del /q "%OFFLINE_SMOKE_WAV%" >nul 2>&1
echo [5/6] Fresh-process offline smoke test ...
"%TTS_PYTHON%" tts_worker.py --smoke-test "%OFFLINE_SMOKE_WAV%"
if errorlevel 1 goto :fail
set "SMOKE_WAV_PATH=%OFFLINE_SMOKE_WAV%"
"%TTS_PYTHON%" -c "import os,sys; p=os.environ['SMOKE_WAV_PATH']; b=open(p,'rb').read(12) if os.path.isfile(p) else b''; sys.exit(0 if len(b)>=12 and b[:4]==b'RIFF' and b[8:12]==b'WAVE' else 1)"
if errorlevel 1 (
    echo [LOI] Offline smoke test khong tao WAV hop le.
    goto :fail
)
del /q "%OFFLINE_SMOKE_WAV%" >nul 2>&1

echo [6/6] Ghi manifest chi sau khi offline smoke da thanh cong ...
"%TTS_PYTHON%" tools\write_vieneu_manifest.py --hf-cache "%HF_HUB_CACHE%" --output "%SETUP_MANIFEST%"
if errorlevel 1 goto :fail
if not exist "%SETUP_MANIFEST%" goto :fail

echo.
echo [OK] Offline Vietnamese TTS da san sang.
echo Engine: VieNeu-TTS v3 Turbo %VIENEU_VERSION%
echo Voice: Thuy Dung ^(Southern female preset^)
echo Backend: ONNX CPU fp32
echo Runtime se dung HF_HUB_OFFLINE=1 sau buoc setup nay.
echo.
endlocal
exit /b 0

:fail
if exist "%ONLINE_SMOKE_WAV%" del /q "%ONLINE_SMOKE_WAV%" >nul 2>&1
if exist "%OFFLINE_SMOKE_WAV%" del /q "%OFFLINE_SMOKE_WAV%" >nul 2>&1
if exist "%SETUP_MANIFEST%" del /q "%SETUP_MANIFEST%" >nul 2>&1
echo.
echo [LOI] Cai dat Offline TTS khong hoan tat.
echo Kiem tra ket noi Internet, Python x64 va dung luong dia roi chay lai.
echo.
endlocal
exit /b 1
