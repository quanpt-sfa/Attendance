import json
import threading
import time
import unittest
from pathlib import Path

import tts_worker


class _FakeStdin:
    def write(self, value):
        return len(value)

    def flush(self):
        pass

    def close(self):
        pass


class _BlockingStdout:
    def __init__(self, response):
        self.response = response
        self.release = threading.Event()

    def readline(self):
        self.release.wait(0.2)
        return self.response


class _FakeProcess:
    def __init__(self, response):
        self.stdin = _FakeStdin()
        self.stdout = _BlockingStdout(response)
        self._returncode = None

    def poll(self):
        return self._returncode

    def terminate(self):
        self._returncode = 0
        self.stdout.release.set()

    def kill(self):
        self._returncode = -9
        self.stdout.release.set()

    def wait(self, timeout=None):
        return self._returncode or 0


class NghiFrontendTimeoutTests(unittest.TestCase):
    def test_frontend_read_timeout_fails_closed_and_retries_only_once(self):
        self.assertTrue(
            hasattr(tts_worker, "FRONTEND_TIMEOUT_SECONDS"),
            "worker must define a bounded NGHI frontend response timeout",
        )
        old_timeout = tts_worker.FRONTEND_TIMEOUT_SECONDS
        tts_worker.FRONTEND_TIMEOUT_SECONDS = 0.01
        starts = []
        response = json.dumps(
            {
                "id": "fixed-id",
                "ok": True,
                "processed_text": "xin chào.",
                "chunks": [{"text": "xin chào.", "phoneme_ids": [1, 0, 2]}],
            }
        ) + "\n"

        def process_factory(command, **kwargs):
            starts.append((command, kwargs))
            return _FakeProcess(response)

        client = tts_worker.NghiFrontendClient(
            Path("node.exe"),
            Path("tts/nghi_frontend.mjs"),
            Path("tts/runtime/nghitts"),
            Path("tts/voices/calmwoman3688.onnx.json"),
            tts_worker.NGHI_COMMIT_DEFAULT,
            process_factory=process_factory,
        )
        client._new_request_id = lambda: "fixed-id"
        started = time.monotonic()
        try:
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                client.process("Xin chào.")
        finally:
            tts_worker.FRONTEND_TIMEOUT_SECONDS = old_timeout
            client.close()

        self.assertEqual(len(starts), 2)
        self.assertLess(time.monotonic() - started, 0.15)


if __name__ == "__main__":
    unittest.main()
