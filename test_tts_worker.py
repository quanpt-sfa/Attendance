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


class TTSWindowsScriptContractTests(unittest.TestCase):
    def test_setup_script_pins_runtime_voice_revision_hash_and_smoke_test(self):
        text = (ROOT / "Setup-TTS.bat").read_text(encoding="utf-8").lower()
        self.assertIn("piper-tts==1.8.0", text)
        self.assertIn(".venv-tts\\scripts\\python.exe", text)
        self.assertIn("vi_vn-vais1000-medium.onnx", text)
        self.assertIn("vi_vn-vais1000-medium.onnx.json", text)
        self.assertIn("resolve/%voice_revision%/vi/vi_vn/vais1000/medium", text)
        self.assertIn("voice_revision=v1.0.0", text)
        self.assertIn(
            "ec7c89e2c85f4d1edc24b6120c18aaf1bda614f06b511567eb9c7c0de15e2dab",
            text,
        )
        self.assertIn("get-filehash -algorithm sha256", text)
        self.assertIn("--smoke-test", text)

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
