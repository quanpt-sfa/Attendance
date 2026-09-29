# VieNeu Southern Voice Migration — Design Specification

Date: 2026-09-29
Status: Proposed for implementation after user review
Branch: `feat/vieneu-southern-voice`
Base: `main`

## 1. Goal

Replace Attendance's current Piper-based Vietnamese TTS backend with VieNeu-TTS v3 Turbo using the preset voice **Thùy Dung**, prioritizing a natural Southern Vietnamese female voice and correct sentence prosody while preserving the existing Attendance HTTP API, cache behavior, precache workflow, and browser fallback.

Success means:

- The default voice is `Thùy Dung`.
- Synthesis runs locally on CPU through VieNeu's ONNX backend.
- The application does not depend on Piper, NGHI, Node, or hand-written pause insertion.
- Sentence pauses/prosody are produced by VieNeu's own text normalization/chunk/gap pipeline.
- After one successful online setup, synthesis works with the machine disconnected from the Internet.
- Existing Random Picker and `/api/tts/...` callers do not need interface changes.

## 2. Source and version basis

The design was checked against VieNeu-TTS repository state:

- Repository: `pnnbao97/VieNeu-TTS`
- Source commit inspected: `2e982ff857bbe23fffa0c314e0f60da2497e2f4b`
- Python package version declared by that source: `vieneu==3.8.3`
- Repository license: Apache-2.0
- CPU path: ONNX Runtime, torch-free for preset-voice synthesis
- v3 Turbo sample rate: 48 kHz

The implementation pins the Python package to `vieneu==3.8.3`. The upstream source commit is recorded as provenance for the API/design review; the runtime package itself is installed from the pinned released package version rather than cloning the repository into Attendance.

Model/codec artifacts are downloaded by VieNeu/Hugging Face during setup. Because the current public VieNeu API does not expose a single revision parameter for every required model and codec artifact, Attendance will freeze each installation operationally by prefetching all required artifacts during setup and then forcing offline runtime. Setup will record an artifact manifest for diagnostics; it will not claim cross-machine bitwise reproducibility of upstream Hub snapshots.

## 3. Selected architecture

```text
Random Picker / Attendance UI
          |
          v
   server_tts.py
          |
          v
   tts_service.py
   - cache key/status
   - worker lifecycle
   - NDJSON protocol
          |
          v
   .venv-tts Python worker
          |
          v
   tts_worker.py
   - one long-lived Vieneu instance
   - mode="v3turbo"
   - backend="onnx"
   - precision="fp32"
   - voice="Thùy Dung"
          |
          v
   VieNeu normalization/chunk/gap/prosody
          |
          v
       48 kHz WAV
          |
          v
      tts_cache/
```

The main Attendance process continues not to import the heavy TTS package. VieNeu remains isolated in `.venv-tts` behind the existing worker boundary.

## 4. Explicitly removed architecture

Production synthesis must no longer depend on any of the following:

- native `piper.exe`
- Python Piper inference
- `calmwoman3688`
- NGHI-TTS sidecar
- portable Node runtime
- direct phoneme-ID handling
- Attendance-authored sentence splitting for TTS
- `sentence_silence`
- fixed zero-PCM pause insertion

Old local Piper/NGHI files may remain on disk after upgrade, but the new runtime must ignore them. Setup must not destructively delete old user-local runtime files.

## 5. Voice selection

Production constants:

```python
VOICE_ID = "Thùy Dung"
TTS_ENGINE = "vieneu-v3-turbo"
TTS_ENGINE_VERSION = "3.8.3"
TTS_BACKEND = "onnx-fp32"
```

`Thùy Dung` is a Southern preset and an upstream Editors' Pick. Setup must instantiate VieNeu and assert that `list_preset_voices()` contains a voice resolvable by the exact name `Thùy Dung` before declaring the installation ready.

The voice identifier remains centralized so a future A/B test can switch to another Southern preset such as `Mỹ Duyên`, `Kim Thanh`, or `Thục Đoan` without changing the worker protocol or service architecture.

## 6. Worker behavior

`tts_worker.py` remains a long-lived NDJSON worker.

At worker startup:

1. Import `Vieneu` only inside the isolated worker process.
2. Set Hugging Face offline mode for normal production runtime.
3. Construct exactly one engine instance using:

```python
Vieneu(
    mode="v3turbo",
    backend="onnx",
    precision="fp32",
)
```

