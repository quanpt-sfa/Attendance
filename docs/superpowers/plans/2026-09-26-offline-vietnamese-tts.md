# Offline Vietnamese TTS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add offline Piper-based Vietnamese student-name speech with deterministic WAV caching, asynchronous precaching, and browser speech fallback.

**Architecture:** Attendance keeps its existing Python runtime. `tts_service.py` manages cache identity, local runtime discovery, a long-lived subprocess, and background precache; `tts_worker.py` runs inside `.venv-tts` and is the only module that imports Piper. `server.py` exposes thin TTS endpoints/hooks, while `random-picker.js` prefers local WAV audio and falls back to its existing `speechSynthesis` path.

**Tech Stack:** Python 3 standard library, SQLite, `http.server`, `unittest`, Piper `piper-tts==1.8.0`, ONNX voice `vi_VN-vais1000-medium`, Windows batch scripts, browser JavaScript `Audio` + Web Speech API fallback.

**Spec:** `docs/superpowers/specs/2026-09-26-offline-vietnamese-tts-design.md`

## Global Constraints

- Attendance must continue to start and operate when Piper is not installed.
- Piper runtime is isolated in `.venv-tts`; the main Attendance Python process must not import `piper`.
- Pin `piper-tts==1.8.0`.
- Pin voice ID `vi_VN-vais1000-medium` to voice revision `piper-voices-v1.0.0`.
- Verify the pinned ONNX SHA-256 `ec7c89e2c85f4d1edc24b6120c18aaf1bda614f06b511567eb9c7c0de15e2dab` during setup.
- Cache identity is `SHA256(cache_format_version + "\n" + voice_id + "\n" + voice_revision + "\n" + normalized_text)` with cache format version `1`.
- Runtime/model/cache artifacts remain outside Git: `.venv-tts/`, `tts/voices/`, `tts_cache/`.
- Database schema remains unchanged for this feature.
- Database-backed Random Picker remains attendance-only; Excel-only entries continue using browser speech fallback.
- All automated tests use fakes/temp directories and must not download or load the real Piper model.

## Review Focus

- Student names containing Vietnamese combining characters or repeated whitespace must normalize deterministically without losing diacritics; Task 1 pins NFC/whitespace behavior.
- Two simultaneous requests for the same uncached name must not trigger duplicate synthesis or publish a partial WAV; Task 1 pins same-key serialization and atomic replacement.
- Worker death, malformed JSON, or runtime/model absence must degrade to `tts_unavailable`/`tts_synthesis_failed` rather than crashing Attendance; Tasks 1–3 pin these states.
- Student write operations must commit successfully even when precache fails or Piper is unavailable; Task 3 pins post-commit non-blocking behavior.
- Random Picker must never play both local WAV and browser speech for one selection; Task 4 pins success/fallback exclusivity.

---

### Task 1: Local TTS Cache and Service Boundary

**Files:**
- Create: `tts_service.py`
- Create: `test_tts_service.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: project root filesystem only; no Piper import.
- Produces: `normalize_text(text: str) -> str`, `cache_key(text: str) -> str`, `get_cached_audio(text: str) -> pathlib.Path | None`, `ensure_audio(text: str) -> pathlib.Path`, `get_status() -> dict`, `precache_students(students: list[dict]) -> dict`, `shutdown_worker() -> None`.
- Produces exceptions: `TTSUnavailableError`, `TTSSynthesisError`.

- [ ] **Step 1: Write failing normalization/cache-key tests in `test_tts_service.py`**

Assert that `"  Nguye\u0302\u0303n   Thị  An  "` normalizes to NFC with single spaces, identical text/config produces identical keys, and changing text/voice revision changes the key.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m unittest test_tts_service.TTSServicePureTests -v`

Expected: FAIL because `tts_service`/interfaces do not exist.

- [ ] **Step 3: Implement pure configuration, normalization, and cache-path logic in `tts_service.py`**

Use constants `VOICE_ID`, `VOICE_REVISION`, `CACHE_FORMAT_VERSION`, project-relative `TTS_VENV`, `VOICE_DIR`, `CACHE_DIR`, and deterministic two-character cache sharding.

- [ ] **Step 4: Run pure tests and verify GREEN**

