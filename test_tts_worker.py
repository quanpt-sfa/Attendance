import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import tts_worker


ROOT = Path(__file__).resolve().parent


class TTSWorkerProtocolTests(unittest.TestCase):
    def test_valid_synthesis_request_preserves_id_and_calls_synthesizer(self):
        calls = []

        def synthesize(text, output):
            calls.append((text, Path(output)))

        request = {
            "id": "req-1",
            "action": "synthesize",
            "text": "Nguyễn Văn An",
            "output": "out.wav",
        }
        response = tts_worker.handle_request(request, synthesize)

        self.assertEqual(response, {"id": "req-1", "ok": True})
        self.assertEqual(calls, [("Nguyễn Văn An", Path("out.wav"))])

    def test_invalid_action_returns_protocol_error_without_synthesis(self):
        calls = []
        response = tts_worker.handle_request(
            {"id": "req-2", "action": "delete", "text": "A", "output": "x.wav"},
            lambda *args: calls.append(args),
        )
        self.assertEqual(response["id"], "req-2")
        self.assertFalse(response["ok"])
        self.assertIn("action", response["error"].lower())
        self.assertEqual(calls, [])

    def test_synthesis_exception_is_returned_as_protocol_error(self):
        def fail(_text, _output):
            raise RuntimeError("model failure")

        response = tts_worker.handle_request(
            {"id": "req-3", "action": "synthesize", "text": "A", "output": "x.wav"},
            fail,
        )
        self.assertEqual(response["id"], "req-3")
        self.assertFalse(response["ok"])
        self.assertIn("model failure", response["error"])

    def test_serve_writes_only_json_protocol_to_stdout(self):
        request = json.dumps(
            {"id": "req-4", "action": "synthesize", "text": "A", "output": "x.wav"}
        )
        stdin = io.StringIO(request + "\nnot-json\n")
        stdout = io.StringIO()
        stderr = io.StringIO()

        tts_worker.serve_streams(
            stdin,
            stdout,
            stderr,
            lambda _text, _output: None,
        )

        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual(lines[0], {"id": "req-4", "ok": True})
        self.assertFalse(lines[1]["ok"])
        self.assertNotIn("not-json", stdout.getvalue())
        self.assertIn("not-json", stderr.getvalue())

    def test_spoken_name_lowercases_uppercase_tokens_before_espeak(self):
        self.assertEqual(
            tts_worker.prepare_spoken_name("Nguyễn Thị THU"),
            "nguyễn thị thu",
        )
        self.assertEqual(
            tts_worker.prepare_spoken_name("  HUỲNH   QUỐC PHƯỚC  "),
            "huỳnh quốc phước",
        )

    def test_spoken_text_preserves_sentence_and_clause_punctuation(self):
        self.assertEqual(
            tts_worker.prepare_spoken_name(
                "HUỲNH QUỐC PHƯỚC, đã điểm danh thành công. Mời sinh viên tiếp theo!"
            ),
            "huỳnh quốc phước, đã điểm danh thành công. mời sinh viên tiếp theo!",
        )

    def test_smoke_sample_exercises_vietnamese_names_with_diacritics_and_uppercase(self):
        sample = tts_worker.DEFAULT_SMOKE_TEXT
        for fragment in (
            "Nguyễn Thị THÚY QUỲNH",
            "HUỲNH QUỐC PHƯỚC",
            "VÕ TRỌNG NGHĨA",
            "ĐẶNG HOÀNG YẾN",
        ):
            self.assertIn(fragment, sample)