4. Verify the configured voice exists.
5. Signal readiness to `tts_service.py` before accepting synthesis work.

For each synthesis request:

1. Preserve the existing normalized Unicode text from `tts_service.py`.
2. Call VieNeu inference with `voice="Thùy Dung"`.
3. Save the returned waveform as a 48 kHz WAV through the VieNeu-supported save path or equivalent lossless PCM output.
4. Return the existing success/error response schema.

The worker must not split sentences or insert silence itself. VieNeu's own normalization/chunk/gap logic is authoritative.

## 7. Worker startup and timeout contract

Model loading is materially heavier than the old Piper executable, so startup and per-request timeouts must be distinct.

- Worker startup timeout: generous bounded timeout (target 90 seconds) waiting for an explicit ready/failure signal.
- Warm synthesis timeout: separate bounded timeout (target 45 seconds) per request.
- A worker startup failure must return `TTSUnavailableError` or a stable equivalent, not hang the Attendance server.
- A synthesis failure must preserve current cleanup behavior: no partial WAV is published into the cache.
- Worker restart policy remains one retry after a crashed worker, not unbounded retries.

Exact timeout values may be adjusted during implementation tests, but bounded failure is mandatory.

## 8. Cache identity and migration

The new branch starts from `main`, where the current cache format is version 5. VieNeu therefore bumps:

```python
CACHE_FORMAT_VERSION = 6
```

The cache key continues to include normalized text and voice/engine identity. At minimum it must be sensitive to:

- cache format version
- `VOICE_ID`
- `TTS_ENGINE_VERSION`
- backend/precision identity
- normalized text

This prevents any `calmwoman3688` WAV from being reused after migration.

Existing cached files are left on disk and naturally become unreachable through the new keys. No destructive cache migration is required.

## 9. Setup-TTS.bat

`Setup-TTS.bat` becomes the single online bootstrap step for VieNeu.

It must:

1. Create/reuse `.venv-tts`.
2. Install the pinned `vieneu==3.8.3` runtime and required dependencies.
3. Verify the installed package version.
4. Configure an Attendance-owned Hugging Face cache directory under ignored runtime storage rather than relying on an arbitrary global user cache.
5. Instantiate `Vieneu(mode="v3turbo", backend="onnx", precision="fp32")` while online.
6. Verify the exact `Thùy Dung` preset exists.
7. Run a real smoke synthesis that forces the required v3 Turbo ONNX/model/codec artifacts to download.
8. Record a local setup manifest containing at least package version, selected voice, backend, setup timestamp, and resolved downloaded artifact filenames/sizes when discoverable.
9. Run the same smoke synthesis again with Hugging Face offline mode enabled.
10. Report setup success only if the offline smoke synthesis succeeds and produces a valid WAV.

The setup script must fail closed if the package, model artifacts, voice, or offline smoke test is incomplete.

## 10. Runtime offline guarantee

Normal Attendance runtime must explicitly set Hugging Face offline mode in the worker environment, e.g. `HF_HUB_OFFLINE=1`, and point Hugging Face cache variables to the Attendance-owned cache directory created during setup.

This has two purposes:

- no accidental network call during class/attendance use;
- setup completeness is tested rather than silently repaired at runtime.

If required local artifacts are missing, status/synthesis must report TTS unavailable and instruct the operator to rerun `Setup-TTS.bat` while online.

## 11. Check-TTS.bat and status contract

`Check-TTS.bat` remains read-only. It must not install, clone, or download anything.

`tts_service.get_status()` should expose at least:

```json
{
  "available": true,
  "voice": "Thùy Dung",
  "engine": "vieneu-v3-turbo",
  "engine_version": "3.8.3",
  "backend": "onnx-fp32",
  "runtime_present": true,
  "offline_assets_present": true,
  "cache_files": 0
}
```

`available=true` is allowed only when the isolated Python runtime, pinned VieNeu package, setup manifest/offline asset marker, and worker script are all present.

Status must remain read-only and must not instantiate VieNeu or trigger Hub access.

## 12. Existing API compatibility

The following are intentionally unchanged:

- `server_tts.py` public route shapes
- Random Picker integration
- `/api/tts/status`
- student/name synthesis endpoint semantics
- asynchronous precache scheduling after student writes
- browser `speechSynthesis` fallback when local TTS is unavailable
- atomic cache publication
- failure mapping to stable HTTP error responses

