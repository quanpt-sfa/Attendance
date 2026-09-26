"""TTS HTTP extension for the canonical Attendance server launcher."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import tts_service


def _send_json_error(handler, code: str, status: int) -> None:
    handler.send_json({"error": code}, status)


def _load_student_name(db_file, student_id: str, class_id: str):
    with sqlite3.connect(db_file) as conn:
        row = conn.execute(
            "SELECT full_name FROM students WHERE student_id = ? AND class_id = ?",
            (student_id, class_id),
        ).fetchone()
    return None if row is None else (row[0] or "")


def _send_wav(handler, wav_path: Path) -> None:
    data = Path(wav_path).read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", "audio/wav")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Cache-Control", "public, max-age=31536000, immutable")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(data)


def handle_tts_get(handler, raw_path: str, db_file) -> bool:
    """Handle a TTS GET route; return False when the path is not a TTS route."""
    parsed = urlparse(raw_path)
    path = parsed.path
    params = parse_qs(parsed.query)

    if path == "/api/tts/status":
        handler.send_json(tts_service.get_status())
        return True

    prefix = "/api/tts/student/"
    if not path.startswith(prefix):
        return False

    student_id = unquote(path[len(prefix):])
    class_id = params.get("class_id", [""])[0]
    if not student_id or not class_id:
        _send_json_error(handler, "missing_student_or_class", 400)
        return True

    name = _load_student_name(db_file, student_id, class_id)
    if name is None:
        _send_json_error(handler, "student_not_found", 404)
        return True
    if not tts_service.normalize_text(name):
        _send_json_error(handler, "student_name_empty", 422)
        return True

    try:
        wav_path = tts_service.ensure_audio(name)
    except tts_service.TTSUnavailableError:
        _send_json_error(handler, "tts_unavailable", 503)
        return True
    except (tts_service.TTSSynthesisError, OSError):
        _send_json_error(handler, "tts_synthesis_failed", 503)
        return True

    try:
        _send_wav(handler, wav_path)
    except OSError:
        _send_json_error(handler, "tts_synthesis_failed", 503)
    return True
