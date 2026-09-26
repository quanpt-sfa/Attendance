import io
import json
import tempfile
import unittest
from pathlib import Path

import tts_worker


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


if __name__ == "__main__":
    unittest.main()
