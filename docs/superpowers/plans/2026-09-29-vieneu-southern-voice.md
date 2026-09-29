# VieNeu Southern Voice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Attendance's Piper TTS backend with offline VieNeu-TTS v3 Turbo using the Southern female preset `Thùy Dung`, without changing the existing Attendance HTTP/UI integration.

**Architecture:** Keep the existing isolated `.venv-tts` long-lived worker boundary and NDJSON request protocol, but make `tts_worker.py` own one `Vieneu(mode="v3turbo", backend="onnx", precision="fp32")` instance. `tts_service.py` owns cache identity, worker lifecycle, offline Hugging Face environment and status; setup performs an online smoke synthesis followed by a fresh-process offline smoke before writing a validated local runtime manifest.

**Tech Stack:** Python 3.10+, `vieneu==3.8.3`, ONNX Runtime CPU fp32, NumPy/SoundFile, Windows batch/PowerShell bootstrap, existing Python `unittest` + GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-29-vieneu-southern-voice-design.md`

## Global Constraints

- Start from clean `main` on branch `feat/vieneu-southern-voice`; do not copy production code from `feat/nghi-frontend-onnx`.
- Pin runtime package exactly to `vieneu==3.8.3`.
- Production voice is exactly `Thùy Dung`.
- Production engine is VieNeu v3 Turbo, `backend="onnx"`, `precision="fp32"`, CPU-only.
- Production runtime must not depend on Piper, NGHI, Node, direct phoneme IDs, Attendance sentence splitting, or manual post-synthesis silence.
- Main Attendance process must not import `vieneu` or other heavy TTS dependencies.
- Existing `/api/tts/...`, precache scheduling, atomic cache publication and browser `speechSynthesis` fallback remain compatible.
- Runtime must use an Attendance-owned Hugging Face cache and run with `HF_HUB_OFFLINE=1` after setup.
- Setup succeeds only after an online smoke and a second smoke in a fresh Python process with offline mode enabled.
- Do not destructively delete old local Piper/NGHI assets during migration.

## Review Focus

1. **SDK writes to stdout during import/init/infer** — worker protocol stdout must still contain NDJSON only; SDK chatter goes to stderr.
2. **Cold model load is slow or fails** — service must use a separate bounded 90-second readiness timeout and surface unavailable status/error rather than hang.
3. **Hub cache looks present but is incomplete** — setup must prove a fresh-process `HF_HUB_OFFLINE=1` synthesis before writing the ready manifest; production never silently repairs from the network.
4. **Preset display label differs from voice ID** — validation must resolve the exact voice ID `Thùy Dung`, not rely on decorative labels such as an Editors' Pick prefix.
5. **Worker crashes after partially writing a WAV** — no partial file may be published into `tts_cache`; the existing one-retry policy remains bounded.

---

### Task 1: Replace Piper Worker With VieNeu v3 Turbo

**Files:**
- Modify: `tts_worker.py`
- Modify: `test_tts_worker.py`

**Interfaces:**
- Consumes: NDJSON synthesis requests `{id, action:"synthesize", text, output}` from `tts_service.py`.
- Produces: `VieneuSynthesizer`, `READY_EVENT_TYPE = "ready"`, `DEFAULT_VOICE = "Thùy Dung"`, startup ready/failure NDJSON, and the existing per-request `{id, ok, error?}` response schema.

- [ ] **Step 1: Write RED tests for engine construction and voice selection**

Add tests asserting a fake `Vieneu` factory is constructed exactly once with `mode="v3turbo"`, `backend="onnx"`, `precision="fp32"`; `list_preset_voices()` must contain a tuple whose voice ID is exactly `Thùy Dung`; two synthesis requests reuse the same engine.

- [ ] **Step 2: Run the focused worker tests and confirm RED**

Run: `python -m unittest test_tts_worker -v`

Expected: FAIL because the current worker exposes Piper synthesizers and requires model/config/native-piper arguments.

- [ ] **Step 3: Write RED tests for output fidelity and protocol isolation**

Add tests asserting source case/punctuation are passed unchanged to `infer(text, voice="Thùy Dung")`; a fake float waveform is written as mono 48 kHz PCM WAV; fake SDK `print()` calls during init/infer do not contaminate protocol stdout; inference/save failure removes the partial output.

- [ ] **Step 4: Implement `VieneuSynthesizer` and simplify the CLI**

Implement a lazy/long-lived synthesizer in `tts_worker.py` with constructor/factory injection for tests. Import `Vieneu` inside the isolated worker only. Redirect SDK stdout to stderr around import/init/list/infer. Write waveform with `soundfile.write(..., samplerate=48000, subtype="PCM_16")`. Remove `PiperSynthesizer`, `NativePiperSynthesizer`, lowercasing/eSpeak normalization, Piper model/config CLI arguments and manual sentence-silence logic.

- [ ] **Step 5: Add worker readiness handshake**

For `--serve`, initialize/validate the engine before reading requests and write exactly one startup line: `{"type":"ready","ok":true,"voice":"Thùy Dung","engine":"vieneu-v3-turbo","backend":"onnx-fp32"}`. On initialization failure, write `{"type":"ready","ok":false,"error":"..."}` and exit non-zero. Preserve request-response IDs after readiness.

- [ ] **Step 6: Run worker tests GREEN**

Run: `python -m unittest test_tts_worker -v`

Expected: all worker tests PASS and no test imports a real VieNeu model.

- [ ] **Step 7: Commit**

```bash
git add tts_worker.py test_tts_worker.py
git commit -m "feat: replace Piper worker with VieNeu"
```

---

### Task 2: Migrate Service Identity, Cache and Worker Lifecycle

**Files:**
- Modify: `tts_service.py`
- Modify: `test_tts_service.py`
- Create: `tts_vieneu_manifest.py`
- Create: `test_tts_vieneu_manifest.py`

**Interfaces:**
- Consumes: Task 1 readiness line and synthesis response protocol.
- Produces: VieNeu runtime constants/status, Attendance-owned HF cache paths, validated setup manifest contract, cache v6 identity, bounded worker startup.

- [ ] **Step 1: Write RED pure tests for VieNeu identity/cache**

Assert constants: `VOICE_ID == "Thùy Dung"`, `TTS_ENGINE == "vieneu-v3-turbo"`, `TTS_ENGINE_VERSION == "3.8.3"`, `TTS_BACKEND == "onnx-fp32"`, `CACHE_FORMAT_VERSION == 6`. Assert cache keys change when voice/engine version/backend/text changes and no longer depend on `calmwoman3688`.

- [ ] **Step 2: Write RED manifest/status tests**

Define `tts_vieneu_manifest.py` pure interfaces `load_manifest(path: Path) -> dict | None` and `manifest_is_ready(manifest: dict | None) -> bool`. Tests require exact engine/version/voice/backend fields plus `offline_verified is True`. `get_status()` must be read-only and return unavailable when `.venv-tts`, manifest or Attendance-owned HF cache is missing/incomplete; old `piper.exe`/voice files must not affect readiness.

- [ ] **Step 3: Write RED worker startup tests**

Using fake `Popen`, assert production worker environment includes `HF_HUB_OFFLINE=1`, `HF_HOME=<project>/tts/runtime/vieneu/hf`, and `HF_HUB_CACHE=<...>/hub`; command uses only `tts_worker.py --serve`. Assert `_start_worker_locked()` waits for the Task 1 readiness line with `WORKER_STARTUP_TIMEOUT_SECONDS = 90.0`, rejects malformed/failed readiness, and warm synthesis uses a separate `WORKER_REQUEST_TIMEOUT_SECONDS = 45.0`.

- [ ] **Step 4: Implement service + manifest boundary**

Remove `NATIVE_PIPER`, model/config path requirements and Piper backend status. Add `TTS_RUNTIME_ROOT`, `HF_HOME`, `HF_HUB_CACHE`, `SETUP_MANIFEST`. Validate manifest without importing VieNeu. Preserve one worker restart retry, atomic temp-WAV publication, cache locking and current service exception classes.

- [ ] **Step 5: Run service/manifest tests GREEN**

Run: `python -m unittest test_tts_service test_tts_vieneu_manifest -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tts_service.py tts_vieneu_manifest.py test_tts_service.py test_tts_vieneu_manifest.py
git commit -m "feat: add VieNeu runtime service contract"
```

---

### Task 3: Rebuild Windows Setup and Read-Only Check

**Files:**
- Modify: `Setup-TTS.bat`
- Modify: `Check-TTS.bat`
- Create: `tools/write_vieneu_manifest.py`
- Create: `test_tts_setup.py`

**Interfaces:**
- Consumes: Task 1 `tts_worker.py --smoke-test OUTPUT_WAV` and Task 2 manifest schema/cache paths.
- Produces: one-time online setup, fresh-process offline proof, `tts/runtime/vieneu/setup.json`, and read-only diagnostics.

- [ ] **Step 1: Write RED setup/check contract tests**

Assert `Setup-TTS.bat` pins `vieneu==3.8.3`; contains no Piper/NGHI/Node download/install logic; sets Attendance-owned `HF_HOME`/`HF_HUB_CACHE`; performs one smoke with online mode and a second separate `python.exe tts_worker.py --smoke-test ...` invocation after setting `HF_HUB_OFFLINE=1`; writes manifest only after the offline smoke succeeds. Assert `Check-TTS.bat` contains no install/download command.

- [ ] **Step 2: Write RED manifest-writer tests**

`tools/write_vieneu_manifest.py` must query the installed distribution version, require `3.8.3`, summarize files under the Attendance HF cache as relative path + size, and write JSON containing `voice`, `engine`, `engine_version`, `backend`, `offline_verified:true`, timestamp and artifact summary. It must refuse to mark ready when the cache is empty.

- [ ] **Step 3: Implement `Setup-TTS.bat`**

Reuse/create `.venv-tts`, upgrade pip only as needed, install exact `vieneu==3.8.3`, verify package version, create Attendance runtime/cache directories, run online smoke using acceptance sentence 1, delete its temp WAV, then launch a new process with `HF_HUB_OFFLINE=1` for the same smoke. Only after the second WAV validates, invoke the manifest writer. Do not delete old local Piper/NGHI assets.

- [ ] **Step 4: Implement `Check-TTS.bat`**

Use `.venv-tts\Scripts\python.exe` when present to call `tts_service.get_status()` and report voice, engine/version, backend, runtime/offline-assets, and cache count. Remain read-only.

- [ ] **Step 5: Run setup/check tests GREEN**

Run: `python -m unittest test_tts_setup test_tts_vieneu_manifest -v`

Expected: PASS without installing/downloading the real model in CI.

- [ ] **Step 6: Commit**

```bash
git add Setup-TTS.bat Check-TTS.bat tools/write_vieneu_manifest.py test_tts_setup.py
git commit -m "feat: bootstrap VieNeu for offline Windows use"
```

---

### Task 4: Remove Superseded Piper/NGHI Audit Surface and Update Documentation

**Files:**
- Delete: `tools/tts_phoneme_audit.py`
- Delete: `tools/nghi_phoneme_audit.mjs`
- Delete: `tools/tts_phoneme_audit.ps1`
- Delete: `test_tts_audit.py`
- Modify: `.github/workflows/feature-tts-tests.yml`
- Modify: `README.md`
- Modify: `.gitignore` only if obsolete audit-only entries remain

**Interfaces:**
- Consumes: Tasks 1–3 production/runtime contracts.
- Produces: repository documentation and CI that describe/test only the VieNeu production direction.

- [ ] **Step 1: Write/adjust RED repository contract assertions**

Add assertions to the appropriate integration/setup tests that tracked production/setup files contain no `piper.exe`, `calmwoman3688`, NGHI commit, portable Node or phoneme-audit commands, while historical design docs may retain context.

- [ ] **Step 2: Remove obsolete audit tooling and workflow references**

Delete the four obsolete audit files. Remove `tools/tts_phoneme_audit.py`, `test_tts_audit`, Node setup/checks that existed only for NGHI audit, and `tools/nghi_phoneme_audit.mjs` from mandatory workflow commands. Keep existing Random Picker JavaScript regression tests.

- [ ] **Step 3: Update README TTS section**

Document VieNeu v3 Turbo, `Thùy Dung`, one-time `Setup-TTS.bat`, offline runtime, `Check-TTS.bat`, CPU ONNX fp32, and browser fallback. Remove current native Piper 2023/calmwoman guidance.

- [ ] **Step 4: Run syntax + repository regression suite**

Run the same commands that the updated workflow will run. Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "docs: retire Piper audit path for VieNeu"
```

