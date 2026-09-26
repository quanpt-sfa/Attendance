# Offline Vietnamese TTS for Attendance — Design

Date: 2026-09-26
Status: Design approved in chat; implementation pending spec review

## 1. Goal

Add a lightweight, fully offline Vietnamese text-to-speech path for student names in Attendance. The system should pre-generate and cache audio after students are added or imported so Random Picker can play names immediately even when there is no Internet connection.

The default local voice is `vi_VN-vais1000-medium` used through Piper. Browser `speechSynthesis` remains a fallback only.

## 2. Scope

This change covers:

- one-time local TTS setup on Windows;
- an isolated Python virtual environment for Piper;
- local storage of the Vietnamese voice model outside Git;
- a long-lived local Piper worker process isolated from the Attendance Python environment;
- deterministic WAV caching by normalized text and voice revision;
- background precaching after student import, creation, or name update;
- a server endpoint that returns cached/synthesized WAV for one student;
- Random Picker playback that prefers local cached audio and falls back to browser speech synthesis;
- status/check tooling for the local TTS installation and cache.

This change does not replace the existing speech used for all messages in `scan.html`. It only changes student-name speech in Random Picker for the first implementation.

## 3. Architecture

### 3.1 Process boundary

The Attendance server continues to run with its current Python environment. Piper is not imported into that environment.

`tts_service.py` runs inside the Attendance server process and owns:

- name normalization;
- cache-key generation and cache lookup;
- runtime/model discovery;
- lifecycle of a local worker subprocess;
- serialized request/response communication with that worker;
- background precache submission;
- installation/status reporting.

`tts_worker.py` runs under `.venv-tts\Scripts\python.exe`. It is the only component that imports `piper`. It:

1. loads `vi_VN-vais1000-medium` lazily on first synthesis request;
2. stays alive so the model is not reloaded for every student name;
3. accepts newline-delimited JSON requests on stdin;
4. writes newline-delimited JSON results on stdout;
5. synthesizes to a caller-provided temporary WAV path;
6. writes diagnostic information only to stderr so stdout remains a machine-readable protocol.

The protocol is private to the local process and is not exposed over TCP or HTTP.

`server.py` contains only thin HTTP/database integration and calls `tts_service.py`; it contains no Piper implementation details.

### 3.2 Local filesystem layout

Runtime artifacts are local-only and ignored by Git:

```text
Attendance/
├── .venv-tts/
├── tts/
│   └── voices/
│       ├── vi_VN-vais1000-medium.onnx
│       └── vi_VN-vais1000-medium.onnx.json
└── tts_cache/
    ├── ab/
    │   └── abcd....wav
    └── ...
```

Git contains code, tests, setup scripts, and documentation only. It does not contain the Piper wheel, model, generated WAV files, or virtual environment.

### 3.3 Pinned runtime and voice

Pin the runtime to:

```text
piper-tts==1.8.0
```

Pin the voice artifacts to the `rhasspy/piper-voices` `v1.0.0` revision rather than downloading from a moving `main` branch.

Voice:

```text
vi_VN-vais1000-medium
sample rate: 22050 Hz
quality: medium
speakers: 1
voice revision: piper-voices-v1.0.0
```

The ONNX model SHA-256 currently published for that pinned artifact is:

```text
ec7c89e2c85f4d1edc24b6120c18aaf1bda614f06b511567eb9c7c0de15e2dab
```

`Setup-TTS.bat` verifies the downloaded ONNX file against this digest before reporting success.

### 3.4 Setup scripts

`Setup-TTS.bat` performs the one-time online setup:

1. locate `py`, `python`, or `python3`;
2. create `.venv-tts` if missing;
3. install `piper-tts==1.8.0` into that environment;
4. download the pinned `vi_VN-vais1000-medium.onnx` and JSON config into `tts/voices/` if missing;
5. verify the ONNX SHA-256;
6. run `tts_worker.py` in one-shot smoke-test mode to synthesize a short Vietnamese sample into a temporary WAV;
7. delete the smoke-test output;
8. report success or actionable failure.

After this setup finishes, normal TTS operation requires no Internet connection.

`Check-TTS.bat` runs a read-only diagnostic that reports installation state, pinned runtime/voice information, worker smoke status, and cache coverage without downloading or modifying dependencies.

## 4. Voice and cache identity

### 4.1 Name normalization

For synthesis and cache identity:

- Unicode is normalized to NFC;
- leading/trailing whitespace is removed;
- repeated internal whitespace is collapsed to one space;
- Vietnamese diacritics are preserved;
- letter case is preserved for synthesis text.

