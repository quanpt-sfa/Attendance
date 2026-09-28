param(
    [string]$OutputDir = ""
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$AuditRoot = Join-Path $Root ".tts-audit"
$NghiRoot = Join-Path $AuditRoot "nghitts"
$NghiCommit = "46d160da32041f7e176607203b958069265df7da"
$TtsPython = Join-Path $Root ".venv-tts\Scripts\python.exe"

if (-not $OutputDir) {
    $OutputDir = Join-Path $Root "tts_audit_output"
}

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

Require-Command "git"
Require-Command "node"
Require-Command "npm"

if (-not (Test-Path $TtsPython)) {
    throw "Missing TTS virtualenv Python: $TtsPython. Run Setup-TTS.bat first."
}

$nodeMajor = [int]((& node -p "process.versions.node.split('.')[0]").Trim())
if ($nodeMajor -lt 18) {
    throw "Node.js 18+ is required for the NGHI-TTS audit harness. Found major version $nodeMajor."
}

New-Item -ItemType Directory -Force -Path $AuditRoot | Out-Null

if (-not (Test-Path (Join-Path $NghiRoot ".git"))) {
    Write-Host "[audit] Cloning pinned NGHI-TTS source..."
    & git clone --filter=blob:none --no-checkout https://github.com/nghimestudio/nghitts.git $NghiRoot
    if ($LASTEXITCODE -ne 0) { throw "git clone failed" }
}

Write-Host "[audit] Checking out NGHI-TTS $NghiCommit"
& git -C $NghiRoot fetch --depth=1 origin $NghiCommit
if ($LASTEXITCODE -ne 0) { throw "git fetch for pinned NGHI-TTS commit failed" }
& git -C $NghiRoot checkout --detach --force $NghiCommit
if ($LASTEXITCODE -ne 0) { throw "git checkout for pinned NGHI-TTS commit failed" }

$actualCommit = (& git -C $NghiRoot rev-parse HEAD).Trim()
if ($actualCommit -ne $NghiCommit) {
    throw "NGHI-TTS checkout mismatch: expected $NghiCommit, got $actualCommit"
}

$phonemizerPackage = Join-Path $NghiRoot "node_modules\phonemizer\package.json"
if (-not (Test-Path $phonemizerPackage)) {
    Write-Host "[audit] Installing pinned NGHI-TTS JavaScript dependencies..."
    Push-Location $NghiRoot
    try {
        & npm ci --ignore-scripts --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
    }
    finally {
        Pop-Location
    }
}

$modelPath = Join-Path $Root "tts\voices\calmwoman3688.onnx"
$configPath = Join-Path $Root "tts\voices\calmwoman3688.onnx.json"
foreach ($required in @($modelPath, $configPath)) {
    if (-not (Test-Path $required)) {
        throw "Missing TTS prerequisite: $required. Run Setup-TTS.bat first."
    }
}

Write-Host "[audit] Comparing NGHI-TTS and production Piper 1.8 phoneme inputs..."
& $TtsPython (Join-Path $PSScriptRoot "tts_phoneme_audit.py") `
    --nghi-root $NghiRoot `
    --output-dir $OutputDir `
    --model $modelPath `
    --config $configPath
if ($LASTEXITCODE -ne 0) {
    throw "TTS phoneme audit failed"
}

Write-Host "[audit] Done. Reports:"
Write-Host "  $(Join-Path $OutputDir 'tts_phoneme_audit.json')"
Write-Host "  $(Join-Path $OutputDir 'tts_phoneme_audit.md')"
