# NGHI Frontend → Piper/ONNX Vietnamese TTS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace stock-Piper Vietnamese text processing with the pinned NGHI-TTS linguistic frontend, feed its exact phoneme IDs directly to `calmwoman3688` ONNX inference, and keep the existing Attendance cache/API/browser contract unchanged.

**Architecture:** A long-lived portable-Node sidecar runs the exact pinned NGHI preprocessing/chunking/phonemization path and returns ordered scalar phoneme-ID arrays over private NDJSON. The isolated Python TTS worker keeps the ONNX model loaded and calls only `PiperVoice.phoneme_ids_to_audio()` for those IDs, appending model outputs directly into one WAV without synthetic silence. `tts_service.py`, HTTP routes, precache, and Random Picker remain the outer contract.

**Tech Stack:** Python 3 / `piper-tts==1.8.0` / ONNX Runtime; Node.js `v22.23.3`; pinned `nghimestudio/nghitts@46d160da32041f7e176607203b958069265df7da`; `phonemizer-1.2.2.tgz`; NDJSON subprocess protocol; `unittest` and Node assertion tests; GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-28-nghi-frontend-onnx-design.md`

## Global Constraints

- Work only on `feat/nghi-frontend-onnx`; do not merge or cherry-pick the rejected stock-Piper experiment wholesale.
- Voice stays `calmwoman3688` from `sannht/vi_voice@62e57b18157ed213b3863a7a8a35b14d3404554b`, sample rate 22050 Hz.
- NGHI source is pinned to commit `46d160da32041f7e176607203b958069265df7da`.
- Python inference runtime is pinned to `piper-tts==1.8.0`; its text phonemizer must never be used in production synthesis.
- Portable Node is pinned to `v22.23.3`; production must not require global Node.
- Preserve source case and punctuation through Attendance normalization; do not lowercase before NGHI.
- NGHI defaults must be reproduced at inference: `speaker_id=0`, `length_scale=1.0`, `noise_scale=0.667`, `noise_w_scale=0.8`.
- No regex sentence splitter, `--sentence-silence`, explicit silence samples, SSML, or post-synthesis pause insertion.
- `CACHE_FORMAT_VERSION` becomes `6`; old version-5 WAVs are not reused.
- Existing `/api/tts/status`, `/api/tts/student/<student_id>?class_id=...`, precache, and browser fallback contracts remain compatible.
- Model/runtime/source/npm/cache artifacts remain outside Git and normal synthesis must work offline after setup.

## Review Focus

- Windows paths containing spaces or non-ASCII characters: Node sidecar and Python worker must receive exact paths without shell parsing; owning tests are in Tasks 2 and 4.
- Sidecar diagnostics contaminating stdout: stdout must remain NDJSON-only even when NGHI debug/warnings fire; owning test is in Task 1.
- Mixed-case/acronym and punctuation inputs: source case must reach NGHI unchanged and `,` must stay intra-chunk while `.?!` follow NGHI chunking; owning tests are in Tasks 1 and 5.
- Malformed frontend payloads: nested IDs, floats, strings, empty chunks, mismatched IDs, EOF, and timeout must fail closed without publishing partial WAV; owning tests are in Tasks 1 and 2.
- Offline runtime incompleteness: missing Node, NGHI checkout, npm assets, Python runtime, model, or config must leave Attendance usable and report local TTS unavailable rather than starting downloads; owning tests are in Tasks 3 and 4.

---

### Task 1: Production NGHI frontend sidecar

**Files:**
- Create: `tts/nghi_frontend.mjs`
- Create: `test_nghi_frontend.mjs`
- Reuse/reference: `tools/nghi_phoneme_audit.mjs`
- Reference upstream: pinned NGHI `src/utils/text-cleaner.js`, `src/lib/piper-tts.js`

**Interfaces:**
- Consumes: CLI arguments `--nghi-root <path> --voice-config <path> --expected-commit <sha>` and NDJSON requests on stdin.
- Produces: NDJSON response `{id, ok, processed_text, chunks:[{text, phoneme_ids}]}` with scalar integer IDs and stderr-only diagnostics.

- [ ] **Step 1: Write failing Node protocol tests**

Add tests named:

```text
test_preserves_request_id_and_source_case
test_case2_returns_two_chunks
test_comma_stays_inside_one_chunk
test_question_and_exclamation_follow_nghi_chunking
test_phoneme_ids_are_scalar_integers
test_malformed_request_returns_json_error_only_on_stdout
test_nghi_debug_output_stays_on_stderr
```

Use dependency injection/module exports for the pure request handler so these tests do not need a network listener. Assert that the two-sentence case produces exactly two ordered chunks and that the adapter does not lowercase or split text itself.

- [ ] **Step 2: Run the Node tests and verify RED**

Run:

```bash
node test_nghi_frontend.mjs
```

Expected: FAIL because `tts/nghi_frontend.mjs` and/or its exported handler do not exist.

- [ ] **Step 3: Implement the sidecar adapter**

In `tts/nghi_frontend.mjs`, provide these focused interfaces:

```js
export function toOnnxScalarIds(rawIds) -> number[]
export async function createNghiFrontend({ nghiRoot, voiceConfigPath, expectedCommit }) -> frontend
export async function processFrontendRequest(frontend, request) -> object
export async function serveNdjson({ stdin, stdout, stderr, frontend }) -> void
```

`createNghiFrontend()` must import and invoke the pinned NGHI `processTextForTTS()`, `chunkText()`, `PiperTTS.textToPhonemes()`, and `PiperTTS.phonemesToIds()` rather than reproducing those rules. Reuse the proven local-file `fetch` shim semantics from `tools/nghi_phoneme_audit.mjs`. Redirect NGHI `console.log`/`console.warn` diagnostics to stderr and verify the local checkout commit before serving.

- [ ] **Step 4: Run Node tests and syntax check**

Run:

```bash
node --check tts/nghi_frontend.mjs
node test_nghi_frontend.mjs
```

Expected: syntax check succeeds; all sidecar tests PASS.

- [ ] **Step 5: Commit Task 1**

```bash
git add tts/nghi_frontend.mjs test_nghi_frontend.mjs
git commit -m "feat: add pinned NGHI frontend sidecar"
```

---

### Task 2: Python worker inference from exact phoneme IDs

**Files:**
- Modify: `tts_worker.py`
- Modify: `test_tts_worker.py`

**Interfaces:**
- Consumes: ordered frontend chunks from Task 1 via a long-lived Node subprocess.
- Produces: one valid mono 16-bit PCM WAV by calling `PiperVoice.phoneme_ids_to_audio(ids, SynthesisConfig(...))` once per NGHI chunk, plus existing worker NDJSON success/failure responses.

- [ ] **Step 1: Write failing Python worker tests**

Add/replace tests for:

```text
test_frontend_client_passes_source_case_and_validates_matching_id
test_frontend_client_rejects_empty_chunks_nested_ids_float_ids_and_eof
test_frontend_client_restarts_once_after_sidecar_failure
test_synthesizer_calls_phoneme_ids_to_audio_per_chunk_in_order
test_synthesizer_uses_nghi_default_scales_and_speaker_zero
test_synthesizer_appends_chunk_audio_without_inserted_samples
test_synthesizer_never_calls_piper_text_frontend
test_partial_output_is_removed_on_frontend_failure
test_partial_output_is_removed_on_second_chunk_inference_failure
test_sidecar_command_handles_windows_paths_as_argument_list
```

Use fake sidecar processes and a fake Piper voice returning small deterministic float arrays. Assert output frames are exactly the concatenation of model arrays, with no extra frames between chunks.

- [ ] **Step 2: Run focused worker tests and verify RED**

Run:

```bash
python -m unittest test_tts_worker -v
```

Expected: new tests FAIL against the native-Piper/current Python-Piper implementation.

- [ ] **Step 3: Implement the sidecar client and ID-only synthesizer**

Refactor `tts_worker.py` around these interfaces:

```python
class NghiFrontendClient:
    def __init__(self, node_exe: Path, adapter_path: Path, nghi_root: Path, voice_config: Path, expected_commit: str, process_factory=subprocess.Popen): ...
    def process(self, text: str) -> dict: ...
    def close(self) -> None: ...