class PiperSynthesizerTests(unittest.TestCase):
    def test_load_voice_uses_exact_model_and_config_paths(self):
        calls = []

        class FakePiperVoice:
            @staticmethod
            def load(model_path, config_path=None):
                calls.append((model_path, config_path))
                return object()

        fake_module = types.SimpleNamespace(PiperVoice=FakePiperVoice)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = root / "voice.onnx"
            config = root / "custom.json"
            model.write_bytes(b"model")
            config.write_text("{}", encoding="utf-8")
            synth = tts_worker.PiperSynthesizer(model, config)
            with mock.patch.dict(sys.modules, {"piper": fake_module}):
                voice = synth._load_voice()

        self.assertIsNotNone(voice)
        self.assertEqual(calls, [(str(model), str(config))])

    def test_real_synthesis_error_is_not_masked_by_wave_close(self):
        class BrokenVoice:
            def synthesize_wav(self, _text, _wav_file):
                raise RuntimeError("phonemizer exploded")

        synthesizer = tts_worker.PiperSynthesizer(Path("voice.onnx"), Path("voice.onnx.json"))
        synthesizer._voice = BrokenVoice()

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "broken.wav"
            with self.assertRaisesRegex(RuntimeError, "phonemizer exploded"):
                synthesizer("HUỲNH QUỐC PHƯỚC", output)
            self.assertFalse(output.exists())

    def test_whole_text_is_delegated_to_piper_frontend_with_punctuation_intact(self):
        calls = []

        class SentenceAwareVoice:
            def synthesize_wav(self, text, wav_file):
                calls.append(text)
                wav_file.setframerate(22050)
                wav_file.setsampwidth(2)
                wav_file.setnchannels(1)
                wav_file.writeframes(b"\x00\x00")

        synthesizer = tts_worker.PiperSynthesizer(Path("voice.onnx"), Path("voice.onnx.json"))
        synthesizer._voice = SentenceAwareVoice()

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "sentence.wav"
            synthesizer(
                "HUỲNH QUỐC PHƯỚC đã điểm danh thành công. Mời sinh viên tiếp theo.",
                output,
            )

        self.assertEqual(
            calls,
            ["huỳnh quốc phước đã điểm danh thành công. mời sinh viên tiếp theo."],
        )


class TTSWindowsScriptContractTests(unittest.TestCase):
    def test_setup_script_pins_piper_1_8_python_runtime_voice_and_smoke_test(self):
        text = (ROOT / "Setup-TTS.bat").read_text(encoding="utf-8").lower()
        self.assertIn(".venv-tts\\scripts\\python.exe", text)
        self.assertIn('piper-tts==1.8.0', text)
        self.assertIn('pip install', text)
        self.assertNotIn("piper_windows_amd64.zip", text)
        self.assertNotIn("2023.11.14-2", text)
        self.assertNotIn("--native-piper", text)
        self.assertNotIn("tts\\runtime\\piper\\piper.exe", text)
        self.assertIn('set "voice_id=calmwoman3688"', text)
        self.assertIn('set "model_path=%voice_dir%\\%voice_id%.onnx"', text)
        self.assertIn('set "config_path=%voice_dir%\\%voice_id%.onnx.json"', text)
        self.assertIn("huggingface.co/sannht/vi_voice/resolve/%voice_revision%/tts-model", text)
        self.assertIn("voice_revision=62e57b18157ed213b3863a7a8a35b14d3404554b", text)
        self.assertIn(
            "8db60d8afc50dc0921fd3a1b0b942813f44cc3744dbe2534617f2b8726096e7e",
            text,
        )
        self.assertIn(
            "971f57f8d504223fee5b40d664f503cf769baf7db21f7d2ae0554a75d07de2f8",
            text,
        )
        self.assertGreaterEqual(text.count("get-filehash -algorithm sha256"), 2)
        self.assertIn("--smoke-test", text)
        self.assertNotIn("vi_vn-vais1000-medium", text)

    def test_check_script_is_read_only(self):
        text = (ROOT / "Check-TTS.bat").read_text(encoding="utf-8").lower()
        self.assertIn("tts_service.get_status", text)
        self.assertIn("piper:", text)
        self.assertIn("voice:", text)
        self.assertIn("backend:", text)
        self.assertIn("cache:", text)
        for forbidden in (
            "pip install",
            "invoke-webrequest",
            "curl ",
            "bitsadmin",
            "start-bitstransfer",
        ):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
