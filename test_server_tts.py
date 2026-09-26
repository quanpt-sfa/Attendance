import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import server_tts
import tts_service


FAKE_WAV = b"RIFF\x04\x00\x00\x00WAVE"


class FakeHandler:
    def __init__(self):
        self.status = None
        self.json = None
        self.headers_sent = []
        self.wfile = io.BytesIO()

    def send_json(self, data, status=200):
        self.status = status
        self.json = data

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.headers_sent.append((key, value))

    def end_headers(self):
        pass


class ServerTTSEndpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_file = self.root / "attendance.db"
        with sqlite3.connect(self.db_file) as conn:
            conn.execute(
                "CREATE TABLE students (student_id TEXT, class_id TEXT, full_name TEXT, "
                "PRIMARY KEY(student_id, class_id))"
            )
            conn.execute(
                "INSERT INTO students(student_id, class_id, full_name) VALUES (?, ?, ?)",
                ("SV 01", "L01", "Nguyễn Văn An"),
            )
            conn.execute(
                "INSERT INTO students(student_id, class_id, full_name) VALUES (?, ?, ?)",
                ("SV02", "L01", ""),
            )

    def tearDown(self):
        self.temp.cleanup()

    def test_status_endpoint_forwards_read_only_service_status(self):
        handler = FakeHandler()
        expected = {"available": False, "voice": "vi_VN-vais1000-medium"}
        with mock.patch.object(tts_service, "get_status", return_value=expected):
            handled = server_tts.handle_tts_get(handler, "/api/tts/status", self.db_file)
        self.assertTrue(handled)
        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.json, expected)

    def test_student_endpoint_returns_404_for_missing_student(self):
        handler = FakeHandler()
        handled = server_tts.handle_tts_get(
            handler,
            "/api/tts/student/NOPE?class_id=L01",
            self.db_file,
        )
        self.assertTrue(handled)
        self.assertEqual(handler.status, 404)

    def test_student_endpoint_returns_422_for_empty_name(self):
        handler = FakeHandler()
        server_tts.handle_tts_get(
            handler,
            "/api/tts/student/SV02?class_id=L01",
            self.db_file,
        )
        self.assertEqual(handler.status, 422)

    def test_student_endpoint_maps_unavailable_to_stable_503_code(self):
        handler = FakeHandler()
        with mock.patch.object(
            tts_service,
            "ensure_audio",
            side_effect=tts_service.TTSUnavailableError("not installed"),
        ):
            server_tts.handle_tts_get(
                handler,
                "/api/tts/student/SV%2001?class_id=L01",
                self.db_file,
            )
        self.assertEqual(handler.status, 503)
        self.assertEqual(handler.json, {"error": "tts_unavailable"})

    def test_student_endpoint_maps_synthesis_failure_to_stable_503_code(self):
        handler = FakeHandler()
        with mock.patch.object(
            tts_service,
            "ensure_audio",
            side_effect=tts_service.TTSSynthesisError("model failure"),
        ):
            server_tts.handle_tts_get(
                handler,
                "/api/tts/student/SV%2001?class_id=L01",
                self.db_file,
            )
        self.assertEqual(handler.status, 503)
        self.assertEqual(handler.json, {"error": "tts_synthesis_failed"})

    def test_student_endpoint_returns_exact_wav_and_cache_headers(self):
        handler = FakeHandler()
        wav = self.root / "cached.wav"
        wav.write_bytes(FAKE_WAV)
        with mock.patch.object(tts_service, "ensure_audio", return_value=wav) as ensure:
            server_tts.handle_tts_get(
                handler,
                "/api/tts/student/SV%2001?class_id=L01",
                self.db_file,
            )
        self.assertEqual(handler.status, 200)
        self.assertEqual(handler.wfile.getvalue(), FAKE_WAV)
        self.assertIn(("Content-Type", "audio/wav"), handler.headers_sent)
        self.assertIn(("Content-Length", str(len(FAKE_WAV))), handler.headers_sent)
        ensure.assert_called_once_with("Nguyễn Văn An")


if __name__ == "__main__":
    unittest.main()
