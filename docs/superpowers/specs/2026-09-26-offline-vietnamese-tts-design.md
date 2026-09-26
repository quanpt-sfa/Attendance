# Offline Vietnamese TTS for Attendance — Design

Date: 2026-09-26
Status: Design approved in chat; implementation pending spec review

## 1. Goal

Add a lightweight, fully offline Vietnamese text-to-speech path for student names in Attendance. The system should pre-generate and cache audio after students are added or imported so Random Picker can play names immediately even when there is no Internet connection.

The default local voice is `vi_VN-vais1000-medium` used through Piper. Browser `speechSynthesis` remains a fallback only.

## 2. Scope

This change covers:

- one-time local TTS setup on Windows;
- a dedicated Python virtual environment for Piper;
- local storage of the Vietnamese voice model outside Git;
- deterministic WAV caching by normalized text and voice identity;
- background precaching after student import, creation, or name update;
- a server endpoint that returns cached/synthesized WAV for one student;
- Random Picker playback that prefers local cached audio and falls back to browser speech synthesis;
- status/check tooling for the local TTS installation and cache.

This change does not replace the existing speech used for all messages in `scan.html`. It only changes student-name speech in Random Picker for the first implementation.

## 3. Architecture

### 3.1 Runtime components

`tts_service.py` is the single Python boundary for local TTS. It owns:

- voice/model discovery;
- name normalization;
- cache-key generation;
- Piper model loading;
- synthesis;
- cache lookup;
- class-level precache operations;
- installation/status reporting.

`server.py` should not contain Piper-specific implementation details. It imports and calls the service through a small interface.

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

### 3.3 Setup scripts

`Setup-TTS.bat` performs the one-time online setup:

1. locate `py`, `python`, or `python3`;
2. create `.venv-tts` if missing;
3. install the pinned Piper Python package into that environment;
4. download `vi_VN-vais1000-medium.onnx` and its JSON config into `tts/voices/` if missing;
5. run a local synthesis smoke test;
6. report success or actionable failure.

After this setup finishes, normal TTS operation requires no Internet connection.

`Check-TTS.bat` runs a read-only diagnostic that reports installation state and cache coverage without downloading or modifying anything.

## 4. Voice and cache identity

### 4.1 Default voice

Default voice identifier:

```text
vi_VN-vais1000-medium
```

The voice identifier and a TTS cache format version are included in cache identity so a future voice/model change does not reuse incompatible audio.

### 4.2 Name normalization

For synthesis and cache identity:

- Unicode is normalized to NFC;
- leading/trailing whitespace is removed;
- repeated internal whitespace is collapsed to one space;
- Vietnamese diacritics are preserved;
- letter case is preserved for synthesis text.

An empty normalized name is invalid and must not be synthesized.

### 4.3 Cache key

The cache key is:

```text
SHA256(cache_format_version + "\n" + voice_id + "\n" + normalized_text)
```

The cache is content-addressed rather than student-ID-addressed. The same exact name using the same voice can therefore be reused across classes and records.

A student name change naturally generates a different key. Old unreferenced WAV files may remain until a future cleanup feature; automatic garbage collection is outside this scope.

## 5. TTS service interface

The service exposes functions equivalent to:

```python
get_status() -> dict
normalize_text(text: str) -> str
cache_key(text: str) -> str
get_cached_audio(text: str) -> Path | None
ensure_audio(text: str) -> Path
precache_students(students: list[dict]) -> dict
```

`ensure_audio()` behavior:

1. normalize text;
2. calculate cache key;
3. return existing WAV if valid;
4. otherwise load Piper lazily;
5. synthesize to a temporary file;
6. atomically rename the completed file into the cache;
7. return the final WAV path.

Model loading is lazy and process-local. A lock protects initial model load and synthesis/cache creation so concurrent requests cannot create the same file simultaneously.

## 6. Background precaching

Precache is triggered after successful database persistence for these operations:

- bulk student import;
- single student creation;
- student name update.

The HTTP write operation must not wait for a whole class to synthesize. After the database transaction commits, the server submits a background daemon thread/task to precache the affected names.

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

