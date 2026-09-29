param(
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$NodeExe = Join-Path $Root "tts\runtime\node\node.exe"
$NghiRoot = Join-Path $Root "tts\runtime\nghitts"
$NghiAdapter = Join-Path $Root "tts\nghi_frontend.mjs"
$PythonExe = Join-Path $Root ".venv-tts\Scripts\python.exe"
$ConfigPath = Join-Path $Root "tts\voices\calmwoman3688.onnx.json"

if (-not $OutputDir) {
    $OutputDir = Join-Path $Root "tts_audit_output"
}

foreach ($required in @($NodeExe, $NghiRoot, $NghiAdapter, $PythonExe, $ConfigPath)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Missing TTS audit prerequisite: $required. Run Setup-TTS.bat first."
    }
}

Write-Host "[audit] Comparing pinned NGHI oracle with production frontend..."
& $PythonExe (Join-Path $PSScriptRoot "tts_phoneme_audit.py") `
    --node $NodeExe `
    --nghi-root $NghiRoot `
    --config $ConfigPath `
    --output-dir $OutputDir
if ($LASTEXITCODE -ne 0) {
    throw "TTS frontend parity audit failed"
}

Write-Host "[audit] PASS. Reports:"
Write-Host "  $(Join-Path $OutputDir 'tts_phoneme_audit.json')"
Write-Host "  $(Join-Path $OutputDir 'tts_phoneme_audit.md')"
