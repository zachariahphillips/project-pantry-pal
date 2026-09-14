"""
Phase 7Z regression suite — post-backup download/check reminders.

Phase 7Y tells the operator when a backup is missing or stale. 7Z closes the
next gap: after a manual PythonAnywhere backup is created, the CLI should
immediately remind the operator to download it and run the local restore drill
before trusting it.

Tier-1 dev loop:

    pytest tests/test_phase_7z.py -q
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.backup_sqlite import (
    BASE64_BEGIN_MARKER,
    BASE64_END_MARKER,
    REQUIRED_BACKUP_TABLES,
    main,
    post_backup_reminder,
    restore_drill_command,
)


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"


def _make_pantrypal_db(path: Path) -> Path:
    with sqlite3.connect(path) as conn:
        for table in REQUIRED_BACKUP_TABLES:
            conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
        conn.commit()
    return path


def test_restore_drill_command_uses_downloaded_local_backup_path():
    backup = Path("/home/riah/project-pantry-pal/backups/pantrypal-latest.sqlite3")

    assert restore_drill_command(backup) == (
        ".venv/bin/python scripts/restore_drill.py "
        "backups/pantrypal-latest.sqlite3"
    )


def test_post_backup_reminder_points_to_download_and_restore_drill():
    reminder = post_backup_reminder(Path("backups/pantrypal-latest.sqlite3"))

    assert "Post-backup reminder" in reminder
    assert "Download pantrypal-latest.sqlite3" in reminder
    assert "PythonAnywhere's Files tab" in reminder
    assert ".venv/bin/python scripts/restore_drill.py" in reminder
    assert "Only trust this backup after the restore drill exits 0" in reminder


def test_backup_cli_prints_post_backup_reminder_to_stderr(tmp_path, capfd):
    source = _make_pantrypal_db(tmp_path / "source.sqlite3")
    dest = tmp_path / "backups" / "pantrypal-latest.sqlite3"

    exit_code = main([
        "--source", str(source),
        "--dest", str(dest),
        "--verify",
    ])

    captured = capfd.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == str(dest)
    assert "Backup verification passed" in captured.err
    assert "Post-backup reminder" in captured.err
    assert "pantrypal-latest.sqlite3" in captured.err


def test_post_backup_reminder_stays_off_base64_stdout(tmp_path, capfd):
    source = _make_pantrypal_db(tmp_path / "source.sqlite3")
    dest = tmp_path / "backups" / "pantrypal-latest.sqlite3"

    exit_code = main([
        "--source", str(source),
        "--dest", str(dest),
        "--verify",
        "--emit-base64",
    ])

    captured = capfd.readouterr()
    lines = captured.out.splitlines()
    assert exit_code == 0
    assert lines[0] == BASE64_BEGIN_MARKER
    assert lines[-1] == BASE64_END_MARKER
    assert "Post-backup reminder" not in captured.out
    assert "Post-backup reminder" in captured.err


def test_verify_file_mode_does_not_emit_post_backup_reminder(tmp_path, capfd):
    backup = _make_pantrypal_db(tmp_path / "existing.sqlite3")

    assert main(["--verify-file", str(backup)]) == 0

    captured = capfd.readouterr()
    assert "Backup verification passed" in captured.err
    assert "Post-backup reminder" not in captured.err


def test_readme_documents_phase_7z_download_and_restore_drill_reminder():
    readme = README.read_text()

    assert "Post-backup download/check reminder (Phase 7Z)" in readme
    assert "Download the new `pantrypal-*.sqlite3` file" in readme
    assert ".venv/bin/python scripts/restore_drill.py backups/pantrypal-YYYYMMDDTHHMMSSZ.sqlite3" in readme
    assert "Only trust a backup after the restore drill exits 0" in readme