An empty normalized name is invalid and must not be synthesized.

### 4.2 Cache key

The cache key is:

```text
SHA256(cache_format_version + "\n" + voice_id + "\n" + voice_revision + "\n" + normalized_text)
```

Initial constants:

```text
cache_format_version = 1
voice_id = vi_VN-vais1000-medium
voice_revision = piper-voices-v1.0.0
```

The cache is content-addressed rather than student-ID-addressed. The same exact name using the same pinned voice can therefore be reused across classes and records.

A student name change or voice revision change naturally generates a different key. Old unreferenced WAV files may remain until a future cleanup feature; automatic garbage collection is outside this scope.

## 5. TTS service and worker interfaces

### 5.1 Attendance-side service

`tts_service.py` exposes functions equivalent to:

```python
get_status() -> dict
normalize_text(text: str) -> str
cache_key(text: str) -> str
get_cached_audio(text: str) -> Path | None
ensure_audio(text: str) -> Path
precache_students(students: list[dict]) -> dict
shutdown_worker() -> None
```

`ensure_audio()` behavior:

1. normalize text;
2. calculate cache key;
3. return existing WAV if valid;
4. create a unique temporary output path inside the cache tree;
5. ensure the isolated worker subprocess is alive;
6. send one synth request to the worker;
7. require a successful worker response and a non-empty valid WAV output;
8. atomically rename the completed temporary file into the final cache path;
9. return the final WAV path.

A process-local lock protects worker communication and same-process cache creation. The final cache existence check is repeated after the lock is acquired so concurrent callers can reuse a file created by the first caller.

### 5.2 Worker protocol

A synth request has this conceptual form:

```json
{"id":"request-id","action":"synthesize","text":"Nguyễn Văn An","output":"C:\\...\\temporary.wav"}
```

A success response has this form:

```json
{"id":"request-id","ok":true}
```

A failure response has this form:

```json
{"id":"request-id","ok":false,"error":"message"}
```

The service validates response IDs. Malformed output, EOF, timeout, or worker death is treated as a worker failure.

On worker failure the service may restart the worker once for the current request. If the retry fails, `ensure_audio()` reports TTS unavailable/synthesis failure and the frontend fallback path remains active.

The worker must never make network requests.

## 6. Background precaching

Precache is triggered after successful database persistence for these operations:

- bulk student import;
- single student creation;
- student name update.

The HTTP write operation must not wait for a whole class to synthesize. After the database transaction commits, the server submits a background daemon thread to precache the affected names.

Only one precache job should actively synthesize at a time because the single Piper worker is serialized. Repeated triggers may enqueue additional names, but cache hits make duplicate work inexpensive.

Precache failures are logged but do not roll back student data.

The worker skips cache hits. If Piper is not installed, it exits cleanly and leaves browser fallback available.

No new database schema is required for cache metadata in this version because cache identity is deterministic from text and configuration.

## 7. HTTP API

### 7.1 Student audio

Add:

```text
GET /api/tts/student/<student_id>?class_id=<class_id>
```

Behavior:

1. find the student by `(student_id, class_id)`;
2. return `404` if the student does not exist;
3. use `full_name` as TTS text;
4. return `422` if the name is empty;
5. call `ensure_audio()`;
6. return WAV bytes with `Content-Type: audio/wav` and cache-friendly headers.

If local TTS is unavailable because setup/model/runtime is missing, return `503` JSON with:

```json
{"error":"tts_unavailable"}
```

If synthesis fails after runtime validation, return `503` JSON with:

```json
{"error":"tts_synthesis_failed"}
```

This allows the frontend to distinguish local-TTS failure from a missing student or generic server failure.

### 7.2 Status

Add:

```text
GET /api/tts/status
```

Return fields including:

```json
{
  "available": true,
  "voice": "vi_VN-vais1000-medium",
  "voice_revision": "piper-voices-v1.0.0",
  "runtime_present": true,
  "model_present": true,
  "model_checksum_ok": true,
  "worker_running": false,
  "cache_files": 42
}
```

The endpoint is read-only. It does not install dependencies, download files, or start the Piper worker merely to report status.

## 8. Random Picker playback

Random Picker keeps its current visual and selection behavior.

Database-backed student objects must retain `class_id` through the Random Picker mapping layer so the TTS endpoint can address the correct student record.

When a winner is selected:

1. cancel browser `speechSynthesis` and stop any previously playing local name audio;
2. if the selected record has both student ID and class ID, request `/api/tts/student/...`;
3. if HTTP 200 returns WAV, play it through `Audio`;
4. if the endpoint returns `503`, cannot be reached, returns invalid audio, or browser audio playback rejects, use the existing Vietnamese `speechSynthesis` logic;
5. do not play both engines for the same selection.