class NghiOnnxSynthesizer:
    def __init__(self, model_path: Path, config_path: Path, frontend: NghiFrontendClient): ...
    def __call__(self, text: str, output: Path) -> None: ...
    def close(self) -> None: ...
```

Load `PiperVoice` once with the exact model/config path. Call only `phoneme_ids_to_audio()` for production text. Convert returned float audio to clipped signed 16-bit PCM and append chunks directly. Preserve the existing outer worker request protocol and root-error preservation behavior.

- [ ] **Step 4: Run focused worker tests and syntax check**

Run:

```bash
python -m py_compile tts_worker.py
python -m unittest test_tts_worker -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add tts_worker.py test_tts_worker.py
git commit -m "feat: synthesize from NGHI phoneme ids"
```

---

### Task 3: Service runtime contract, cache v6, and read-only status

**Files:**
- Modify: `tts_service.py`
- Modify: `test_tts_service.py`
- Modify: `test_tts_integration.py`

**Interfaces:**
- Consumes: local paths for `.venv-tts`, portable Node, pinned NGHI checkout, adapter, voice model/config, and the worker from Task 2.
- Produces: unchanged public `tts_service` API and worker launch command containing all required local runtime paths.

- [ ] **Step 1: Write failing service/integration tests**

Pin these behaviors:

```text
CACHE_FORMAT_VERSION == 6
backend == "nghi-frontend+python-piper-onnx"
available requires Python + Node + NGHI + adapter + model/config
get_status does not launch Python worker or Node sidecar
worker command contains --node, --nghi-root, --nghi-adapter, --nghi-commit
worker command no longer contains --native-piper
source-case text survives service normalization
missing any runtime component reports unavailable without breaking imports/startup
```

Also preserve legacy compatibility keys such as `runtime_present` and `model_present` where current callers/tests rely on them.

- [ ] **Step 2: Run service/integration tests and verify RED**

Run:

```bash
python -m unittest test_tts_service test_tts_integration -v
```

Expected: FAIL on cache version, backend/runtime requirements, and worker command.

- [ ] **Step 3: Implement runtime discovery and worker launch contract**

Add exact constants/paths in `tts_service.py` for:

```text
NGHI_COMMIT = 46d160da32041f7e176607203b958069265df7da
NODE_EXE = tts/runtime/node/node.exe
NGHI_ROOT = tts/runtime/nghitts
NGHI_ADAPTER = tts/nghi_frontend.mjs
CACHE_FORMAT_VERSION = 6
```

Update `_runtime_state()`, `get_status()`, and `_start_worker_locked()` to require and pass these components without importing TTS dependencies in the Attendance server process. Remove native-Piper executable from the production availability check and launch command.

- [ ] **Step 4: Run service/integration tests**

Run:

```bash
python -m unittest test_tts_service test_tts_integration -v
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```bash
git add tts_service.py test_tts_service.py test_tts_integration.py
git commit -m "feat: route TTS service through NGHI frontend runtime"
```

