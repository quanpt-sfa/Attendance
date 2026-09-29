from __future__ import annotations

import json
from pathlib import Path

EXPECTED_IDENTITY = {
    "voice": "Thùy Dung",
    "engine": "vieneu-v3-turbo",
    "engine_version": "3.8.3",
    "backend": "onnx-fp32",
}


def load_manifest(path: Path) -> dict | None:
    """Load a setup manifest without importing the TTS runtime."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def manifest_is_ready(manifest: dict | None) -> bool:
    """Return whether a manifest proves the approved VieNeu offline setup."""
    if not isinstance(manifest, dict):
        return False
    if manifest.get("offline_verified") is not True:
        return False
    return all(manifest.get(key) == value for key, value in EXPECTED_IDENTITY.items())