Standalone Random Picker already limits database-backed selection to checked-in students of the open session. That behavior remains unchanged.

Excel-only Random Picker entries may not have a class/database identity. Those entries continue to use browser `speechSynthesis`. A text-only TTS endpoint is outside this scope to avoid exposing arbitrary synthesis unnecessarily.

## 9. Configuration

Keep TTS configuration in `tts_service.py` or a focused constants module:

```text
piper_runtime_version = 1.8.0
voice_id = vi_VN-vais1000-medium
voice_revision = piper-voices-v1.0.0
cache_format_version = 1
venv_python = .venv-tts/Scripts/python.exe
voice_dir = tts/voices
cache_dir = tts_cache
```

No API key or network credential is required.

Runtime/model/cache paths resolve relative to the Attendance project directory and must work when the server is launched from `Start-Server.bat` on Windows.

## 10. Failure handling

### Piper virtual environment not installed

- Attendance server continues to run;
- `/api/tts/status` reports unavailable;
- `/api/tts/student/...` returns `503 tts_unavailable`;
- Random Picker falls back to browser speech synthesis.

### Model files missing, wrong checksum, or corrupt

Same behavior as runtime unavailable. The service must not crash server startup and must not start the worker.

### Worker exits or protocol breaks

- service discards the dead worker;
- it may restart once for the current request;
- if retry fails, no final cache file is created;
- endpoint returns a TTS failure and frontend falls back.

### Synthesis fails for one name

- log the student/name and exception;
- remove any temporary output;
- do not leave a partial final cache file;
- frontend falls back to browser speech synthesis.

### Concurrent requests for the same name

Only one final cache file is created within the Attendance process. Callers wait on the serialized worker/cache lock and reuse the completed file.

### No Internet

After `Setup-TTS.bat` has successfully completed once, worker startup, synthesis, caching, precaching, and playback operate locally.

## 11. Git hygiene

Add these local artifacts to `.gitignore`:

```text
.venv-tts/
tts/voices/
tts_cache/
```

Do not commit model weights, generated audio, virtual environments, or temporary synthesis files.

## 12. Testing

Implementation follows TDD. Tests must cover at least:

1. name normalization preserves Vietnamese text and collapses whitespace;
2. identical text/voice/revision produces identical cache key;
3. changed name, voice, or voice revision produces a different cache key;
4. cache hit does not invoke the worker;
5. cache miss invokes synthesis once and creates a WAV atomically;
6. concurrent same-key requests do not create duplicate synthesis work;
7. missing virtual environment/model reports unavailable without crashing import/server startup;
8. bad model checksum reports unavailable and does not launch the worker;
9. worker protocol validates request/response IDs;
10. worker failure/restart path does not leave partial final files;
11. student audio endpoint returns `404` for missing student;
12. endpoint returns `503` when local TTS is unavailable;
13. endpoint returns `audio/wav` for a cached/created student name;
14. precache is triggered only after successful student persistence and does not block the HTTP response on class-wide generation;
15. frontend local-audio success suppresses browser speech synthesis;
16. frontend local-audio failure invokes browser fallback;
17. database-backed picker mappings preserve `class_id`;
18. existing Random Picker attendance-only tests continue to pass;
19. existing database schema/startup tests continue to pass.

Tests use temporary directories and fake worker/synthesizer processes. Automated tests do not download the real model or require Piper to be installed.

A separate manual smoke test after setup verifies the real pinned runtime and model on Windows.

## 13. Acceptance criteria

The feature is complete when all of the following are true:

- running Attendance without TTS installed still works as before;
- `Setup-TTS.bat` installs the isolated local runtime and pinned Vietnamese model once;
- the Attendance Python environment does not need the `piper` package installed;
- after setup, disconnecting the machine from the Internet does not prevent generation or playback of student-name audio;
- imported/added/renamed students are precached asynchronously;
- Random Picker normally plays local Piper WAV for database students;
- cache hits play without invoking Piper again;
- browser speech synthesis remains a working fallback;
- model/runtime/cache files remain outside Git;
- the automated test suite passes;
- the Windows real-model smoke test succeeds after setup.

## 14. Future extensions explicitly deferred

The following are not part of this implementation:

- replacing every `scan.html` spoken message with Piper;
- per-student custom pronunciation text;
- GUI voice selection;
- multiple installed voices;
- cache garbage collection;
- arbitrary text-to-speech API;
- packaging the voice/model inside Git or a distributable installer.
