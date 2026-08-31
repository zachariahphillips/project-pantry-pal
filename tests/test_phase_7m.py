"""
Phase 7M regression suite — automated SQLite backup helper.

The backup script wraps sqlite3.Connection.backup() so the runbook can call a
small tested helper instead of carrying a long inline Python heredoc.

Tier-1 dev loop:

    pytest tests/test_phase_7m.py -q
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from scripts.backup_sqlite import backup_sqlite, timestamped_backup_path


def test_timestamped_backup_path_uses_utc_suffix(tmp_path):
    now = datetime(2026, 8, 31, 15, 45, 12, tzinfo=timezone.utc)

    backup_path = timestamped_backup_path(tmp_path, now=now)

    assert backup_path == tmp_path / "pantrypal-20260831T154512Z.sqlite3"


def test_backup_sqlite_copies_source_database(tmp_path):
    source = tmp_path / "source.sqlite3"
    dest = tmp_path / "nested" / "backup.sqlite3"
    with sqlite3.connect(source) as con:
        con.execute("CREATE TABLE pantry_items (name TEXT NOT NULL)")
        con.execute("INSERT INTO pantry_items (name) VALUES (?)", ("Milk",))

    backup_path = backup_sqlite(source, dest)

    assert backup_path == dest
    with sqlite3.connect(dest) as con:
        rows = con.execute("SELECT name FROM pantry_items").fetchall()
    assert rows == [("Milk",)]
