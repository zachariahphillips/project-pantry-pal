"""
Phase 7K regression suite — SQLite backup/restore runbook.

The production database is a Fly volume-backed SQLite file. Keep the docs
explicit about online backups, WAL sidecars, restore drills, and post-restore
smoke checks.

Tier-1 dev loop:

    pytest tests/test_phase_7k.py -q
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readme_documents_online_sqlite_backup_command():
    readme = (ROOT / "README.md").read_text()

    assert "### SQLite backup and restore" in readme
    assert "/data/pantrypal.sqlite3" in readme
    assert "/data/backups" in readme
    assert "python /app/scripts/backup_sqlite.py" in readme
    assert ".venv/bin/python scripts/backup_sqlite.py" in readme
    assert "fly ssh sftp" in readme


def test_readme_documents_restore_drill_and_wal_cleanup():
    readme = (ROOT / "README.md").read_text()

    assert "Before restoring production, do a local restore drill" in readme
    assert "pantrypal-restore-test.sqlite3" in readme
    assert "pantrypal-pre-restore" in readme
    assert "pantrypal.sqlite3-wal" in readme
    assert "pantrypal.sqlite3-shm" in readme
    assert "EXPECT_SECURE_COOKIES=1" in readme