No database migration is required.

## 13. Text handling

Attendance continues to do only deterministic transport/cache normalization:

- Unicode NFC
- collapse repeated whitespace
- trim leading/trailing whitespace
- preserve case
- preserve punctuation

No pronunciation-specific rewriting should be added in Attendance. VieNeu receives the natural source sentence and owns linguistic normalization and prosody.

## 14. Acceptance sentences

At minimum test these exact utterances:

1. `Huỳnh Quốc Phước đã điểm danh thành công. Mời sinh viên tiếp theo.`
2. `Nguyễn Thị Thúy Quỳnh đã điểm danh thành công. Mời sinh viên tiếp theo.`
3. `Huỳnh Quốc Phước, bạn đã điểm danh thành công.`
4. `Bạn đã điểm danh thành công!`
5. `Bạn đã điểm danh thành công?`

Automated tests can establish WAV validity, selected backend/voice, cache invalidation, protocol behavior, and offline operation. They cannot establish subjective naturalness.

Final Windows listening acceptance must confirm:

- Southern female voice is recognizably natural rather than robotic;
- names are intelligible;
- the full stop between `thành công.` and `Mời` has a natural audible boundary;
- comma, exclamation, and question intonation are acceptable;
- no manual post-synthesis pause is required.

## 15. Automated test strategy

### Service tests

- cache version is 6;
- cache key changes with engine version/backend/voice;
- status is read-only;
- old Piper files are not considered runtime requirements;
- missing VieNeu setup marker/assets reports unavailable;
- worker launch uses `.venv-tts` and offline cache environment.

### Worker tests

Using a fake VieNeu object:

- worker constructs the configured v3 Turbo ONNX fp32 engine exactly once;
- configured voice is `Thùy Dung`;
- source text case/punctuation is preserved;
- inference output is written as a valid WAV;
- no Piper/NGHI/Node path is referenced;
- startup readiness and bounded failure behavior work;
- partial output is removed after inference/save failure.

### Setup/check contract tests

- setup pins `vieneu==3.8.3`;
- setup verifies preset voice;
- setup performs an online smoke synthesis;
- setup performs a second smoke synthesis under `HF_HUB_OFFLINE=1`;
- check script contains no download/install commands.

### CI

CI should run unit and contract tests without downloading the full model. A separate optional/manual or appropriately cached integration gate may instantiate real VieNeu if practical, but the mandatory repository CI must remain deterministic and reasonably lightweight.

The decisive real-model gate is the Windows setup/offline/listening test on the deployment machine.

## 16. Failure and fallback behavior

If VieNeu is unavailable or fails:

- Attendance itself continues running;
- the local TTS endpoint reports the established unavailable/synthesis error;
- browser fallback remains available;
- no corrupt/partial WAV is cached;
- no automatic fallback to Piper or NGHI occurs.

There will be one production local TTS backend, not a hidden chain of multiple engines.

## 17. Migration sequence

1. Create implementation from clean `main` on `feat/vieneu-southern-voice`.
2. Add RED tests describing VieNeu contracts.
3. Replace worker implementation.
4. Replace service runtime/status identity.
5. Replace setup/check scripts.
6. Update documentation and remove obsolete Piper-specific guidance from tracked files.
7. Run full repository regression tests.
8. Run Windows online setup.
9. Prove second smoke synthesis works with offline mode.
10. Listen to acceptance sentences.
11. Only after user acceptance, open/merge the VieNeu PR.
12. Close superseded NGHI/Piper PR #10 without merging.

## 18. Non-goals

This migration does not add:

- voice cloning;
- GPU support;
- web/API service mode for VieNeu;
- runtime voice picker UI;
- emotion tags;
- SSML;
- automatic pronunciation dictionary;
- deletion of the user's previous local Piper/NGHI assets.

Those can be considered separately after the default offline Southern voice is stable.

## 19. Decision summary

The approved production direction is:

```text
VieNeu-TTS v3 Turbo
+ Python SDK
+ ONNX CPU
+ fp32
+ preset "Thùy Dung"
+ long-lived isolated worker
+ Attendance-owned offline model cache
+ existing Attendance HTTP/cache/browser interfaces
```

The key design change is to stop reproducing prosody behavior around Piper/NGHI and delegate Vietnamese sentence normalization, chunking, gaps, and natural prosody to a TTS engine that natively provides them.
