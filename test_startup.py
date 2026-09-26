import os
import sqlite3
import sys
import tempfile
import types
import unittest
from unittest import mock

import startup
from db_schema import SCHEMA_VERSION


class StartupSchemaTests(unittest.TestCase):
    def test_initialize_database_schema_runs_initializer_and_stamps_version(self):
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, 'attendance.db')
            calls = []

            def fake_init():
                calls.append('init')
                conn = sqlite3.connect(db_path)
                conn.executescript('''
                    CREATE TABLE classes (class_id TEXT PRIMARY KEY, class_name TEXT);
                    CREATE TABLE students (student_id TEXT, class_id TEXT);
                    CREATE TABLE sessions (session_id INTEGER PRIMARY KEY, class_id TEXT, session_number INTEGER, session_date TEXT, start_period INTEGER, end_period INTEGER, is_open INTEGER, opened_at TEXT, closed_at TEXT);
                    CREATE TABLE checkins (id INTEGER PRIMARY KEY, session_id INTEGER, student_id TEXT, class_id TEXT, check_type TEXT, check_time TEXT);
                    CREATE TABLE absences (id INTEGER PRIMARY KEY, session_id INTEGER, student_id TEXT, class_id TEXT, reason TEXT, created_at TEXT);
                    CREATE TABLE logs (id INTEGER PRIMARY KEY, time TEXT, session_id INTEGER, class_id TEXT, student_id TEXT, check_type TEXT, result TEXT, note TEXT);
                ''')
                conn.commit()
                conn.close()

            logs = []
            version = startup.initialize_database_schema(db_path, fake_init, logs.append)

            self.assertEqual(calls, ['init'])
            self.assertEqual(version, SCHEMA_VERSION)
            self.assertTrue(any('Database schema: 1/1' in line for line in logs))
            conn = sqlite3.connect(db_path)
            self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], SCHEMA_VERSION)
            conn.close()

    def test_main_installs_tts_extension_before_running_server(self):
        calls = []
        fake_server = types.SimpleNamespace(
            init_database=lambda: None,
            DB_FILE='unused.db',
            PORT=8000,
            run_server=lambda: calls.append('run'),
        )
        fake_tts = types.SimpleNamespace(install=lambda module: calls.append(('install', module)))

        with mock.patch.dict(sys.modules, {'server': fake_server, 'server_tts': fake_tts}):
            startup.main(['8080'])

        self.assertEqual(fake_server.PORT, 8080)
        self.assertEqual(calls[0], ('install', fake_server))
        self.assertEqual(calls[1], 'run')


if __name__ == '__main__':
    unittest.main()
