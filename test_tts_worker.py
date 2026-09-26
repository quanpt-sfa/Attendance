import io
import json
import unittest
from pathlib import Path

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

    def test_smoke_sample_exercises_vietnamese_names_with_diacritics_and_uppercase(self):
        sample = tts_worker.DEFAULT_SMOKE_TEXT
        for fragment in (
            "Nguyễn Thị THÚY QUỲNH",
            "HUỲNH QUỐC PHƯỚC",
            "VÕ TRỌNG NGHĨA",
            "ĐẶNG HOÀNG YẾN",
        ):
            self.assertIn(fragment, sample)


class TTSWindowsScriptContractTests(unittest.TestCase):
    def test_setup_script_pins_runtime_voice_revision_hashes_and_smoke_test(self):
        text = (ROOT / "Setup-TTS.bat").read_text(encoding="utf-8").lower()
        self.assertIn("piper-tts==1.8.0", text)
        self.assertIn(".venv-tts\\scripts\\python.exe", text)
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
