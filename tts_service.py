"""Offline Vietnamese TTS cache/service boundary for Attendance.

The main Attendance process never imports Piper. Synthesis is delegated to
``tts_worker.py`` running under the isolated ``.venv-tts`` interpreter.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import queue
import re
import subprocess
import threading
import unicodedata
import uuid
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
TTS_VENV = PROJECT_DIR / ".venv-tts"
VOICE_DIR = PROJECT_DIR / "tts" / "voices"
CACHE_DIR = PROJECT_DIR / "tts_cache"
WORKER_SCRIPT = PROJECT_DIR / "tts_worker.py"

VOICE_ID = "vi_VN-vais1000-medium"
VOICE_REVISION = "piper-voices-v1.0.0"
CACHE_FORMAT_VERSION = 1
WORKER_TIMEOUT_SECONDS = 20.0

VOICE_MODEL_NAME = f"{VOICE_ID}.onnx"
VOICE_CONFIG_NAME = f"{VOICE_ID}.onnx.json"

_tts_lock = threading.RLock()
_worker_process = None
_worker_queue = None
_worker_reader = None


class TTSUnavailableError(RuntimeError):
    """Local TTS runtime or voice is unavailable."""


class TTSSynthesisError(RuntimeError):
    """Local TTS synthesis failed."""


def normalize_text(text: str) -> str:
    """Normalize text for deterministic synthesis/cache identity."""
    value = unicodedata.normalize("NFC", str(text or ""))
    return re.sub(r"\s+", " ", value).strip()


def cache_key(text: str) -> str:
    """Return content-addressed cache key for normalized text and voice."""
    normalized = normalize_text(text)
    payload = (
        f"{CACHE_FORMAT_VERSION}\n"
        f"{VOICE_ID}\n"
        f"{VOICE_REVISION}\n"
        f"{normalized}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_path(text: str) -> Path:
    key = cache_key(text)
    return CACHE_DIR / key[:2] / f"{key}.wav"


def _worker_python() -> Path:
    if os.name == "nt":
        return TTS_VENV / "Scripts" / "python.exe"
    return TTS_VENV / "bin" / "python"


def _voice_model() -> Path:
    return VOICE_DIR / VOICE_MODEL_NAME


def _voice_config() -> Path:
    return VOICE_DIR / VOICE_CONFIG_NAME


def _is_valid_wav(path: Path) -> bool:
    try:
        if not path.is_file() or path.stat().st_size < 12:
            return False
        with path.open("rb") as handle:
            header = handle.read(12)
        return header[:4] == b"RIFF" and header[8:12] == b"WAVE"
    except OSError:
        return False


def get_cached_audio(text: str) -> Path | None:
    normalized = normalize_text(text)
    if not normalized:
        return None
    path = _cache_path(normalized)
    return path if _is_valid_wav(path) else None


def _runtime_state() -> tuple[bool, bool]:
    runtime_present = _worker_python().is_file()
    model_present = _voice_model().is_file() and _voice_config().is_file()
    return runtime_present, model_present


def get_status() -> dict:
    runtime_present, model_present = _runtime_state()
    try:
        cache_files = sum(1 for path in CACHE_DIR.rglob("*.wav") if _is_valid_wav(path))
    except OSError:
        cache_files = 0
    return {
        "available": bool(runtime_present and model_present and WORKER_SCRIPT.is_file()),
        "voice": VOICE_ID,
        "voice_revision": VOICE_REVISION,
        "runtime_present": runtime_present,
        "model_present": model_present,
        "cache_files": cache_files,
    }


def _reader_loop(process, result_queue):
    try:
        for line in process.stdout:
            result_queue.put(line)
    finally:
        result_queue.put(None)


def _stop_worker_locked() -> None:
    global _worker_process, _worker_queue, _worker_reader
    process = _worker_process
    _worker_process = None
    _worker_queue = None
    _worker_reader = None
    if process is None:
        return
    try:
        if process.stdin:
            process.stdin.close()
    except OSError:
        pass
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
    except OSError:
        pass


def shutdown_worker() -> None:
    with _tts_lock:
        _stop_worker_locked()


def _start_worker_locked():
    global _worker_process, _worker_queue, _worker_reader

    if _worker_process is not None and _worker_process.poll() is None:
        return _worker_process

    runtime_present, model_present = _runtime_state()
    if not runtime_present or not model_present or not WORKER_SCRIPT.is_file():
        raise TTSUnavailableError(
            "Offline TTS is not installed. Run Setup-TTS.bat once while online."
        )

    result_queue = queue.Queue()
    try:
        process = subprocess.Popen(
            [
                str(_worker_python()),
                str(WORKER_SCRIPT),
                "--serve",
                "--model",
                str(_voice_model()),
                "--config",
                str(_voice_config()),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            bufsize=1,
            cwd=str(PROJECT_DIR),
        )
    except OSError as exc:
        raise TTSUnavailableError(f"Cannot start offline TTS worker: {exc}") from exc

    reader = threading.Thread(
        target=_reader_loop,
        args=(process, result_queue),
        name="attendance-tts-worker-reader",
        daemon=True,
    )
    reader.start()
    _worker_process = process
    _worker_queue = result_queue
    _worker_reader = reader
    return process


def _request_worker_locked(text: str, output_path: Path) -> None:
    process = _start_worker_locked()
    if process.stdin is None or _worker_queue is None:
        raise TTSSynthesisError("Offline TTS worker has no active protocol pipes")

    request_id = uuid.uuid4().hex
    request = {
        "id": request_id,
        "action": "synthesize",
        "text": text,
        "output": str(output_path),
    }
    try:
        process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        process.stdin.flush()
    except (BrokenPipeError, OSError) as exc:
        raise TTSSynthesisError(f"Offline TTS worker pipe failed: {exc}") from exc

    try:
        line = _worker_queue.get(timeout=WORKER_TIMEOUT_SECONDS)
    except queue.Empty as exc:
        raise TTSSynthesisError("Offline TTS worker timed out") from exc

    if line is None:
        raise TTSSynthesisError("Offline TTS worker exited unexpectedly")

    try:
        response = json.loads(line)
    except json.JSONDecodeError as exc:
        raise TTSSynthesisError("Offline TTS worker returned malformed JSON") from exc

    if response.get("id") != request_id:
        raise TTSSynthesisError("Offline TTS worker response ID mismatch")
    if not response.get("ok"):
        raise TTSSynthesisError(response.get("error") or "Offline TTS synthesis failed")


def _synthesize_to_path(text: str, output_path: Path) -> None:
    """Ask the isolated worker to synthesize one WAV, retrying one worker crash."""
    last_error = None
    for attempt in range(2):
        try:
            _request_worker_locked(text, output_path)
            return
        except TTSUnavailableError:
            raise
        except TTSSynthesisError as exc:
            last_error = exc
            _stop_worker_locked()
            if attempt == 0:
                continue
    raise last_error or TTSSynthesisError("Offline TTS synthesis failed")


def ensure_audio(text: str) -> Path:
    """Return a valid cached WAV, synthesizing and atomically publishing if needed."""
    normalized = normalize_text(text)
    if not normalized:
        raise ValueError("TTS text is empty")

    cached = get_cached_audio(normalized)
    if cached is not None:
        return cached

    with _tts_lock:
        cached = get_cached_audio(normalized)
        if cached is not None:
            return cached

        final_path = _cache_path(normalized)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = final_path.parent / f".{final_path.name}.{uuid.uuid4().hex}.tmp.wav"
        try:
            _synthesize_to_path(normalized, temp_path)
            if not _is_valid_wav(temp_path):
                raise TTSSynthesisError("Offline TTS worker produced an invalid WAV file")
            os.replace(temp_path, final_path)
            return final_path
        except TTSUnavailableError:
            raise
        except TTSSynthesisError:
            raise
        except Exception as exc:
            raise TTSSynthesisError(str(exc)) from exc
        finally:
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except OSError:
                pass


atexit.register(shutdown_worker)