---

### Task 4: One-time offline runtime setup and diagnostics

**Files:**
- Modify: `Setup-TTS.bat`
- Modify: `Check-TTS.bat`
- Modify: `test_tts_worker.py` or create `test_tts_setup.py` if setup assertions become unwieldy
- Verify: `.gitignore`

**Interfaces:**
- Consumes: Internet only during setup; official Node distribution, pinned NGHI commit, pinned voice/model, `piper-tts==1.8.0`.
- Produces: `.venv-tts`, `tts/runtime/node/`, `tts/runtime/nghitts/` with local npm dependencies, and existing voice files; no downloads occur during normal synthesis.

- [ ] **Step 1: Write failing setup/status contract tests**

Assert that `Setup-TTS.bat`:

```text
pins piper-tts==1.8.0
pins Node v22.23.3
uses node-v22.23.3-win-x64.zip
verifies the Node ZIP against the matching entry in official SHASUMS256.txt before extraction
installs NGHI at exact commit 46d160...
verifies git rev-parse HEAD (or equivalent archive identity) equals that commit
runs npm ci for the pinned NGHI package/lock data
runs the smoke test through the production NGHI frontend path
never downloads legacy piper_windows_amd64.zip
```

Add checks that paths are passed as quoted arguments so a project directory containing spaces is valid. Assert `Check-TTS.bat` is read-only and reports Python, Node, NGHI, model, and backend state without installation/download actions.

