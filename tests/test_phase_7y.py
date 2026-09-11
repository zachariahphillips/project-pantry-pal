"""
Phase 7Y regression suite — backup reminders.

PythonAnywhere keeps PantryPal no-cost by making backups a manual operator
habit. 7Y adds a small script that makes that habit visible: run it from a
PythonAnywhere Bash console, get exit code 0 when the latest backup is recent,
or get a reminder with the exact backup command when backups are missing/stale.

Tier-1 dev loop:

    pytest tests/test_phase_7y.py -q
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.backup_reminder import (
    backup_command,
    backup_reminder_status,
    latest_backup,
    main,
)


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


def _touch(path: Path, modified: datetime) -> Path:
    path.write_text("backup")
    timestamp = modified.timestamp()
    os.utime(path, (timestamp, timestamp))
    return path


def test_latest_backup_uses_newest_matching_backup_file(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    _touch(backup_dir / "notes.txt", NOW)
    older = _touch(
        backup_dir / "pantrypal-20260901T120000Z.sqlite3",
        NOW - timedelta(days=10),
    )
    newer = _touch(
        backup_dir / "pantrypal-20260910T120000Z.sqlite3",
        NOW - timedelta(days=1),
    )

    assert latest_backup(backup_dir) == newer
    assert latest_backup(backup_dir) != older


def test_backup_reminder_status_is_ok_for_recent_backup(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    newest = _touch(
        backup_dir / "pantrypal-20260910T120000Z.sqlite3",
        NOW - timedelta(days=1),
    )

    status = backup_reminder_status(backup_dir, max_age_days=7, now=NOW)

    assert status.ok is True
    assert status.latest_backup == newest
    assert status.age_days == pytest.approx(1.0)
    assert "Backup reminder OK" in status.message


def test_backup_reminder_status_warns_when_no_backup_exists(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    status = backup_reminder_status(backup_dir, max_age_days=7, now=NOW)

    assert status.ok is False
    assert status.latest_backup is None
    assert "no pantrypal-*.sqlite3 files found" in status.message
    assert "python scripts/backup_sqlite.py" in status.message
    assert "--verify --keep 14" in status.message


def test_backup_reminder_status_warns_when_latest_backup_is_stale(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    stale = _touch(
        backup_dir / "pantrypal-20260901T120000Z.sqlite3",
        NOW - timedelta(days=10),
    )

    status = backup_reminder_status(backup_dir, max_age_days=7, now=NOW)

    assert status.ok is False
    assert status.latest_backup == stale
    assert status.age_days == pytest.approx(10.0)
    assert "10.0 days old" in status.message
    assert "limit: 7" in status.message


def test_backup_command_matches_pythonanywhere_runbook_paths():
    assert backup_command() == (
        "python scripts/backup_sqlite.py "
        "--source data/pantrypal.sqlite3 "
        "--dest-dir backups "
        "--verify "
        "--keep 14"
    )


def test_main_returns_nonzero_for_stale_or_invalid_threshold(tmp_path, capsys):
    assert main(["--backup-dir", str(tmp_path), "--max-age-days", "7"]) == 1
    out = capsys.readouterr().out
    assert "BACKUP REMINDER" in out

    assert main(["--backup-dir", str(tmp_path), "--max-age-days", "0"]) == 2
    err = capsys.readouterr().err
    assert "max_age_days must be at least 1" in err


def test_readme_documents_phase_7y_backup_reminder():
    readme = README.read_text()

    assert "PythonAnywhere backup reminder (Phase 7Y)" in readme
    assert "python scripts/backup_reminder.py" in readme
    assert "--max-age-days 7" in readme
    assert "Exit code 1" in readme
