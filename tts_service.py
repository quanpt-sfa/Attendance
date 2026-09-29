"""Offline Vietnamese TTS cache/service boundary for Attendance.

The main Attendance process does not import VieNeu. Synthesis runs in the
isolated ``.venv-tts`` worker after one-time offline asset setup.
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

from tts_vieneu_assets import CODEC_DIR as DEFAULT_CODEC_DIR
from tts_vieneu_assets import ONNX_DIR as DEFAULT_ONNX_DIR
from tts_vieneu_assets import assets_ready
from tts_vieneu_manifest import load_manifest, manifest_is_ready

PROJECT_DIR = Path(__file__).resolve().parent
TTS_VENV = PROJECT_DIR / ".venv-tts"
TTS_RUNTIME_ROOT = PROJECT_DIR / "tts" / "runtime" / "vieneu"
HF_HOME = TTS_RUNTIME_ROOT / "hf"
HF_HUB_CACHE = HF_HOME / "hub"
VIENEU_ONNX_DIR = DEFAULT_ONNX_DIR
VIENEU_CODEC_DIR = DEFAULT_CODEC_DIR
SETUP_MANIFEST = TTS_RUNTIME_ROOT / "setup.json"
CACHE_DIR = PROJECT_DIR / "tts_cache"
WORKER_SCRIPT = PROJECT_DIR / "tts_worker.py"

VOICE_ID = "Thùy Dung"
TTS_ENGINE = "vieneu-v3-turbo"
TTS_ENGINE_VERSION = "3.8.3"
TTS_BACKEND = "onnx-fp32"
CACHE_FORMAT_VERSION = 6
WORKER_STARTUP_TIMEOUT_SECONDS = 90.0
WORKER_REQUEST_TIMEOUT_SECONDS = 45.0

_tts_lock = threading.RLock()
_worker_process = None
_worker_queue = None
_worker_reader = None


class TTSUnavailableError(RuntimeError):
    """Local TTS runtime or offline assets are unavailable."""


class TTSSynthesisError(RuntimeError):
    """Local TTS synthesis failed."""


def normalize_text(text: str) -> str:
    value = unicodedata.normalize("NFC", str(text or ""))
    return re.sub(r"\s+", " ", value).strip()


def cache_key(text: str) -> str:
    normalized = normalize_text(text)
    payload = "\n".join(
        (
            str(CACHE_FORMAT_VERSION),
            VOICE_ID,
            TTS_ENGINE,
            TTS_ENGINE_VERSION,
            TTS_BACKEND,
            normalized,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_path(text: str) -> Path:
    key = cache_key(text)
    return CACHE_DIR / key[:2] / f"{key}.wav"


def _worker_python() -> Path:
    if os.name == "nt":
        return TTS_VENV / "Scripts" / "python.exe"
    return TTS_VENV / "bin" / "python"


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


def _vieneu_distribution_present() -> bool:
    names = {
        f"vieneu-{TTS_ENGINE_VERSION}.dist-info",
        f"vieneu_{TTS_ENGINE_VERSION}.dist-info",
    }
    windows_site = TTS_VENV / "Lib" / "site-packages"
    for name in names:
        if (windows_site / name).is_dir():
            return True
    lib_root = TTS_VENV / "lib"
    if lib_root.is_dir():
        for site in lib_root.glob("python*/site-packages"):
            for name in names:
                if (site / name).is_dir():
                    return True
    return False


def _hf_cache_has_files() -> bool:
    """Diagnostic only; materialized assets, not Hub cache, gate readiness."""
    try:
        return HF_HUB_CACHE.is_dir() and any(
            path.is_file() for path in HF_HUB_CACHE.rglob("*")
        )
    except OSError:
        return False


def _materialized_assets_present() -> bool:
    return assets_ready(onnx_dir=VIENEU_ONNX_DIR, codec_dir=VIENEU_CODEC_DIR)


def _runtime_components() -> dict:
    python_runtime_present = _worker_python().is_file()
    package_present = _vieneu_distribution_present()
    manifest = load_manifest(SETUP_MANIFEST)
    manifest_ready = manifest_is_ready(manifest)
    materialized_assets_present = _materialized_assets_present()
    hf_cache_present = _hf_cache_has_files()
    offline_assets_present = bool(manifest_ready and materialized_assets_present)
    runtime_present = bool(
        python_runtime_present and package_present and offline_assets_present
    )
    return {
        "python_runtime_present": python_runtime_present,
        "package_present": package_present,
        "manifest_ready": manifest_ready,
        "materialized_assets_present": materialized_assets_present,
        "hf_cache_present": hf_cache_present,
        "offline_assets_present": offline_assets_present,
        "runtime_present": runtime_present,
    }


def get_status() -> dict:
    components = _runtime_components()
    try:
        cache_files = sum(
            1 for path in CACHE_DIR.rglob("*.wav") if _is_valid_wav(path)
        )
    except OSError:
        cache_files = 0
    available = bool(components["runtime_present"] and WORKER_SCRIPT.is_file())
    return {
        "available": available,
        "voice": VOICE_ID,
        "engine": TTS_ENGINE,
        "engine_version": TTS_ENGINE_VERSION,
        "backend": TTS_BACKEND,
        "runtime_present": bool(components["runtime_present"]),
        "python_runtime_present": bool(components["python_runtime_present"]),
        "package_present": bool(components["package_present"]),
        "offline_assets_present": bool(components["offline_assets_present"]),
        "materialized_assets_present": bool(components["materialized_assets_present"]),
        "manifest_ready": bool(components["manifest_ready"]),
        "hf_cache_present": bool(components["hf_cache_present"]),
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
    except (OSError, ValueError):
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


def _validate_ready_line(line: str | None) -> dict:
    if line is None:
        raise TTSUnavailableError("Offline TTS worker exited during startup")
    try:
        ready = json.loads(line)
    except (TypeError, json.JSONDecodeError) as exc:
        raise TTSUnavailableError(
            "Offline TTS worker returned malformed readiness data"
        ) from exc
    if not isinstance(ready, dict) or ready.get("type") != "ready":
        raise TTSUnavailableError("Offline TTS worker returned invalid readiness data")
    if not ready.get("ok"):
        raise TTSUnavailableError(
            ready.get("error") or "Offline TTS worker failed to initialize"
        )
    expected = {"voice": VOICE_ID, "engine": TTS_ENGINE, "backend": TTS_BACKEND}
    if any(ready.get(key) != value for key, value in expected.items()):
        raise TTSUnavailableError("Offline TTS worker readiness identity mismatch")
    return ready


def _start_worker_locked():
    global _worker_process, _worker_queue, _worker_reader
    if _worker_process is not None and _worker_process.poll() is None:
        return _worker_process

    components = _runtime_components()
    if not components.get("runtime_present") or not WORKER_SCRIPT.is_file():
        raise TTSUnavailableError(
            "Offline TTS is not installed. Run Setup-TTS.bat once while online."
        )

    command = [str(_worker_python()), str(WORKER_SCRIPT), "--serve"]
    worker_env = os.environ.copy()
    worker_env["PYTHONIOENCODING"] = "utf-8:strict"
    worker_env["HF_HUB_OFFLINE"] = "1"
    worker_env["HF_HOME"] = str(HF_HOME)
    worker_env["HF_HUB_CACHE"] = str(HF_HUB_CACHE)

    result_queue = queue.Queue()
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            bufsize=1,
            cwd=str(PROJECT_DIR),
            env=worker_env,
        )
    except OSError as exc:
        raise TTSUnavailableError(f"Cannot start offline TTS worker: {exc}") from exc

    reader = threading.Thread(
        target=_reader_loop,
        args=(process, result_queue),
        name="attendance-tts-worker-reader",
        daemon=True,
    )
    _worker_process = process
    _worker_queue = result_queue
    _worker_reader = reader
    reader.start()

    try:
        line = result_queue.get(timeout=WORKER_STARTUP_TIMEOUT_SECONDS)
    except queue.Empty as exc:
        _stop_worker_locked()
        raise TTSUnavailableError("Offline TTS worker startup timed out") from exc

    try:
        _validate_ready_line(line)
    except TTSUnavailableError:
        _stop_worker_locked()
        raise
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
    except (BrokenPipeError, OSError, UnicodeError, ValueError) as exc:
        raise TTSSynthesisError(f"Offline TTS worker pipe failed: {exc}") from exc

    try:
        line = _worker_queue.get(timeout=WORKER_REQUEST_TIMEOUT_SECONDS)
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
                raise TTSSynthesisError(
                    "Offline TTS worker produced an invalid WAV file"
                )
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


def precache_students(students: list[dict]) -> dict:
    unique = []
    seen = set()
    for student in students or []:
        record = student or {}
        name = normalize_text(
            record.get("full_name") or record.get("fullName") or ""
        )
        if not name or name in seen:
            continue
        seen.add(name)
        unique.append(name)
    result = {"total": len(unique), "generated": 0, "cached": 0, "failed": 0}
    for name in unique:
        if get_cached_audio(name) is not None:
            result["cached"] += 1
            continue
        try:
            ensure_audio(name)
            result["generated"] += 1
        except (TTSUnavailableError, TTSSynthesisError, ValueError):
            result["failed"] += 1
    return result


atexit.register(shutdown_worker)