Run: `python -m unittest test_tts_service.TTSServicePureTests -v`

Expected: PASS.

- [ ] **Step 5: Add failing cache-hit, cache-miss, atomic-write, concurrency, and unavailable-runtime tests**

Use a temporary cache directory and an injected/fake worker transport. Assert cache hit performs zero synth calls; two concurrent same-key calls synthesize once; final path is a non-empty WAV; failed synthesis leaves no final/partial cache file; missing `.venv-tts` or model reports unavailable without import-time failure.

- [ ] **Step 6: Run service tests and verify RED**

Run: `python -m unittest test_tts_service -v`

Expected: new worker/cache tests FAIL.

- [ ] **Step 7: Implement worker lifecycle and atomic cache publication in `tts_service.py`**

Keep one process-local lock around worker communication and the second cache-existence check. Launch `.venv-tts/Scripts/python.exe tts_worker.py --serve`; exchange newline-delimited JSON; retry one worker restart on transport failure; write to unique temp WAV then `os.replace()` into the final cache path.

- [ ] **Step 8: Implement `get_status()`, `precache_students()`, and `shutdown_worker()`**

`precache_students()` deduplicates normalized non-empty names and records generated/cached/failed counts without raising class-wide failure.

- [ ] **Step 9: Extend `.gitignore`**

Add `.venv-tts/`, `tts/voices/`, and `tts_cache/`.

- [ ] **Step 10: Run Task 1 tests**

Run: `python -m unittest test_tts_service -v`

Expected: PASS.

- [ ] **Step 11: Commit**

```bash
git add tts_service.py test_tts_service.py .gitignore
git commit -m "feat: add offline TTS cache service"
```

### Task 2: Isolated Piper Worker and Windows Setup/Diagnostics

**Files:**
- Create: `tts_worker.py`
- Create: `test_tts_worker.py`
- Create: `Setup-TTS.bat`
- Create: `Check-TTS.bat`

**Interfaces:**
- Consumes: `.venv-tts` Python environment, `tts/voices/vi_VN-vais1000-medium.onnx`, matching `.onnx.json`.
- Produces worker protocol: stdin request `{"id": str, "action": "synthesize", "text": str, "output": str}` and stdout response `{"id": str, "ok": bool, "error"?: str}`.
- Produces CLI modes: `tts_worker.py --serve`, `tts_worker.py --smoke-test <output.wav>`, and read-only status through `tts_service.py` for `Check-TTS.bat`.

- [ ] **Step 1: Write failing worker protocol tests in `test_tts_worker.py`**

Test request parsing/response IDs with a fake model object: valid synth produces `ok=true`; invalid action produces `ok=false`; synthesis exception produces `ok=false`; diagnostics never pollute protocol stdout.

- [ ] **Step 2: Run worker tests and verify RED**

Run: `python -m unittest test_tts_worker -v`

Expected: FAIL because `tts_worker.py` does not exist.

- [ ] **Step 3: Implement `tts_worker.py` with lazy Piper import/model load**

Do not import `piper` at module import time used by tests; import/load inside the runtime path. Keep stdout exclusively for protocol JSON and stderr for diagnostics.

- [ ] **Step 4: Run worker tests and verify GREEN**

Run: `python -m unittest test_tts_worker -v`

Expected: PASS without Piper installed in the test environment.

- [ ] **Step 5: Implement `Setup-TTS.bat`**

Create `.venv-tts`, install exactly `piper-tts==1.8.0`, download the two pinned voice files only when missing, verify the ONNX SHA-256, run the smoke-test mode, delete smoke output, and print actionable failure messages. Do not alter the main Attendance Python environment.

- [ ] **Step 6: Implement `Check-TTS.bat`**

Invoke the normal Attendance Python interpreter to print `tts_service.get_status()` fields and cache count; do not download/install/change files.

- [ ] **Step 7: Add static contract tests for setup/check scripts to `test_tts_worker.py`**

Assert pinned package/version, voice filenames, SHA-256, `.venv-tts` isolation, smoke-test invocation, and absence of destructive/download actions in `Check-TTS.bat`.

- [ ] **Step 8: Run Task 2 tests**

