"""Canonical Attendance server launcher with database schema version checks."""

import os
import sqlite3
import sys

from db_schema import SCHEMA_VERSION, SchemaVersionError, ensure_schema_version, get_schema_version


def initialize_database_schema(db_file, init_func, log=print):
    """Run the legacy initializer, migrate/stamp the DB, and report its version."""
    if os.path.exists(db_file):
        with sqlite3.connect(db_file) as conn:
            existing_version = get_schema_version(conn)
        if existing_version > SCHEMA_VERSION:
            raise SchemaVersionError(
                f"Database schema v{existing_version} is newer than this application (v{SCHEMA_VERSION})."
            )

    init_func()

    with sqlite3.connect(db_file) as conn:
        version = ensure_schema_version(conn, log=log)

    log(f"[OK] Database schema: {version}/{SCHEMA_VERSION}")
    return version


def _parse_port(value):
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid port: {value}") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"Invalid port: {value}")
    return port


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    port = _parse_port(argv[0]) if argv else 8000

    import server

    original_init_database = server.init_database

    def versioned_init_database():
        return initialize_database_schema(
            server.DB_FILE,
            original_init_database,
            log=print,
        )

    server.init_database = versioned_init_database
    server.PORT = port
    server.run_server()


if __name__ == "__main__":
    try:
        main()
    except (SchemaVersionError, ValueError) as exc:
        print(f"[LOI] {exc}")
        raise SystemExit(1)
