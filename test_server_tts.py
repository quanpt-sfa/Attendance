import io
import sqlite3
import tempfile
import types
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

    def send_response(self, status, message=None):
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


class ServerTTSPrecacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_file = Path(self.temp.name) / "attendance.db"
        with sqlite3.connect(self.db_file) as conn:
            conn.execute(
                "CREATE TABLE students (student_id TEXT, class_id TEXT, full_name TEXT, "
                "PRIMARY KEY(student_id, class_id))"
            )

    def tearDown(self):
        self.temp.cleanup()

    def make_server_module(self):
        db_file = self.db_file

        class Handler:
            def __init__(self):
                self.path = "/"
                self.status = None
                self.original_get_calls = 0

            def send_response(self, status, message=None):
                self.status = status

            def do_GET(self):
                self.original_get_calls += 1

            def create_student(self):
                with sqlite3.connect(db_file) as conn:
                    conn.execute(
                        "INSERT INTO students VALUES (?, ?, ?)",
                        ("S1", "C1", "Nguyễn Văn Một"),
                    )
                self.send_response(200)

            def import_students(self):
                with sqlite3.connect(db_file) as conn:
                    conn.execute(
                        "INSERT INTO students VALUES (?, ?, ?)",
                        ("S2", "C1", "Trần Thị Hai"),
                    )
                self.send_response(200)

            def update_student(self, student_id):
                with sqlite3.connect(db_file) as conn:
                    conn.execute(
                        "UPDATE students SET full_name = ? WHERE student_id = ?",
                        ("Nguyễn Văn Một Mới", student_id),
                    )
                self.send_response(200)

        return types.SimpleNamespace(AttendanceHandler=Handler, DB_FILE=str(db_file))

    def test_install_routes_tts_get_before_legacy_get(self):
        module = self.make_server_module()
        server_tts.install(module)
        handler = module.AttendanceHandler()

        with mock.patch.object(server_tts, "handle_tts_get", return_value=True) as routed:
            handler.path = "/api/tts/status"
            handler.do_GET()
        routed.assert_called_once_with(handler, "/api/tts/status", module.DB_FILE)
        self.assertEqual(handler.original_get_calls, 0)

        with mock.patch.object(server_tts, "handle_tts_get", return_value=False):
            handler.path = "/api/classes"
            handler.do_GET()
        self.assertEqual(handler.original_get_calls, 1)

    def test_successful_student_writes_schedule_after_committed_data_is_visible(self):
        module = self.make_server_module()
        snapshots = []

        def observe(db_file):
            with sqlite3.connect(db_file) as conn:
                snapshots.append(conn.execute("SELECT student_id, full_name FROM students ORDER BY student_id").fetchall())

        with mock.patch.object(server_tts, "schedule_tts_precache", side_effect=observe) as schedule:
            server_tts.install(module)
            handler = module.AttendanceHandler()
            handler.create_student()
            handler.import_students()
            handler.update_student("S1")

        self.assertEqual(schedule.call_count, 3)
        self.assertEqual(snapshots[0], [("S1", "Nguyễn Văn Một")])
        self.assertEqual(snapshots[1], [("S1", "Nguyễn Văn Một"), ("S2", "Trần Thị Hai")])
        self.assertEqual(snapshots[2][0], ("S1", "Nguyễn Văn Một Mới"))

    def test_failed_student_write_does_not_schedule_precache(self):
        module = self.make_server_module()

        def fail_create(self):
            self.send_response(500)

        module.AttendanceHandler.create_student = fail_create
        with mock.patch.object(server_tts, "schedule_tts_precache") as schedule:
            server_tts.install(module)
            module.AttendanceHandler().create_student()
        schedule.assert_not_called()

    def test_schedule_tts_precache_uses_daemon_thread_and_returns_without_running_inline(self):
        created = []

        class FakeThread:
            def __init__(self, target, args, name, daemon):
                self.target = target
                self.args = args
                self.name = name
                self.daemon = daemon
                self.started = False
                created.append(self)

            def start(self):
                self.started = True

        with mock.patch.object(server_tts.threading, "Thread", FakeThread):
            thread = server_tts.schedule_tts_precache(str(self.db_file))

        self.assertIs(thread, created[0])
        self.assertTrue(thread.daemon)
        self.assertTrue(thread.started)
        self.assertEqual(thread.args, (str(self.db_file),))


if __name__ == "__main__":
    unittest.main()