Run: `python -m unittest test_tts_worker -v`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add tts_worker.py test_tts_worker.py Setup-TTS.bat Check-TTS.bat
git commit -m "feat: add isolated Piper runtime setup"
```

### Task 3: Backend TTS API and Asynchronous Precache Hooks

**Files:**
- Modify: `server.py` (`AttendanceHandler.do_GET`, `create_student`, `import_students`, `update_student`; add thin TTS helper methods)
- Create: `test_server_tts.py`

**Interfaces:**
- Consumes Task 1: `tts_service.ensure_audio()`, `tts_service.get_status()`, `tts_service.precache_students()`, exceptions.
- Produces: `GET /api/tts/status` and `GET /api/tts/student/<student_id>?class_id=<class_id>`.
- Produces helper: `schedule_tts_precache(students: list[dict]) -> None` that returns immediately and executes `precache_students()` in a daemon thread.

- [ ] **Step 1: Write failing handler-level tests in `test_server_tts.py`**

Use a temporary SQLite DB and patched `tts_service`: assert missing student -> 404; empty name -> 422; unavailable -> 503 `tts_unavailable`; synthesis error -> 503 `tts_synthesis_failed`; success -> `Content-Type: audio/wav` and exact WAV bytes; status endpoint forwards read-only service status.

- [ ] **Step 2: Run endpoint tests and verify RED**

Run: `python -m unittest test_server_tts.ServerTTSEndpointTests -v`

Expected: FAIL because routes/handlers do not exist.

- [ ] **Step 3: Add thin GET routes and response helpers in `server.py`**

Decode `student_id`, require `class_id`, query by composite identity, call service, stream the resolved WAV, and map service exceptions to stable JSON error codes without exposing local filesystem paths.

- [ ] **Step 4: Run endpoint tests and verify GREEN**

Run: `python -m unittest test_server_tts.ServerTTSEndpointTests -v`

Expected: PASS.

- [ ] **Step 5: Write failing precache-hook tests**

Assert `create_student`, `import_students`, and name-changing `update_student` commit before scheduling; scheduler is called with persisted `full_name`; scheduler exceptions/precache failures do not change successful database response; request path does not wait for fake slow precache work.

- [ ] **Step 6: Run precache tests and verify RED**

Run: `python -m unittest test_server_tts.ServerTTSPrecacheTests -v`

Expected: FAIL because hooks/scheduler do not exist.

- [ ] **Step 7: Implement `schedule_tts_precache()` and call it only after successful commits**

For update, schedule only when the effective full name is non-empty; duplicate triggers are acceptable because Task 1 cache/dedup handles them. Log failures; never roll back persisted student data because of TTS.

- [ ] **Step 8: Run all backend TTS tests**

Run: `python -m unittest test_server_tts -v`

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add server.py test_server_tts.py
git commit -m "feat: expose local student TTS API"
```

### Task 4: Random Picker Local-Audio Playback with Exclusive Fallback

**Files:**
- Modify: `random-picker.js` (student mapping/context, winner speech path)
- Modify: `random-picker-attendance.js` (preserve/pass `classId` for database-backed entries if needed)
- Modify: `random-picker.html` only if class context wiring cannot remain inside existing objects
- Create: `random-picker-speech.js`
- Create: `test_random_picker_speech.js`
- Modify: `test_random_picker_attendance.js` only for regression expectations affected by class context

**Interfaces:**
- Consumes Task 3 endpoint: `/api/tts/student/<student_id>?class_id=<class_id>`.
- Produces browser helper: `RandomPickerSpeech.playStudentName(student, options) -> Promise<'local'|'fallback'|'silent'>`.
- Student object must carry `maSV`, `fullName`, and optional `classId`; Excel entries omit `classId` and go directly to fallback.

- [ ] **Step 1: Write failing browser-helper tests in `test_random_picker_speech.js`**

With fake `fetch`, `Audio`, and fallback callback, assert: 200 local WAV -> local playback and zero fallback calls; 503/network/audio-play rejection -> exactly one fallback call; missing `classId` -> no fetch and one fallback; sound disabled -> neither local nor fallback.

- [ ] **Step 2: Run helper tests and verify RED**

Run: `node test_random_picker_speech.js`

Expected: FAIL because `random-picker-speech.js` does not exist.