- [ ] **Step 2: Run setup contract tests and verify RED**

Run:

```bash
python -m unittest test_tts_worker -v
```

(or `python -m unittest test_tts_setup -v` if split in Step 1).

Expected: FAIL because current setup installs native Piper 2023 and no portable Node/NGHI runtime.

- [ ] **Step 3: Implement the setup migration**

Update `Setup-TTS.bat` to:

1. create/reuse `.venv-tts` and install exactly `piper-tts==1.8.0`;
2. download Node `v22.23.3` Windows x64 ZIP plus official `SHASUMS256.txt`, compare the ZIP hash to the file's `node-v22.23.3-win-x64.zip` entry, then extract to `tts/runtime/node/`;
3. obtain NGHI at exactly `46d160...` into `tts/runtime/nghitts/`, verify identity, and install its locked production dependencies using the portable Node/npm;
4. download/reuse the already pinned `calmwoman3688` model/config with existing SHA checks;
5. run a production-path smoke synthesis and remove its temporary WAV.

Do not make `Check-TTS.bat` mutate installation state.

- [ ] **Step 4: Run setup contract tests and script/static checks**

Run:

```bash
python -m unittest test_tts_worker -v
```

Expected: PASS. On Windows acceptance later, `Setup-TTS.bat` must also complete from a path containing spaces.

- [ ] **Step 5: Commit Task 4**

```bash
git add Setup-TTS.bat Check-TTS.bat test_tts_worker.py .gitignore
git commit -m "feat: install pinned NGHI frontend runtime"
```

---

### Task 5: Golden NGHI parity and production audit

**Files:**
- Modify: `tools/nghi_phoneme_audit.mjs`
- Modify: `tools/tts_phoneme_audit.py`
- Modify: `tools/tts_phoneme_audit.ps1`
- Modify: `test_tts_audit.py`
- Add if useful: `tools/nghi_frontend_golden.json`

**Interfaces:**
- Consumes: the same pinned NGHI checkout/config as production and the production sidecar from Task 1.
- Produces: deterministic parity assertions/report for the five fixed cases: `processed_text`, chunk count, chunk text, and element-by-element phoneme IDs.

- [ ] **Step 1: Write failing parity tests**

Add tests that execute/compare the audit path and production frontend contract for all five fixed cases. Hard-code the Case 2 requirement:

```python
assert len(case2["chunks"]) == 2
```

Assert source-case input remains unchanged before NGHI, comma remains in one chunk, and the known NGHI tone IDs represented in the prior audit are present where expected. Reject any production/audit mismatch element by element.

- [ ] **Step 2: Run audit tests and verify RED**

Run:

```bash
python -m unittest test_tts_audit -v
node --check tools/nghi_phoneme_audit.mjs
```

Expected: FAIL until the audit invokes/compares the new production frontend.

- [ ] **Step 3: Refactor audit tooling around the production adapter**

Keep the existing independent pinned-NGHI audit as the oracle. Add a production-sidecar capture path and report differences without reimplementing either frontend. Ensure the PowerShell audit uses local pinned Node/NGHI paths installed by `Setup-TTS.bat`, not global Node.

- [ ] **Step 4: Run parity tests**

Run:

```bash
python -m unittest test_tts_audit -v
```

Expected: PASS for all five cases with exact phoneme-ID parity and exactly two Case 2 chunks.

- [ ] **Step 5: Commit Task 5**

```bash
git add tools test_tts_audit.py
git commit -m "test: enforce NGHI frontend phoneme parity"
```

---

### Task 6: CI real-runtime gate and whole-repo regression

**Files:**
- Modify: `.github/workflows/feature-tts-tests.yml`
- Modify as needed from failures: production/test files owned by Tasks 1-5

