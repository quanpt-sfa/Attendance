"""SQLite schema versioning for Attendance.

Versioning starts at v1 with the schema that existed when PRAGMA user_version
was introduced. Existing databases are reconciled idempotently before being
stamped v1; future schema changes must add a new numbered migration.
"""

SCHEMA_VERSION = 1


class SchemaVersionError(RuntimeError):
    """Raised when a database schema cannot be safely used by this code."""


REQUIRED_TABLES = {
    "classes": {
        "class_id": "TEXT",
        "credit_class_id": "TEXT",
        "class_name": "TEXT",
        "start_date": "TEXT",
        "num_sessions": "INTEGER DEFAULT 10",
        "session_interval": "INTEGER DEFAULT 7",
        "default_start_period": "INTEGER DEFAULT 1",
        "default_end_period": "INTEGER DEFAULT 3",
        "room": "TEXT",
        "is_conference": "INTEGER DEFAULT 0",
        "google_sheet_url": "TEXT",
        "created_at": "TEXT",
        "updated_at": "TEXT",
    },
    "students": {
        "student_id": "TEXT",
        "class_id": "TEXT",
        "last_name": "TEXT",
        "first_name": "TEXT",
        "full_name": "TEXT",
        "email": "TEXT",
        "birth_date": "TEXT",
        "gender": "TEXT",
        "photo_path": "TEXT",
        "card_uid": "TEXT",
        "card_registered_at": "TEXT",
        "is_lecturer": "INTEGER DEFAULT 0",
        "created_at": "TEXT",
    },
    "sessions": {
        "session_id": "INTEGER",
        "class_id": "TEXT",
        "session_number": "INTEGER",
        "session_date": "TEXT",
        "start_period": "INTEGER",
        "end_period": "INTEGER",
        "is_open": "INTEGER",
        "opened_at": "TEXT",
        "closed_at": "TEXT",
    },
    "checkins": {
        "id": "INTEGER",
        "session_id": "INTEGER",
        "student_id": "TEXT",
        "class_id": "TEXT",
        "check_type": "TEXT",
        "check_time": "TEXT",
        "bonus_points": "INTEGER DEFAULT 0",
        "bonus_reason": "TEXT",
    },
    "absences": {
        "id": "INTEGER",
        "session_id": "INTEGER",
        "student_id": "TEXT",
        "class_id": "TEXT",
        "reason": "TEXT",
        "created_at": "TEXT",
    },
    "logs": {
        "id": "INTEGER",
        "time": "TEXT",
        "session_id": "INTEGER",
        "class_id": "TEXT",
        "student_id": "TEXT",
        "check_type": "TEXT",
        "result": "TEXT",
        "note": "TEXT",
    },
}


def get_schema_version(conn):
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _table_exists(conn, table):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def _columns(conn, table):
    return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}


def _add_missing_columns(conn, table, columns):
    if not _table_exists(conn, table):
        raise SchemaVersionError(
            f"Missing required table '{table}'. Run the Attendance database initializer first."
        )

    existing = _columns(conn, table)
    added = []
    for name, definition in columns.items():
        if name not in existing:
            conn.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {definition}')
            added.append(f"{table}.{name}")
    return added


def _migration_1_reconcile_current_schema(conn):
    """Adopt pre-versioning databases into the current v1 baseline."""
    added = []
    for table, columns in REQUIRED_TABLES.items():
        added.extend(_add_missing_columns(conn, table, columns))
    return added


MIGRATIONS = {
    1: _migration_1_reconcile_current_schema,
}


def validate_schema(conn):
    missing = {}
    for table, columns in REQUIRED_TABLES.items():
        if not _table_exists(conn, table):
            missing[table] = ["<table missing>"]
            continue
        absent = sorted(set(columns) - _columns(conn, table))
        if absent:
            missing[table] = absent

    if missing:
        details = "; ".join(
            f"{table}: {', '.join(columns)}" for table, columns in missing.items()
        )
        raise SchemaVersionError(f"Database schema validation failed: {details}")
    return True


def ensure_schema_version(conn, log=None):
    """Upgrade an initialized Attendance DB to SCHEMA_VERSION and validate it."""
    version = get_schema_version(conn)
    if version > SCHEMA_VERSION:
        raise SchemaVersionError(
            f"Database schema v{version} is newer than this application (v{SCHEMA_VERSION})."
        )

    while version < SCHEMA_VERSION:
        target = version + 1
        migration = MIGRATIONS.get(target)
        if migration is None:
            raise SchemaVersionError(f"Missing migration for schema v{target}.")

        if log:
            log(f"[*] Migrating database schema {version} -> {target}...")
        try:
            added = migration(conn)
            conn.execute(f"PRAGMA user_version = {target}")
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        if log:
            for column in added:
                log(f"    + {column}")
        version = target

    validate_schema(conn)
    return version