- [ ] **Step 3: Implement `random-picker-speech.js` as a standalone testable module**

Use endpoint URL encoding for both student and class IDs. Revoke object URLs after playback/error when response audio is materialized as a Blob. Guarantee a single terminal path per selection.

- [ ] **Step 4: Run helper tests and verify GREEN**

Run: `node test_random_picker_speech.js`

Expected: PASS.

- [ ] **Step 5: Wire database class context into Random Picker student objects**

`random-picker-attendance.js` returns checked-in entries with `classId`; `scan.html` integration data already has `currentSession.class_id` and should pass it when constructing checked-in/all entries; standalone uses the selected class/open session context. Excel entries remain unchanged.

- [ ] **Step 6: Replace only Random Picker winner-name speech with `RandomPickerSpeech.playStudentName()`**

Keep the existing browser Vietnamese voice-selection code as the fallback callback. Do not alter horror/race sound effects or general `scan.html` speech in this task.

- [ ] **Step 7: Extend regression tests**

Assert attendance-only loading still filters `check_type === 'in'`, class context is preserved, and local-audio success suppresses `SpeechSynthesisUtterance` while failure invokes it once.

- [ ] **Step 8: Run frontend tests**

Run: `node test_random_picker_attendance.js && node test_random_picker_speech.js`

Expected: both PASS.

- [ ] **Step 9: Commit**

```bash
git add random-picker.js random-picker-attendance.js random-picker.html random-picker-speech.js test_random_picker_attendance.js test_random_picker_speech.js scan.html
git commit -m "feat: play cached Piper names in random picker"
```

### Task 5: Full Regression and Offline Acceptance Contract

**Files:**
- Modify: `README.md` only to add current TTS setup/use instructions without rewriting unrelated legacy sections
- Create: `test_tts_integration.py`

**Interfaces:**
- Consumes all previous tasks.
- Produces one integration contract proving Attendance remains usable both with and without installed local TTS.

- [ ] **Step 1: Write integration tests in `test_tts_integration.py`**

Assert imports/startup do not require Piper; status is unavailable cleanly when runtime/model paths are absent; a fake worker creates a reusable cache file; a second `ensure_audio()` is a cache hit; worker shutdown is safe/idempotent.

- [ ] **Step 2: Run integration test and verify expected failures before final wiring fixes**

Run: `python -m unittest test_tts_integration -v`

Expected: FAIL only for any still-missing cross-task contract; if already GREEN, record that no additional production change is required.

- [ ] **Step 3: Add concise README instructions**

Document: run `Setup-TTS.bat` once while online; verify with `Check-TTS.bat`; then normal `Start-Server.bat [PORT]` works offline. State that TTS is optional and browser speech remains fallback.

- [ ] **Step 4: Run complete Python regression suite**

Run: `python -m unittest test_db_schema test_startup test_tts_service test_tts_worker test_server_tts test_tts_integration -v`

Expected: PASS.

- [ ] **Step 5: Run complete JavaScript regression suite**

Run: `node test_random_picker_attendance.js && node test_random_picker_speech.js`

Expected: PASS.

- [ ] **Step 6: Run static syntax/contract checks**

Run: `python -m py_compile server.py startup.py db_schema.py tts_service.py tts_worker.py`

Expected: exit code 0.

- [ ] **Step 7: Verify Git hygiene**

Run: `git status --short --ignored`

Expected: `.venv-tts/`, `tts/voices/`, and `tts_cache/` appear ignored if present; no model/WAV/venv file is tracked.

- [ ] **Step 8: Manual Windows acceptance after real one-time setup**

On a Windows machine: run `Setup-TTS.bat`; run `Check-TTS.bat`; import a small class; confirm cache files appear; disconnect network; start Attendance; open a current session; call Random Picker; confirm a checked-in student's name plays from local audio. This is the only step that uses the real model/runtime.

- [ ] **Step 9: Commit**

```bash
git add README.md test_tts_integration.py
git commit -m "docs: document offline Vietnamese TTS setup"
```

- [ ] **Step 10: Final review gate**

Compare the implementation branch against the pre-feature commit, verify only planned files changed, and run the full test commands above immediately before declaring completion.
