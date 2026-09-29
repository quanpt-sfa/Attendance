"""Isolated Vietnamese TTS worker using the pinned NGHI linguistic frontend.

The Attendance server process never imports Piper or NGHI. This worker keeps a
long-lived Node sidecar for NGHI text processing and feeds the returned exact
phoneme IDs directly to Piper/ONNX inference. Stock Piper phonemization is not
used for production Vietnamese synthesis.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import struct
import subprocess
import sys
import threading
import uuid
import wave
from pathlib import Path
from typing import Callable, TextIO

DEFAULT_SMOKE_TEXT = (
    "Nguyễn Thị THÚY QUỲNH, HUỲNH QUỐC PHƯỚC đã điểm danh thành công. "
    "Mời sinh viên tiếp theo."
)
NGHI_COMMIT_DEFAULT = "46d160da32041f7e176607203b958069265df7da"
FRONTEND_TIMEOUT_SECONDS = 20.0
INTER_CHUNK_SILENCE_SECONDS = 0.45


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
    """Serve newline-delimited JSON requests until EOF."""
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


class NghiFrontendClient:
    """Long-lived private NDJSON client for the pinned NGHI Node sidecar."""

    def __init__(
        self,
        node_exe: Path,
        adapter_path: Path,
        nghi_root: Path,
        voice_config: Path,
        expected_commit: str,
        process_factory=subprocess.Popen,
    ):
        self.node_exe = Path(node_exe)
        self.adapter_path = Path(adapter_path)
        self.nghi_root = Path(nghi_root)
        self.voice_config = Path(voice_config)
        self.expected_commit = str(expected_commit)
        self._process_factory = process_factory
        self._process = None

    def _new_request_id(self) -> str:
        return uuid.uuid4().hex

    def _start_process(self):
        if self._process is not None and self._process.poll() is None:
            return self._process

        if self._process_factory is subprocess.Popen:
            for path, label in (
                (self.node_exe, "Node runtime"),
                (self.adapter_path, "NGHI adapter"),
                (self.nghi_root, "NGHI checkout"),
                (self.voice_config, "voice config"),
            ):
                if not path.exists():
                    raise FileNotFoundError(f"{label} not found: {path}")

        command = [
            str(self.node_exe),
            str(self.adapter_path),
            "--nghi-root",
            str(self.nghi_root),
            "--voice-config",
            str(self.voice_config),
            "--expected-commit",
            self.expected_commit,
        ]
        kwargs = {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": None,
            "text": True,
            "encoding": "utf-8",
            "bufsize": 1,
            "cwd": str(self.adapter_path.parent),
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
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        except (OSError, AttributeError):
            pass

    @staticmethod
    def _validate_response(response: dict, request_id: str) -> dict:
        if not isinstance(response, dict):
            raise RuntimeError("NGHI frontend returned a non-object response")
        if response.get("id") != request_id:
            raise RuntimeError("NGHI frontend response ID mismatch")
        if not response.get("ok"):
            raise RuntimeError(response.get("error") or "NGHI frontend failed")
        chunks = response.get("chunks")
        if not isinstance(chunks, list) or not chunks:
            raise ValueError("NGHI frontend returned empty chunks")
        validated = []
        for chunk in chunks:
            if not isinstance(chunk, dict) or not isinstance(chunk.get("text"), str):
                raise ValueError("NGHI frontend returned invalid chunk text")
            ids = chunk.get("phoneme_ids")
            if not isinstance(ids, list) or not ids:
                raise ValueError("NGHI frontend returned empty phoneme ids")
            if any(isinstance(value, bool) or not isinstance(value, int) for value in ids):
                raise ValueError("NGHI frontend phoneme ids must be scalar integers")
            validated.append({"text": chunk["text"], "phoneme_ids": list(ids)})
        return {
            "processed_text": str(response.get("processed_text") or ""),
            "chunks": validated,
        }

    @staticmethod
    def _readline_with_timeout(stream, timeout_seconds: float) -> str:
        """Read one protocol line without allowing a live sidecar to hang forever."""
        result_queue = queue.Queue(maxsize=1)

        def reader() -> None:
            try:
                result_queue.put((True, stream.readline()))
            except BaseException as exc:
                result_queue.put((False, exc))

        thread = threading.Thread(
            target=reader,
            name="attendance-nghi-frontend-reader",
            daemon=True,
        )
        thread.start()
        try:
            ok, value = result_queue.get(timeout=timeout_seconds)
        except queue.Empty as exc:
            raise RuntimeError("NGHI frontend response timed out") from exc
        if not ok:
            raise RuntimeError(f"NGHI frontend response read failed: {value}") from value
        return value

    def _request_once(self, text: str) -> dict:
        process = self._start_process()
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("NGHI frontend sidecar has no active protocol pipes")
        request_id = self._new_request_id()
        request = {"id": request_id, "action": "frontend", "text": text}
        try:
            process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError, UnicodeError) as exc:
            raise RuntimeError(f"NGHI frontend input failed: {exc}") from exc
        line = self._readline_with_timeout(process.stdout, FRONTEND_TIMEOUT_SECONDS)
        if not line:
            raise RuntimeError("NGHI frontend sidecar exited before response")
        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError("NGHI frontend returned malformed JSON response") from exc
        return self._validate_response(response, request_id)

    def process(self, text: str) -> dict:
        last_error = None
        for attempt in range(2):
            try:
                return self._request_once(text)
            except (RuntimeError, ValueError, OSError, UnicodeError) as exc:
                last_error = exc
                self.close()
                if attempt == 0:
                    continue
        raise last_error or RuntimeError("NGHI frontend failed")


class NghiOnnxSynthesizer:
    """Synthesize exact NGHI phoneme IDs and preserve NGHI chunk boundaries."""

    def __init__(self, model_path: Path, config_path: Path, frontend: NghiFrontendClient):
        self.model_path = Path(model_path)
        self.config_path = Path(config_path)
        self.frontend = frontend
        self._voice = None

    def _load_voice(self):
        if self._voice is not None:
            return self._voice
        if not self.model_path.is_file():
            raise FileNotFoundError(f"Piper model not found: {self.model_path}")
        if not self.config_path.is_file():
            raise FileNotFoundError(f"Piper config not found: {self.config_path}")
        from piper import PiperVoice
        self._voice = PiperVoice.load(str(self.model_path), config_path=str(self.config_path))
        return self._voice

    def _make_synthesis_config(self):
        from piper import SynthesisConfig
        return SynthesisConfig(
            speaker_id=0,
            length_scale=1.0,
            noise_scale=0.667,
            noise_w_scale=0.8,
            normalize_audio=False,
        )

    @staticmethod
    def _audio_to_pcm16(audio) -> bytes:
        frames = bytearray()
        for raw in audio:
            sample = max(-1.0, min(1.0, float(raw)))
            value = int(sample * (32768 if sample < 0 else 32767))
            value = max(-32768, min(32767, value))
            frames.extend(struct.pack("<h", value))
        return bytes(frames)

    def __call__(self, text: str, output: Path) -> None:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            frontend_result = self.frontend.process(text)
            chunks = frontend_result["chunks"]
            voice = self._load_voice()
            syn_config = self._make_synthesis_config()
            sample_rate = int(voice.config.sample_rate)
            silence_frames = max(0, round(sample_rate * INTER_CHUNK_SILENCE_SECONDS))
            inter_chunk_silence = b"\x00\x00" * silence_frames
            with wave.open(str(output), "wb") as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(sample_rate)
                for index, chunk in enumerate(chunks):
                    audio = voice.phoneme_ids_to_audio(
                        chunk["phoneme_ids"],
                        syn_config=syn_config,
                        include_alignments=False,
                    )
                    if isinstance(audio, tuple):
                        audio = audio[0]
                    wav_file.writeframesraw(self._audio_to_pcm16(audio))
                    if index + 1 < len(chunks) and inter_chunk_silence:
                        wav_file.writeframesraw(inter_chunk_silence)
        except Exception:
            try:
                output.unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def close(self) -> None:
        self.frontend.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Attendance isolated NGHI/Piper TTS worker")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--serve", action="store_true", help="Serve NDJSON requests on stdin/stdout")
    mode.add_argument("--smoke-test", metavar="OUTPUT_WAV", help="Synthesize Vietnamese smoke text")
    parser.add_argument("--model", required=True, help="Path to Piper .onnx model")
    parser.add_argument("--config", required=True, help="Path to matching .onnx.json config")
    parser.add_argument("--node", required=True, help="Path to portable Node executable")
    parser.add_argument("--nghi-adapter", required=True, help="Path to Attendance NGHI frontend adapter")
    parser.add_argument("--nghi-root", required=True, help="Path to pinned NGHI checkout")
    parser.add_argument("--nghi-commit", default=NGHI_COMMIT_DEFAULT, help="Expected NGHI git commit")
    return parser


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    frontend = NghiFrontendClient(
        Path(args.node),
        Path(args.nghi_adapter),
        Path(args.nghi_root),
        Path(args.config),
        args.nghi_commit,
    )
    synthesizer = NghiOnnxSynthesizer(Path(args.model), Path(args.config), frontend)
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
        synthesizer.close()


if __name__ == "__main__":
    raise SystemExit(main())
