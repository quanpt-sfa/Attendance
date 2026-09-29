"""Isolated VieNeu worker for Attendance offline Vietnamese TTS."""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path
from typing import Callable, TextIO

from tts_vieneu_assets import CODEC_DIR, MODEL_ROOT, ONNX_DIR

READY_EVENT_TYPE = "ready"
DEFAULT_VOICE = "Thùy Dung"
ENGINE_ID = "vieneu-v3-turbo"
BACKEND_ID = "onnx-fp32"
SAMPLE_RATE = 48_000
VIENEU_MODEL_ROOT = MODEL_ROOT
VIENEU_ONNX_DIR = ONNX_DIR
VIENEU_CODEC_DIR = CODEC_DIR
DEFAULT_SMOKE_TEXT = (
    "Huỳnh Quốc Phước đã điểm danh thành công. Mời sinh viên tiếp theo."
)


def handle_request(request: dict, synthesize: Callable[[str, Path], None]) -> dict:
    request_id = request.get("id") if isinstance(request, dict) else None
    try:
        if not isinstance(request, dict):
            raise ValueError("Request must be a JSON object")
        if request.get("action") != "synthesize":
            raise ValueError("Unsupported action")
        text = str(request.get("text") or "").strip()
        output_raw = request.get("output")
        if not text:
            raise ValueError("Synthesis text is empty")
        if not output_raw:
            raise ValueError("Output path is required")
        output = Path(str(output_raw))
        synthesize(text, output)
        return {"id": request_id, "ok": True}
    except Exception as exc:
        return {"id": request_id, "ok": False, "error": str(exc)}


def serve_streams(
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    synthesize: Callable[[str, Path], None],
) -> None:
    for raw_line in stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON request: {line} ({exc})", file=stderr, flush=True)
            response = {"id": None, "ok": False, "error": "Invalid JSON request"}
        else:
            response = handle_request(request, synthesize)
            if not response.get("ok"):
                print(
                    f"TTS request failed [{response.get('id')}]: {response.get('error')}",
                    file=stderr,
                    flush=True,
                )
        stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        stdout.flush()


class VieneuSynthesizer:
    """Keep one VieNeu v3 Turbo ONNX engine hot for repeated requests."""

    def __init__(self, factory=None, writer=None, stderr: TextIO | None = None):
        self._factory = factory
        self._writer = writer
        self.stderr = stderr or sys.stderr
        self._engine = None

    def _resolve_factory(self):
        if self._factory is not None:
            return self._factory
        from vieneu import Vieneu
        return Vieneu

    def initialize(self):
        if self._engine is not None:
            return self._engine
        with contextlib.redirect_stdout(self.stderr):
            factory = self._resolve_factory()
            engine = factory(
                mode="v3turbo",
                backend="onnx",
                precision="fp32",
                backbone_repo=str(VIENEU_MODEL_ROOT),
                onnx_dir=str(VIENEU_ONNX_DIR),
                codec_dir=str(VIENEU_CODEC_DIR),
            )
            voices = engine.list_preset_voices()
        exact_ids = {
            str(item[1])
            for item in voices or []
            if isinstance(item, (tuple, list)) and len(item) >= 2
        }
        if DEFAULT_VOICE not in exact_ids:
            raise RuntimeError(f"VieNeu preset voice not found: {DEFAULT_VOICE}")
        self._engine = engine
        return engine

    def _write_audio(self, output: Path, audio) -> None:
        writer = self._writer
        if writer is None:
            import soundfile as sf
            writer = sf.write
        writer(str(output), audio, SAMPLE_RATE, "PCM_16")

    def __call__(self, text: str, output: Path) -> None:
        text = str(text or "").strip()
        if not text:
            raise ValueError("Synthesis text is empty")
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        engine = self.initialize()
        try:
            with contextlib.redirect_stdout(self.stderr):
                audio = engine.infer(text, voice=DEFAULT_VOICE)
            self._write_audio(output, audio)
        except Exception:
            try:
                output.unlink(missing_ok=True)
            except OSError:
                pass
            raise


def serve_ready_streams(
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    synthesizer,
) -> bool:
    try:
        synthesizer.initialize()
    except Exception as exc:
        stdout.write(
            json.dumps(
                {"type": READY_EVENT_TYPE, "ok": False, "error": str(exc)},
                ensure_ascii=False,
            )
            + "\n"
        )
        stdout.flush()
        print(f"VieNeu initialization failed: {exc}", file=stderr, flush=True)
        return False

    ready = {
        "type": READY_EVENT_TYPE,
        "ok": True,
        "voice": DEFAULT_VOICE,
        "engine": ENGINE_ID,
        "backend": BACKEND_ID,
    }
    stdout.write(json.dumps(ready, ensure_ascii=False) + "\n")
    stdout.flush()
    serve_streams(stdin, stdout, stderr, synthesizer)
    return True


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Attendance isolated VieNeu TTS worker")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--serve", action="store_true", help="Serve NDJSON requests on stdin/stdout")
    mode.add_argument("--smoke-test", metavar="OUTPUT_WAV", help="Synthesize one Vietnamese acceptance sentence")
    return parser


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    synthesizer = VieneuSynthesizer()
    if args.serve:
        return 0 if serve_ready_streams(sys.stdin, sys.stdout, sys.stderr, synthesizer) else 1

    output = Path(args.smoke_test)
    response = handle_request(
        {
            "id": "smoke-test",
            "action": "synthesize",
            "text": DEFAULT_SMOKE_TEXT,
            "output": str(output),
        },
        synthesizer,
    )
    if not response.get("ok"):
        print(response.get("error") or "TTS smoke test failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
