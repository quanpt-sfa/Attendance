import contextlib
import io
import json
import sys
import tempfile
import types
import unittest
import wave
from pathlib import Path
from unittest import mock

import tts_worker


class FakeEngine:
    def __init__(self, voices=None):
        self.voices = voices or [("⭐ Thùy Dung — Southern female", "Thùy Dung")]
        self.infer_calls = []

    def list_preset_voices(self):
        print("sdk-list-chatter")
        return self.voices

    def infer(self, text, voice):
        print("sdk-infer-chatter")
        self.infer_calls.append((text, voice))
        return [0.0, 0.25, -0.25, 0.0]


class VieneuSynthesizerTests(unittest.TestCase):
    def _factory(self, engine, calls):
        def factory(**kwargs):
            print("sdk-init-chatter")
            calls.append(kwargs)
            return engine
        return factory

    def _fake_soundfile(self, calls):
        module = types.SimpleNamespace()
        def write(path, audio, samplerate, subtype):
            calls.append((str(path), list(audio), samplerate, subtype))
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(samplerate)
                wf.writeframes(b"\x00\x00" * len(audio))
        module.write = write
        return module

    def test_constructs_engine_once_and_reuses_exact_southern_voice(self):
        calls = []
        engine = FakeEngine()
        synth = tts_worker.VieneuSynthesizer(factory=self._factory(engine, calls), stderr=io.StringIO())
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, {"soundfile": self._fake_soundfile([])}):
            synth("Huỳnh Quốc Phước.", Path(tmp) / "a.wav")
            synth("Mời sinh viên tiếp theo.", Path(tmp) / "b.wav")
        self.assertEqual(calls, [{
            "mode": "v3turbo",
            "backend": "onnx",
            "precision": "fp32",
            "backbone_repo": str(tts_worker.VIENEU_MODEL_ROOT),
            "onnx_dir": str(tts_worker.VIENEU_ONNX_DIR),
            "codec_dir": str(tts_worker.VIENEU_CODEC_DIR),
        }])
        self.assertEqual(engine.infer_calls, [
            ("Huỳnh Quốc Phước.", "Thùy Dung"),
            ("Mời sinh viên tiếp theo.", "Thùy Dung"),
        ])
        self.assertEqual(tts_worker.DEFAULT_VOICE, "Thùy Dung")

    def test_requires_exact_voice_id_not_decorative_label(self):
        engine = FakeEngine(voices=[("⭐ Thùy Dung — Southern female", "voice-17")])
        synth = tts_worker.VieneuSynthesizer(factory=lambda **_kwargs: engine, stderr=io.StringIO())
        with self.assertRaisesRegex(RuntimeError, "Thùy Dung"):
            synth.initialize()

    def test_preserves_text_writes_48khz_pcm16_and_redirects_sdk_stdout(self):
        factory_calls = []
        sf_calls = []
        engine = FakeEngine()
        sdk_stderr = io.StringIO()
        protocol_stdout = io.StringIO()
        synth = tts_worker.VieneuSynthesizer(factory=self._factory(engine, factory_calls), stderr=sdk_stderr)
        text = "HUỲNH Quốc Phước đã điểm danh thành công. Mời sinh viên tiếp theo."
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(sys.modules, {"soundfile": self._fake_soundfile(sf_calls)}), contextlib.redirect_stdout(protocol_stdout):
            output = Path(tmp) / "out.wav"
            synth(text, output)
            with wave.open(str(output), "rb") as wf:
                self.assertEqual(wf.getnchannels(), 1)
                self.assertEqual(wf.getframerate(), 48000)
                self.assertEqual(wf.getsampwidth(), 2)
        self.assertEqual(engine.infer_calls, [(text, "Thùy Dung")])
        self.assertEqual(sf_calls[0][2:], (48000, "PCM_16"))
        self.assertEqual(protocol_stdout.getvalue(), "")
        self.assertIn("sdk-init-chatter", sdk_stderr.getvalue())
        self.assertIn("sdk-list-chatter", sdk_stderr.getvalue())
        self.assertIn("sdk-infer-chatter", sdk_stderr.getvalue())

    def test_partial_output_is_removed_after_save_failure(self):
        engine = FakeEngine()
        def broken_writer(path, _audio, _samplerate, _subtype):
            Path(path).write_bytes(b"partial")
            raise RuntimeError("disk failed")
        synth = tts_worker.VieneuSynthesizer(factory=lambda **_kwargs: engine, writer=broken_writer, stderr=io.StringIO())
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "partial.wav"
            with self.assertRaisesRegex(RuntimeError, "disk failed"):
                synth("Xin chào.", output)
            self.assertFalse(output.exists())


class WorkerReadinessTests(unittest.TestCase):
    def test_serve_ready_streams_emits_one_ready_event_then_request_responses(self):
        class Synth:
            def __init__(self): self.initialized = 0
            def initialize(self): self.initialized += 1
            def __call__(self, _text, output): Path(output).write_bytes(b"RIFF\x00\x00\x00\x00WAVE")
        synth = Synth()
        stdin = io.StringIO(json.dumps({"id":"r1","action":"synthesize","text":"Xin chào","output":"out.wav"}) + "\n")
        stdout, stderr = io.StringIO(), io.StringIO()
        tts_worker.serve_ready_streams(stdin, stdout, stderr, synth)
        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual(synth.initialized, 1)
        self.assertEqual(lines[0], {"type":"ready","ok":True,"voice":"Thùy Dung","engine":"vieneu-v3-turbo","backend":"onnx-fp32"})
        self.assertEqual(lines[1], {"id":"r1","ok":True})
        self.assertEqual(tts_worker.READY_EVENT_TYPE, "ready")

    def test_readiness_failure_emits_failure_and_does_not_consume_requests(self):
        class BrokenSynth:
            def initialize(self): raise RuntimeError("model unavailable")
        stdin = io.StringIO("should-not-be-read\n")
        stdout, stderr = io.StringIO(), io.StringIO()
        ok = tts_worker.serve_ready_streams(stdin, stdout, stderr, BrokenSynth())
        self.assertFalse(ok)
        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual(lines, [{"type":"ready","ok":False,"error":"model unavailable"}])


class ProtocolCompatibilityTests(unittest.TestCase):
    def test_request_protocol_remains_compatible(self):
        seen = []
        response = tts_worker.handle_request(
            {"id":"req-1","action":"synthesize","text":"Nguyễn Văn An","output":"out.wav"},
            lambda text, output: seen.append((text, Path(output))),
        )
        self.assertEqual(response, {"id":"req-1","ok":True})
        self.assertEqual(seen, [("Nguyễn Văn An", Path("out.wav"))])


if __name__ == "__main__":
    unittest.main()
