"""
Phase 7T regression suite — backup restore verification.

Phases 7M-7S built the backup pipeline and documented it, but the only
correctness check anywhere in the chain was `test -s` on the decoded file: a
truncated or corrupt backup passed and you'd find out during a real restore.
These tests guard the integrity check, the required-table check, and the two
properties the pipeline depends on — a failed verify never reaches the artifact
upload, and verification chatter never pollutes the base64 stream on stdout.

Tier-1 dev loop:

    pytest tests/test_phase_7t.py -q
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts.backup_sqlite import (
    BASE64_BEGIN_MARKER,
    BASE64_END_MARKER,
    REQUIRED_BACKUP_TABLES,
    BackupVerificationError,
    main,
    verify_backup,
)


ROOT = Path(__file__).resolve().parents[1]


def _make_pantrypal_db(path: Path, *, tables=REQUIRED_BACKUP_TABLES) -> Path:
    """A stand-in for a production DB: right table names, enough rows to span
    several pages so truncation tests remove real content, not just slack."""
    conn = sqlite3.connect(path)
    try:
        for table in tables:
            conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY, name TEXT)")
        conn.executemany(
            f"INSERT INTO {tables[0]} (name) VALUES (?)",
            [(f"row-{n}-{'x' * 200}",) for n in range(200)],
        )
        conn.commit()
    finally:
        conn.close()
    return path


def test_verify_backup_accepts_a_real_backup(tmp_path):
    backup = _make_pantrypal_db(tmp_path / "pantrypal-backup.sqlite3")

    table_names = verify_backup(backup)

    assert set(REQUIRED_BACKUP_TABLES).issubset(table_names)


def test_verify_backup_rejects_a_truncated_backup(tmp_path):
    """The failure mode the base64 transport can actually produce.

    A backup cut off mid-file keeps a valid SQLite header, so anything that
    only checks the first bytes (or the file size) waves it through.
    """
    backup = _make_pantrypal_db(tmp_path / "pantrypal-backup.sqlite3")
    intact = backup.read_bytes()
    backup.write_bytes(intact[: len(intact) // 2])

    with pytest.raises(BackupVerificationError):
        verify_backup(backup)


def test_verify_backup_rejects_a_file_that_is_not_a_database(tmp_path):
    backup = tmp_path / "pantrypal-backup.sqlite3"
    backup.write_text("this is not a database, it is an error page")

    with pytest.raises(BackupVerificationError, match="not a readable SQLite database"):
        verify_backup(backup)


def test_verify_backup_rejects_an_empty_file(tmp_path):
    backup = tmp_path / "pantrypal-backup.sqlite3"
    backup.touch()

    with pytest.raises(BackupVerificationError, match="empty"):
        verify_backup(backup)


def test_verify_backup_rejects_a_missing_file(tmp_path):
    with pytest.raises(BackupVerificationError, match="not found"):
        verify_backup(tmp_path / "nope.sqlite3")


def test_verify_backup_names_the_missing_tables(tmp_path):
    """A valid SQLite file from the wrong app shouldn't count as a backup."""
    backup = _make_pantrypal_db(
        tmp_path / "pantrypal-backup.sqlite3",
        tables=("households", "users"),
    )

    with pytest.raises(BackupVerificationError) as excinfo:
        verify_backup(backup)

    message = str(excinfo.value)
    assert "pantry_items" in message
    assert "shopping_items" in message


def test_verify_file_cli_exit_codes(tmp_path, capfd):
    good = _make_pantrypal_db(tmp_path / "good.sqlite3")
    bad = tmp_path / "bad.sqlite3"
    bad.write_text("not a database")

    assert main(["--verify-file", str(good)]) == 0
    assert main(["--verify-file", str(bad)]) == 1

    assert "Backup verification FAILED" in capfd.readouterr().err


def test_failed_verification_blocks_emit_and_prune(tmp_path, capfd):
    """A corrupt backup must not become an artifact or evict an older one.

    Verification runs before the base64 emit and before --keep pruning, so a
    bad run leaves the existing restore points alone.

    capfd, not capsys: emit_backup_base64 defaults its output to the sys.stdout
    bound at import, so only fd-level capture sees the marker block. That also
    matches how the workflow reads it (a shell `>` redirect).
    """
    source = _make_pantrypal_db(tmp_path / "source.sqlite3", tables=("users",))
    dest_dir = tmp_path / "backups"
    dest_dir.mkdir()
    older = dest_dir / "pantrypal-20260901T000000Z.sqlite3"
    older.write_text("older backup")

    exit_code = main([
        "--source", str(source),
        "--dest", str(dest_dir / "pantrypal-20260902T000000Z.sqlite3"),
        "--verify", "--emit-base64", "--keep", "1",
    ])

    captured = capfd.readouterr()
    assert exit_code == 1
    assert BASE64_BEGIN_MARKER not in captured.out
    assert "Backup verification FAILED" in captured.err
    assert older.exists()


def test_verification_output_stays_off_the_base64_stream(tmp_path, capfd):
    """stdout carries the marker protocol; verify messages go to stderr.

    The workflow pipes stdout through awk to find the markers, so a stray
    progress line on stdout would corrupt the decoded artifact.
    """
    source = _make_pantrypal_db(tmp_path / "source.sqlite3")

    exit_code = main([
        "--source", str(source),
        "--dest", str(tmp_path / "backup.sqlite3"),
        "--verify", "--emit-base64",
    ])

    captured = capfd.readouterr()
    lines = captured.out.splitlines()
    assert exit_code == 0
    assert lines[0] == BASE64_BEGIN_MARKER
    assert lines[-1] == BASE64_END_MARKER
    assert "Backup verification passed" in captured.err


def test_backup_workflow_verifies_before_uploading():
    workflow = (ROOT / ".github" / "workflows" / "backup.yml").read_text()

    assert "actions/checkout@v4" in workflow
    assert "--verify --emit-base64 --keep 14" in workflow
    assert "--verify-file pantrypal-backup.sqlite3" in workflow
    # Ordering is the point: verification has to gate the upload.
    assert workflow.index("Verify decoded backup") < workflow.index(
        "Upload SQLite backup artifact"
    )


def test_readme_documents_backup_verification():
    readme = (ROOT / "README.md").read_text()

    assert "PRAGMA integrity_check" in readme
    assert "--verify-file backups/pantrypal-backup.sqlite3" in readme
    assert "`Verify decoded backup`" in readme
