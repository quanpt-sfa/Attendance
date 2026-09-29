from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

EXPECTED_VERSION = "3.8.3"
VOICE_ID = "Thùy Dung"
ENGINE_ID = "vieneu-v3-turbo"
BACKEND_ID = "onnx-fp32"


def build_manifest(hf_cache: Path) -> dict:
    """Build a diagnostic manifest after an offline smoke test has succeeded."""
    hf_cache = Path(hf_cache)
    installed = importlib.metadata.version("vieneu")
    if installed != EXPECTED_VERSION:
        raise RuntimeError(
            f"VieNeu package version mismatch: expected {EXPECTED_VERSION}, got {installed}"
        )

    artifacts = []
    if hf_cache.is_dir():
        for path in sorted((p for p in hf_cache.rglob("*") if p.is_file()), key=lambda p: p.as_posix()):
            try:
                size = path.stat().st_size
            except OSError:
                continue
            artifacts.append(
                {"path": path.relative_to(hf_cache).as_posix(), "size": int(size)}
            )
    if not artifacts:
        raise RuntimeError("Hugging Face cache is empty after offline verification")

    return {
        "voice": VOICE_ID,
        "engine": ENGINE_ID,
        "engine_version": EXPECTED_VERSION,
        "backend": BACKEND_ID,
        "offline_verified": True,
        "setup_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "artifacts": artifacts,
    }


def write_manifest(hf_cache: Path, output: Path) -> Path:
    """Atomically publish the setup manifest."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = build_manifest(Path(hf_cache))
    temp = output.with_name(f"{output.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temp, output)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
    return output


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Write Attendance VieNeu offline setup manifest")
    parser.add_argument("--hf-cache", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        output = write_manifest(Path(args.hf_cache), Path(args.output))
    except Exception as exc:
        print(f"Cannot write VieNeu setup manifest: {exc}")
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
