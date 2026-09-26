"""Offline Vietnamese TTS service primitives.

This module intentionally has no dependency on Piper. The Piper runtime lives
in an isolated virtual environment and is contacted through a subprocess in
later stages of the implementation.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
TTS_VENV = PROJECT_DIR / ".venv-tts"
VOICE_DIR = PROJECT_DIR / "tts" / "voices"
CACHE_DIR = PROJECT_DIR / "tts_cache"

VOICE_ID = "vi_VN-vais1000-medium"
VOICE_REVISION = "piper-voices-v1.0.0"
CACHE_FORMAT_VERSION = 1


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
