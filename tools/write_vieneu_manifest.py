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


def build_manifest(asset_root: Path) -> dict:
    """Build a diagnostic manifest after an offline smoke test has succeeded."""
    asset_root = Path(asset_root)
    installed = importlib.metadata.version("vieneu")
    if installed != EXPECTED_VERSION:
        raise RuntimeError(
            f"VieNeu package version mismatch: expected {EXPECTED_VERSION}, got {installed}"
        )

    artifacts = []
    if asset_root.is_dir():
        for path in sorted((p for p in asset_root.rglob("*") if p.is_file()), key=lambda p: p.as_posix()):
            if ".cache" in path.parts:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            artifacts.append(
                {"path": path.relative_to(asset_root).as_posix(), "size": int(size)}
            )
    if not artifacts:
        raise RuntimeError("VieNeu materialized asset directory is empty after offline verification")

    return {
        "voice": VOICE_ID,
        "engine": ENGINE_ID,
        "engine_version": EXPECTED_VERSION,
        "backend": BACKEND_ID,
        "offline_verified": True,
        "setup_timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "artifacts": artifacts,
    }


def write_manifest(asset_root: Path, output: Path) -> Path:
    """Atomically publish the setup manifest."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = build_manifest(Path(asset_root))
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
    parser.add_argument("--asset-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        output = write_manifest(Path(args.asset_root), Path(args.output))
    except Exception as exc:
        print(f"Cannot write VieNeu setup manifest: {exc}")
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
