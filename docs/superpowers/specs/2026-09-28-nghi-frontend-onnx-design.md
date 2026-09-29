# NGHI Frontend → Piper/ONNX Vietnamese TTS — Design

Date: 2026-09-28
Status: Design approved in chat; awaiting written-spec review

## 1. Goal

Replace the current stock-Piper linguistic frontend for `calmwoman3688` with the exact NGHI-TTS linguistic frontend used by the voice source, while preserving the existing Attendance HTTP API, cache behavior, database integration, Random Picker fallback behavior, and offline operation after one-time setup.

The production path must preserve NGHI sentence chunking, punctuation handling, Vietnamese tone markers, and exact ONNX phoneme-ID sequences. Stock Piper/eSpeak sentence detection must not be used for Vietnamese text in production.

## 2. Why this architecture is required

Real-runtime probes on the pinned Vietnamese sentence:

```text
Huỳnh Quốc Phước đã điểm danh thành công. Mời sinh viên tiếp theo.
```

showed that both `piper-tts==1.8.0` and model-declared `piper-tts==1.3.0` produce one phoneme sentence rather than two. They also omit tone markers present in the pinned NGHI frontend, including cases such as NGHI `zˈe-1ɲ` and `kˈo7ŋ` versus stock Piper `zˈe-ɲ` and `kˈoŋ`.

Therefore upgrading or downgrading stock Piper does not repair the root cause. The voice must receive the same linguistic representation used by NGHI-TTS.

The already-pinned NGHI-TTS commit is:

```text
46d160da32041f7e176607203b958069265df7da
```

The voice remains:

```text
voice_id: calmwoman3688
voice source: sannht/vi_voice
voice revision: 62e57b18157ed213b3863a7a8a35b14d3404554b
sample rate: 22050 Hz
```

## 3. Architecture

The production pipeline is:

```text
Attendance server
    │
    ▼
tts_service.py
    │ private NDJSON
    ▼
tts_worker.py  (.venv-tts Python)
    │
    ├── long-lived NGHI frontend sidecar (Node)
    │       text
    │        ▼
    │   processTextForTTS()
    │        ▼
    │   chunkText()
    │        ▼
    │   PiperTTS.textToPhonemes()
    │        ▼
    │   PiperTTS.phonemesToIds()
    │        ▼
    │   exact scalar phoneme IDs per chunk
    │
    └── Python Piper/ONNX inference
            phoneme_ids_to_audio(ids)
                 ▼
            audio chunk 1
            audio chunk 2
            ...
                 ▼
            sequential WAV frames
                 ▼
            existing content-addressed cache
                 ▼
        /api/tts/student/<student_id>
                 ▼
              Random Picker
```

No component inserts a synthetic pause, zero-valued PCM block, or application-level regex sentence split.

The Node sidecar owns linguistic preprocessing only. The Python worker owns model loading, ONNX inference, audio assembly, output validation, and sidecar lifecycle.

The Attendance server process still does not import Piper or NGHI dependencies.

## 4. Component boundaries

### 4.1 `tts_service.py`

`tts_service.py` keeps its current responsibilities:

- normalize cache identity text;
- determine cache path;
- validate runtime/model presence;
- start/restart the isolated Python worker;
- serialize worker requests;
- validate worker responses;
- atomically publish completed WAV files;
- expose status and precache functions.

It does not know how NGHI phonemization works.

The public Python service interface remains compatible:

```python
get_status() -> dict
normalize_text(text: str) -> str
cache_key(text: str) -> str
get_cached_audio(text: str) -> Path | None
ensure_audio(text: str) -> Path
precache_students(students: list[dict]) -> dict
shutdown_worker() -> None
```

`normalize_text()` continues to perform NFC normalization and whitespace collapse for deterministic cache identity. It preserves source case and Vietnamese diacritics.

### 4.2 `tts_worker.py`

The Python worker becomes an inference/orchestration worker rather than a text phonemizer.

It must:

1. preserve source case and punctuation, applying only NFC normalization and whitespace collapse before handing text to NGHI;
2. keep one NGHI frontend sidecar alive;
3. send the complete normalized text to the sidecar;
4. receive ordered NGHI chunks and scalar phoneme-ID arrays;
5. lazily load the pinned ONNX voice once;
6. call `PiperVoice.phoneme_ids_to_audio()` for each NGHI chunk;
7. write all returned PCM chunks to one WAV in the original NGHI chunk order;
8. add no silence between chunks;
9. delete partial output if any frontend or inference step fails;
10. restart a failed frontend sidecar at most once for the current request.

The old `prepare_spoken_name(...).lower()` workaround is not part of the new production path. Case/acronym interpretation belongs to the exact NGHI frontend. Database and display text remain untouched.

The worker must not call:

```text
PiperVoice.phonemize()
PiperVoice.synthesize()
PiperVoice.synthesize_wav()
```

for production Vietnamese synthesis.

### 4.3 `tts/nghi_frontend.mjs`

Add a small Attendance-owned Node adapter. It must not reimplement NGHI linguistic rules.

It imports the exact pinned NGHI modules from the local NGHI checkout:

```text
src/utils/text-cleaner.js
src/lib/piper-tts.js
```

and invokes only their public functions/classes needed for frontend processing:

```text
processTextForTTS()
chunkText()
PiperTTS.textToPhonemes()
PiperTTS.phonemesToIds()
```

The adapter also provides the same local-file fetch shim already proven by `tools/nghi_phoneme_audit.mjs`, so NGHI resources such as CSV/config assets are loaded from the pinned checkout rather than the network.

The sidecar stdout is reserved for NDJSON protocol responses. NGHI debug/warning output is redirected to stderr.

## 5. Frontend protocol

A request from Python to Node is:

```json
{
  "id": "request-id",
  "action": "frontend",
  "text": "Huỳnh Quốc Phước đã điểm danh thành công. Mời sinh viên tiếp theo."
}
```

A successful response is:

```json
{
  "id": "request-id",
  "ok": true,
  "processed_text": "...",
  "chunks": [
    {
      "text": "...",
      "phoneme_ids": [1, 0, 20, 0, 37, 0, 10, 0, 2]
    },
    {
      "text": "...",
      "phoneme_ids": [1, 0, 26, 0, 13, 0, 2]
    }
  ]
}
```

A failure response is:

```json
{
  "id": "request-id",
  "ok": false,
  "error": "message"
}
```

Requirements:

- request and response IDs must match;
- `chunks` must be a non-empty ordered array;
- every `phoneme_ids` value must be a scalar integer suitable for ONNX int64 input;
- nested config values such as `[10]` are converted using the same coercion as NGHI immediately before its ONNX tensor creation;
- malformed JSON, missing IDs, empty chunks, non-integer values, sidecar EOF, or timeout are synthesis failures;
- no HTTP/TCP listener is created.

## 6. Audio generation and assembly

For each frontend chunk, the Python worker calls the pinned model with the exact NGHI phoneme IDs.

The synthesis configuration must match NGHI defaults:

```text
speaker_id = 0
length_scale = 1.0
noise_scale = 0.667
noise_w_scale = 0.8
```

The worker writes one mono 16-bit PCM WAV at the voice-config sample rate. Each model output is appended directly after the prior model output.

There is deliberately no:

```text
--sentence-silence
450 ms zero PCM
post-synthesis silence insertion
regex-based sentence splitting
```

Any natural pause must come from NGHI chunking, punctuation/tone IDs, BOS/EOS handling, and model output.

## 7. Runtime installation

### 7.1 Python runtime

Continue using:

```text
.venv-tts/
```

Pin Python inference to:

```text
piper-tts==1.8.0
```

Piper is used only as the ONNX voice/inference wrapper. Its linguistic frontend is not used.

### 7.2 Node runtime

Production must not depend on a globally installed Node.js.

`Setup-TTS.bat` installs a portable x64 Node.js runtime under:

```text
tts/runtime/node/
```

Pin:

```text
Node.js v22.23.3
```

The downloaded Windows x64 ZIP is checksum-verified before extraction.

### 7.3 NGHI source/runtime

`Setup-TTS.bat` installs the NGHI source at the exact commit:

```text
tts/runtime/nghitts/
46d160da32041f7e176607203b958069265df7da
```

The setup process must verify the checkout/archive identity before reporting success.

Dependencies are installed locally inside that runtime using the pinned NGHI lockfile. The production sidecar uses the same `phonemizer-1.2.2.tgz` referenced by that commit.

After setup completes, the Node runtime, NGHI source, phonemizer assets, Python environment, model, and config are all local. Normal synthesis makes no network request.

## 8. Filesystem layout

Local-only artifacts:

```text
Attendance/
├── .venv-tts/
├── tts/
│   ├── runtime/
│   │   ├── node/
│   │   └── nghitts/
│   └── voices/
│       ├── calmwoman3688.onnx
│       └── calmwoman3688.onnx.json
└── tts_cache/
```

Git-tracked adapter code:

```text
Attendance/
├── tts_worker.py
├── tts_service.py
├── tts/
│   └── nghi_frontend.mjs
├── Setup-TTS.bat
├── Check-TTS.bat
└── tests/tooling
```

The NGHI repository, portable Node binary, model, Python environment, npm dependencies, and generated WAV files are never committed.

## 9. Cache identity and migration

The linguistic frontend materially changes model input, so cached WAV files from the stock-Piper path must never be reused.

Bump:

```text
CACHE_FORMAT_VERSION: 5 → 6
```

The existing SHA-256 cache-key formula remains unchanged otherwise.

No explicit cache deletion is required. Old version-5 WAV files become unreachable from version-6 keys and may remain on disk until a future cleanup feature.

## 10. HTTP and browser compatibility

No HTTP route changes are required.

Keep:

```text
GET /api/tts/status
GET /api/tts/student/<student_id>?class_id=<class_id>
```

`server_tts.py` continues to call `tts_service.ensure_audio()` and return `audio/wav` or stable `503` errors.

`random-picker-speech.js` continues to request the student endpoint and falls back once to browser `speechSynthesis` if local audio fails.

No NGHI, Node, Piper, phoneme, or ONNX concepts are exposed to the browser API.

## 11. Runtime status

`get_status()` remains read-only and must not start either worker.

It reports enough information to distinguish missing components:

```json
{
  "available": true,
  "voice": "calmwoman3688",
  "backend": "nghi-frontend+python-piper-onnx",
  "python_runtime_present": true,
  "node_runtime_present": true,
  "nghi_frontend_present": true,
  "model_present": true,
  "cache_files": 42
}
```

Compatibility fields already consumed by existing tests/UI remain available where required.

## 12. Failure handling

### Missing portable Node or NGHI runtime

- Attendance server still starts;
- status reports TTS unavailable;
- student TTS endpoint returns `503 tts_unavailable`;
- Random Picker falls back to browser speech.

### Frontend sidecar crashes

- Python worker discards the dead sidecar;
- it starts one replacement and retries the current frontend request once;
- a second failure aborts synthesis;
- no final cache WAV is published.

### NGHI returns malformed IDs

Treat as synthesis failure. Do not coerce arbitrary strings, floats, nested arrays, or missing values beyond the exact scalar conversion already established by the NGHI audit harness.

### ONNX inference fails for any chunk

Abort the entire utterance, remove the temporary WAV, and return failure. Do not publish a partial multi-chunk file.

### Worker crashes

The existing `tts_service.py` worker restart-once behavior remains in force above the frontend-sidecar retry layer.

## 13. Testing strategy

Implementation is TDD-first.

### 13.1 Pure Node frontend tests

Tests must prove:

1. NDJSON request IDs are preserved;
2. complete source-case text is sent to NGHI without an Attendance sentence splitter or lowercasing step;
3. Case 2 returns two NGHI chunks;
4. commas remain inside a chunk rather than becoming sentence boundaries;
5. `!` and `?` produce expected NGHI chunk boundaries;
6. output phoneme IDs are scalar integers;
7. frontend errors never write non-JSON data to stdout.

### 13.2 Golden NGHI parity tests

Use the fixed audit cases already present in `tools/tts_phoneme_audit.py`.

For each case, production frontend output must equal the pinned NGHI audit output for:

```text
processed_text
chunk count
chunk text
phoneme_ids, element by element
```

The parity input is the same NFC/whitespace-normalized source-case text in both production and audit paths.

Case 2 is a hard gate: production must return exactly two NGHI chunks before synthesis can be considered correct.

### 13.3 Python worker tests

Tests must prove:

1. Python never calls Piper text phonemization/synthesis APIs;
2. each received NGHI chunk is sent independently to `phoneme_ids_to_audio()`;
3. chunk ordering is preserved;
4. no application-generated silence is inserted between chunks;
5. WAV format is valid and uses the model sample rate;
6. partial files are removed after frontend or inference failure;
7. sidecar restart is bounded to one retry;
8. uppercase Vietnamese input reaches NGHI with case preserved, while database/display text remains untouched.

### 13.4 Service/integration tests

Existing cache, endpoint, precache, startup, and browser fallback tests remain green.

Add tests for:

- cache format version 6;
- status requiring Python + Node + NGHI + model;
- worker command receives exact local frontend/runtime paths;
- Attendance imports and starts when TTS runtime is absent.

### 13.5 Real-runtime CI/probe

A dedicated verification step installs the pinned NGHI frontend and asserts the known two-sentence Vietnamese text produces two chunks and the same phoneme IDs as the golden audit path.

Stock Piper sentence grouping is not an acceptance test because stock Piper phonemization is intentionally bypassed.

### 13.6 Windows acceptance

After setup on the real Windows Attendance machine:

```text
Huỳnh Quốc Phước đã điểm danh thành công. Mời sinh viên tiếp theo.
```

must:

- synthesize successfully offline;
- contain two NGHI frontend chunks in diagnostic mode;
- play as one WAV;
- exhibit a perceptible sentence boundary without inserted silence;
- preserve correct Vietnamese pronunciation for the previously failing tone-marked words.

Perceptual acceptance is separate from automated structural verification.

## 14. Acceptance criteria

The migration is complete only when all are true:

- `main` no longer uses native Piper 2023 for production Vietnamese synthesis;
- production never uses stock Piper phonemization for `calmwoman3688`;
- production frontend chunk text and phoneme IDs equal pinned NGHI output;
- source case is preserved until NGHI applies its own text rules;
- Case 2 produces exactly two NGHI chunks;
- Python performs model inference from those IDs only;
- no synthetic inter-sentence silence is added;
- HTTP API and Random Picker behavior remain backward-compatible;
- cache version is bumped so old stock-Piper audio is not reused;
- setup installs all required runtimes locally and synthesis works without Internet afterward;
- automated Python and JavaScript regression suites pass;
- real-runtime NGHI parity verification passes;
- real Windows listening test passes before the migration is considered user-accepted.

## 15. Explicit non-goals

This change does not:

- create a general arbitrary-text public TTS endpoint;
- rewrite NGHI text normalization or phonemization in Python;
- add SSML;
- inject manual pauses or silence samples;
- change student/database schema;
- change Random Picker selection logic;
- change the selected `calmwoman3688` model;
- bundle model weights or third-party runtimes into Git;
- refactor unrelated Attendance server code.

## 16. Migration sequence constraint

Implementation must be performed on `feat/nghi-frontend-onnx` with RED → GREEN tests. `main` remains on the currently accepted native-Piper implementation until the new branch passes all automated gates.

The failed stock-Piper 1.3/1.8 experiment is not a migration base and must not be merged or cherry-picked wholesale. Only independently validated tests or diagnostic knowledge may be reused.