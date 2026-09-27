"""Isolated Piper worker for Attendance offline Vietnamese TTS.

On Windows, the worker prefers the official native Piper executable so Vietnamese
text bypasses the Python ``espeakbridge`` path that can emit invalid Unicode
surrogates. Python Piper remains available as a fallback for non-Windows/testing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata
import wave
from pathlib import Path
from typing import Callable, TextIO

DEFAULT_SMOKE_TEXT = (
    "Nguyễn Thị THÚY QUỲNH, HUỲNH QUỐC PHƯỚC, VÕ TRỌNG NGHĨA, ĐẶNG HOÀNG YẾN."
)


def prepare_spoken_name(text: str) -> str:
    """Normalize a student name for Vietnamese eSpeak/Piper pronunciation.

    eSpeak may interpret an uppercase token inside an otherwise mixed-case name
    as an acronym (for example ``THU`` -> ``tê hát u``). Student names do not
    need acronym semantics, so the synthesis-only representation is lowercased.
    Display/database text is left untouched by this worker.
    """
    normalized = unicodedata.normalize("NFC", str(text or ""))
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.lower()


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
    """Lazily load one Python Piper voice and synthesize WAV files."""

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
        spoken_text = prepare_spoken_name(text)
        if not spoken_text:
            raise ValueError("Synthesis text is empty after normalization")
        voice = self._load_voice()

        wav_file = wave.open(str(output), "wb")
        try:
            voice.synthesize_wav(spoken_text, wav_file)
        except Exception:
            # Piper sets the WAV format only after the first audio chunk. If
            # phonemization/model inference fails first, wave.close() can mask
            # the real exception with '# channels not specified'.
            try:
                wav_file.close()
            except Exception:
                pass
            try:
                output.unlink(missing_ok=True)
            except OSError:
                pass
            raise
        else:
            wav_file.close()


class NativePiperSynthesizer:
    """Keep one native Piper process alive and feed it JSONL synthesis jobs."""

    def __init__(
        self,
        executable: Path,
        model_path: Path,
        config_path: Path,
        process_factory=subprocess.Popen,
    ):
        self.executable = Path(executable)
        self.model_path = Path(model_path)
        self.config_path = Path(config_path)
        self._process_factory = process_factory
        self._process = None

    def _start_process(self):
        if self._process is not None and self._process.poll() is None:
            return self._process

        # Real runtime validates files here. Tests inject a fake process factory.
        if self._process_factory is subprocess.Popen:
            if not self.executable.is_file():
                raise FileNotFoundError(f"Native Piper executable not found: {self.executable}")
            if not self.model_path.is_file():
                raise FileNotFoundError(f"Piper model not found: {self.model_path}")
            if not self.config_path.is_file():
                raise FileNotFoundError(f"Piper config not found: {self.config_path}")

        command = [
            str(self.executable),
            "--model",
            str(self.model_path),
            "--config",
            str(self.config_path),
            "--json-input",
            "--quiet",
        ]
        kwargs = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": None,
            "text": True,
            "encoding": "utf-8",
            "bufsize": 1,
            "cwd": str(self.executable.parent),
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

        self._process = self._process_factory(command, **kwargs)
        return self._process

    def close(self) -> None:
        process = self._process
        self._process = None
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
                process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
            except (AttributeError, OSError):
                pass

    def __call__(self, text: str, output: Path) -> None:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        spoken_text = prepare_spoken_name(text)
        if not spoken_text:
            raise ValueError("Synthesis text is empty after normalization")

        process = self._start_process()
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("Native Piper process has no active protocol pipes")

        request = {
            "text": spoken_text,
            "output_file": str(output),
        }
        try:
            process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError, UnicodeError) as exc:
            self.close()
            raise RuntimeError(f"Native Piper input failed: {exc}") from exc

        ack = process.stdout.readline()
        if not ack:
            return_code = process.poll()
            self.close()
            raise RuntimeError(f"Native Piper exited before producing audio (code={return_code})")

        acknowledged = Path(ack.strip())
        if os.path.normcase(os.path.abspath(str(acknowledged))) != os.path.normcase(
            os.path.abspath(str(output))
        ):
            raise RuntimeError(
                f"Native Piper acknowledged unexpected output path: {acknowledged}"
            )
        if not output.is_file():
            raise RuntimeError("Native Piper acknowledged output but WAV file is missing")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Attendance isolated Piper TTS worker")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--serve", action="store_true", help="Serve NDJSON requests on stdin/stdout")
    mode.add_argument("--smoke-test", metavar="OUTPUT_WAV", help="Synthesize Vietnamese student names")
    parser.add_argument("--model", required=True, help="Path to Piper .onnx model")
    parser.add_argument("--config", required=True, help="Path to matching .onnx.json config")
    parser.add_argument(
        "--native-piper",
        help="Path to native Piper executable. Preferred on Windows to avoid Python espeakbridge.",
    )
    return parser


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    if args.native_piper:
        synthesizer = NativePiperSynthesizer(
            Path(args.native_piper), Path(args.model), Path(args.config)
        )
    else:
        synthesizer = PiperSynthesizer(Path(args.model), Path(args.config))

    try:
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
    finally:
        close = getattr(synthesizer, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    raise SystemExit(main())