If local TTS is unavailable because setup/model is missing, return `503` JSON with a stable machine-readable error code such as:

```json
{"error":"tts_unavailable"}
```

This is intentional so the frontend can distinguish local-TTS absence from a missing student or generic server failure.

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
  "model_present": true,
  "runtime_present": true,
  "cache_files": 42
}
```

The endpoint is read-only and does not install or download anything.

## 8. Random Picker playback

Random Picker keeps its current visual and selection behavior.

When a winner is selected:

1. cancel/stop any currently playing name audio;
2. if the selected record has a student ID and class context, request `/api/tts/student/...`;
3. if HTTP 200 returns WAV, play it through `Audio`;
4. if the endpoint returns `503`, cannot be reached, or playback fails, use the existing Vietnamese `speechSynthesis` logic;
5. do not play both engines for the same selection.

Standalone Random Picker already limits database-backed selection to checked-in students of the open session. That behavior remains unchanged.

Excel-only Random Picker entries may not have a class/database identity. Those entries continue to use browser `speechSynthesis` unless a future text-only TTS endpoint is added. A text-only endpoint is outside this scope to avoid exposing arbitrary synthesis unnecessarily.

## 9. Configuration

Keep TTS configuration in one Python module or constants section, including:

```text
voice_id = vi_VN-vais1000-medium
cache_format_version = 1
voice_dir = tts/voices
cache_dir = tts_cache
```

No API key or network credential is required.

Runtime/model/cache paths must resolve relative to the Attendance project directory and must work when the server is launched from `Start-Server.bat`.

## 10. Failure handling

Expected states:

### Piper not installed

- Attendance server continues to run;
- `/api/tts/status` reports unavailable;
- `/api/tts/student/...` returns `503 tts_unavailable`;
- Random Picker falls back to browser speech synthesis.

### Model files missing or corrupt

Same behavior as Piper unavailable. The service must not crash server startup.

### Synthesis fails for one name

- log the student/name and exception;
- do not leave a partial final cache file;
- return `503` or synthesis-specific failure;
- frontend falls back to browser speech synthesis.

### Concurrent requests for the same name

Only one final cache file is created. Callers either wait for the protected synthesis or consume the completed cache file.

### No Internet

After `Setup-TTS.bat` has successfully completed once, all normal synthesis and playback paths operate locally.

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
2. identical text/voice produces identical cache key;
3. changed name or changed voice produces a different cache key;
4. cache hit does not invoke synthesis;
5. cache miss invokes synthesis once and creates a WAV atomically;
6. concurrent same-key requests do not create duplicate synthesis work;
7. missing Piper/model reports unavailable without crashing import/server startup;
8. student audio endpoint returns `404` for missing student;
9. endpoint returns `503` when local TTS is unavailable;
10. endpoint returns `audio/wav` for a cached/created student name;
11. precache is triggered only after successful student persistence and does not block the HTTP response on class-wide generation;
12. frontend local-audio success suppresses browser speech synthesis;
13. frontend local-audio failure invokes browser fallback;
14. existing Random Picker attendance-only tests continue to pass;
15. existing database schema/startup tests continue to pass.

Tests must use temporary directories and fake synthesizers/models; automated tests must not require downloading the real model.

## 13. Acceptance criteria

The feature is complete when all of the following are true:

- running Attendance without TTS installed still works as before;
- `Setup-TTS.bat` installs the local runtime and Vietnamese model once;
- after setup, disconnecting the machine from the Internet does not prevent generation or playback of student-name audio;
- imported/added/renamed students are precached asynchronously;
- Random Picker normally plays local Piper WAV for database students;
- cache hits play without invoking Piper again;
- browser speech synthesis remains a working fallback;
- model/runtime/cache files remain outside Git;
- the full automated test suite passes.

## 14. Future extensions explicitly deferred

The following are not part of this implementation:

- replacing every `scan.html` spoken message with Piper;
- per-student custom pronunciation text;
- GUI voice selection;
- multiple installed voices;
- cache garbage collection;
- arbitrary text-to-speech API;
- packaging the voice/model inside Git or a distributable installer.
