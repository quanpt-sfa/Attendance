"""Isolated Piper worker for Attendance offline Vietnamese TTS.

This module is importable without Piper installed. Piper is imported lazily only
when the real synthesizer is first asked to generate audio inside .venv-tts.
"""

from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path
from typing import Callable, TextIO

DEFAULT_SMOKE_TEXT = "Xin chào"


def handle_request(request: dict, synthesize: Callable[[str, Path], None]) -> dict:
    """Handle one worker protocol request and return a JSON-serializable response."""
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
    """Serve newline-delimited JSON requests until EOF.

    stdout is reserved exclusively for machine-readable protocol responses.
    Human-readable diagnostics are written to stderr.
    """
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


class PiperSynthesizer:
    """Lazily load one Piper voice and synthesize WAV files."""

    def __init__(self, model_path: Path, config_path: Path):
        self.model_path = Path(model_path)
        self.config_path = Path(config_path)
        self._voice = None

    def _load_voice(self):
        if self._voice is not None:
            return self._voice
        if not self.model_path.is_file():
            raise FileNotFoundError(f"Piper model not found: {self.model_path}")
        if not self.config_path.is_file():
            raise FileNotFoundError(f"Piper config not found: {self.config_path}")

        from piper import PiperVoice

        self._voice = PiperVoice.load(str(self.model_path))
        return self._voice

    def __call__(self, text: str, output: Path) -> None:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        voice = self._load_voice()
        with wave.open(str(output), "wb") as wav_file:
            voice.synthesize_wav(text, wav_file)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Attendance isolated Piper TTS worker")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--serve", action="store_true", help="Serve NDJSON requests on stdin/stdout")
    mode.add_argument("--smoke-test", metavar="OUTPUT_WAV", help="Synthesize one short Vietnamese sample")
    parser.add_argument("--model", required=True, help="Path to Piper .onnx model")
    parser.add_argument("--config", required=True, help="Path to matching .onnx.json config")
    return parser


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    synthesizer = PiperSynthesizer(Path(args.model), Path(args.config))

    if args.serve:
        serve_streams(sys.stdin, sys.stdout, sys.stderr, synthesizer)
        return 0

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