---

### Task 5: Preserve Attendance API/Precache/Fallback Integration

**Files:**
- Modify only if required: `server_tts.py`
- Modify: `test_server_tts.py`
- Modify: `test_tts_integration.py`
- Modify: `test_random_picker_speech.js` only if a regression reveals a compatibility issue

**Interfaces:**
- Consumes: unchanged `tts_service.ensure_audio()`, `get_status()`, `precache_students()` service surface from Task 2.
- Produces: proof that HTTP/UI integration is unchanged by the backend swap.

- [ ] **Step 1: Add/refresh integration tests**

Assert `/api/tts/status` forwards VieNeu status fields without instantiating VieNeu; student endpoint still serves the exact cached WAV and stable error codes; successful student writes still schedule precache; unavailable local TTS still allows the existing browser speech fallback path.

- [ ] **Step 2: Verify cache/worker failure behavior**

Add tests covering worker crash after a temp WAV is created, startup readiness failure, and concurrent same-key requests. Assert no partial final WAV and only one synthesis for a shared cache key.

- [ ] **Step 3: Implement only compatibility fixes required by RED tests**

Do not change route shapes, database schema or front-end message semantics.

- [ ] **Step 4: Run full Python and JavaScript regression suite**

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add server_tts.py test_server_tts.py test_tts_integration.py test_random_picker_speech.js
git commit -m "test: preserve TTS integration across VieNeu migration"
```

---

### Task 6: CI and Whole-Branch Verification

**Files:**
- Modify: `.github/workflows/feature-tts-tests.yml` if Task 4 did not finish all workflow changes

**Interfaces:**
- Consumes: all earlier tasks.
- Produces: deterministic mandatory CI that does not download the multi-model VieNeu runtime.

- [ ] **Step 1: Ensure mandatory CI uses mocks/contracts only**

CI compiles/imports Attendance modules without `vieneu` installed in the main interpreter and runs all unit/integration tests. It must not download Hugging Face model artifacts.

- [ ] **Step 2: Run whole-branch diff review**

Compare `main...feat/vieneu-southern-voice`. Confirm no production references to Piper/NGHI/Node remain; no model/cache/runtime files are tracked; API/database changes are absent unless justified by tests.

- [ ] **Step 3: Run fresh CI on final HEAD**

Expected: Python and JavaScript jobs PASS.

- [ ] **Step 4: Commit any verification-only fixes separately**

Use a narrow commit message matching the defect; do not bundle unrelated cleanup.

---

### Task 7: Windows Real-Model Offline and Listening Gate

**Files:**
- No tracked code changes unless the gate reveals a reproducible defect.

**Interfaces:**
- Consumes: final branch and `Setup-TTS.bat`.
- Produces: deployment-machine evidence required before PR/merge.

- [ ] **Step 1: Online bootstrap on Windows**

Run from a clean/reused `.venv-tts` as supported by the script:

```powershell
cd D:\Works\attendance
git checkout feat/vieneu-southern-voice
git pull
.\Setup-TTS.bat
.\Check-TTS.bat
```

Expected: setup performs online + fresh-process offline smoke and status reports `available=true`, `voice=Thùy Dung`, `engine=vieneu-v3-turbo`, `engine_version=3.8.3`, `backend=onnx-fp32`.

- [ ] **Step 2: Prove runtime offline independently**

Disconnect network or block outbound access, start a new PowerShell/Python process, synthesize acceptance sentences 1–5 through `tts_service.ensure_audio()`, and verify each output is a valid WAV without Hub access.

- [ ] **Step 3: Listening acceptance**

User confirms: Southern female voice sounds materially more natural than `calmwoman3688`; names are intelligible; `thành công. Mời` has a natural sentence boundary; comma/exclamation/question prosody is acceptable; no manual pause is needed.

- [ ] **Step 4: If listening fails, stop and diagnose before merging**

Do not tune arbitrary silence or pronunciation rewrites. Capture the exact failing utterance and determine whether the defect is VieNeu voice choice, text normalization, or engine behavior. A voice-only A/B may switch the centralized preset among `Mỹ Duyên`, `Kim Thanh`, or `Thục Đoan` without architecture changes.

- [ ] **Step 5: Finalize repository state only after user acceptance**

Open the VieNeu PR against `main`, attach CI + Windows offline/listening evidence, close superseded PR #10 without merging, and merge only after acceptance.
