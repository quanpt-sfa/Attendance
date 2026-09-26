import sqlite3
import unittest

import db_schema


class SchemaVersionTests(unittest.TestCase):
    def make_conn(self):
        return sqlite3.connect(':memory:')

    def test_new_database_is_stamped_current_after_required_columns_exist(self):
        conn = self.make_conn()
        conn.executescript('''
            CREATE TABLE classes (class_id TEXT PRIMARY KEY, is_conference INTEGER DEFAULT 0);
            CREATE TABLE students (student_id TEXT, class_id TEXT, email TEXT, card_uid TEXT, card_registered_at TEXT, is_lecturer INTEGER DEFAULT 0);
            CREATE TABLE sessions (session_id INTEGER PRIMARY KEY);
            CREATE TABLE checkins (id INTEGER PRIMARY KEY, bonus_points INTEGER DEFAULT 0, bonus_reason TEXT);
            CREATE TABLE absences (id INTEGER PRIMARY KEY);
            CREATE TABLE logs (id INTEGER PRIMARY KEY);
        ''')
        version = db_schema.ensure_schema_version(conn)
        self.assertEqual(version, db_schema.SCHEMA_VERSION)
        self.assertEqual(conn.execute('PRAGMA user_version').fetchone()[0], db_schema.SCHEMA_VERSION)

    def test_legacy_database_gets_missing_columns_then_current_version(self):
        conn = self.make_conn()
        conn.executescript('''
            CREATE TABLE classes (class_id TEXT PRIMARY KEY);
            CREATE TABLE students (student_id TEXT, class_id TEXT);
            CREATE TABLE sessions (session_id INTEGER PRIMARY KEY);
            CREATE TABLE checkins (id INTEGER PRIMARY KEY);
            CREATE TABLE absences (id INTEGER PRIMARY KEY);
            CREATE TABLE logs (id INTEGER PRIMARY KEY);
        ''')
        version = db_schema.ensure_schema_version(conn)
        self.assertEqual(version, db_schema.SCHEMA_VERSION)
        class_cols = {r[1] for r in conn.execute('PRAGMA table_info(classes)')}
        student_cols = {r[1] for r in conn.execute('PRAGMA table_info(students)')}
        checkin_cols = {r[1] for r in conn.execute('PRAGMA table_info(checkins)')}
        self.assertIn('is_conference', class_cols)
        self.assertTrue({'email', 'card_uid', 'card_registered_at', 'is_lecturer'} <= student_cols)
        self.assertTrue({'bonus_points', 'bonus_reason'} <= checkin_cols)

    def test_future_database_version_is_rejected(self):
        conn = self.make_conn()
        conn.execute(f'PRAGMA user_version = {db_schema.SCHEMA_VERSION + 1}')
        with self.assertRaises(db_schema.SchemaVersionError):
            db_schema.ensure_schema_version(conn)


if __name__ == '__main__':
    unittest.main()