**Interfaces:**
- Consumes: all Task 1-5 code.
- Produces: automated evidence that the pinned real NGHI frontend and full Attendance regression suite pass on the branch.

- [ ] **Step 1: Add a failing real-runtime CI gate**

Extend the workflow to:

1. run Python syntax and existing regression suites;
2. run `node --check` for the production sidecar and Node tests;
3. install/materialize the pinned NGHI runtime used for CI;
4. run the five-case parity check against the real pinned frontend;
5. assert Case 2 has exactly two chunks and production IDs equal the independent audit oracle;
6. run existing JavaScript Random Picker tests.

Do not add stock-Piper sentence segmentation as a gate.

- [ ] **Step 2: Run/push and verify the new gate fails for any unresolved integration gap**

Expected: the branch workflow must not be accepted until every real-runtime/parity step is green.

- [ ] **Step 3: Fix only integration defects exposed by the real gate**

Keep fixes inside the boundaries defined by the spec: no manual pause insertion and no fallback to stock Piper phonemization.

- [ ] **Step 4: Run the complete local regression commands**

Run:

```bash
python -m py_compile startup.py tts_service.py tts_worker.py server_tts.py tools/tts_phoneme_audit.py
python -m unittest test_db_schema test_startup -v
python -m unittest test_tts_service test_tts_worker test_server_tts test_tts_integration -v
python -m unittest test_tts_audit -v
node --check random-picker.js
node --check random-picker-attendance.js
node --check random-picker-speech.js
node --check tts/nghi_frontend.mjs
node --check tools/nghi_phoneme_audit.mjs
node test_nghi_frontend.mjs
node test_random_picker_attendance.js
node test_random_picker_speech.js
```

Expected: all PASS.

- [ ] **Step 5: Commit Task 6**

```bash
git add .github/workflows/feature-tts-tests.yml
git commit -m "ci: verify real NGHI frontend parity"
```

---

### Task 7: Documentation, branch verification, and Windows acceptance handoff

**Files:**
- Modify: `README.md`
- Review: `docs/superpowers/specs/2026-09-28-nghi-frontend-onnx-design.md`
- Review: all changed files versus `main`

**Interfaces:**
- Consumes: green branch from Tasks 1-6.
- Produces: accurate operator instructions and a branch ready for Windows listening acceptance before merge.

- [ ] **Step 1: Update README installation/runtime description**

Document that setup installs portable Node + pinned NGHI + Python Piper inference, that normal synthesis is offline, and that the backend is `nghi-frontend+python-piper-onnx`. Remove any claim that production uses native Piper 2023 or stock Piper phonemization.

- [ ] **Step 2: Verify diff scope and no runtime artifacts are tracked**

Run/inspect:

```bash
git diff --stat main...HEAD
git status --short
git ls-files .venv-tts tts/runtime tts/voices tts_cache
```

Expected: only source/tests/docs/workflow changes are tracked; runtime/model/cache artifacts are absent.

- [ ] **Step 3: Run final automated verification before claiming completion**

Repeat the complete Task 6 regression command set and require the latest branch CI run to conclude `success`.

- [ ] **Step 4: Commit documentation**

```bash
git add README.md
git commit -m "docs: describe NGHI frontend TTS runtime"
```

- [ ] **Step 5: Windows acceptance instructions**

On the actual Attendance Windows machine:

```powershell
cd D:\Works\attendance
git checkout feat/nghi-frontend-onnx
git pull
.\Setup-TTS.bat
.\Check-TTS.bat
.\tools\tts_phoneme_audit.ps1
$wav = .\.venv-tts\Scripts\python.exe -c "import tts_service; print(tts_service.ensure_audio('Huỳnh Quốc Phước đã điểm danh thành công. Mời sinh viên tiếp theo.'))"
Start-Process $wav
```

Acceptance requires: setup succeeds; status is ready; audit shows two NGHI chunks with parity; one WAV plays; a perceptible sentence boundary is heard without inserted silence; Vietnamese tone pronunciation is correct. This perceptual gate is required before merging to `main`.

- [ ] **Step 6: Do not merge before user listening acceptance**

Open/update the PR with automated evidence, but leave it unmerged until the user confirms the Windows listening test.
