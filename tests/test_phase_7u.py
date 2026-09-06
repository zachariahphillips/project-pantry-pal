"""
Phase 7U regression suite — scripted restore drill.

The drill itself needs a real gunicorn, so it isn't run here. What these tests
guard is everything around it that can silently make a drill meaningless: a
three-slash SQLite URL (serves the wrong database), a leaked MAINTENANCE_MODE
(smoke-tests the maintenance page instead of the app), serving the backup in
place (the smoke suite writes, so it would corrupt the restore point), and
leaked gunicorn processes or temp files when a drill fails.

Tier-1 dev loop:

    pytest tests/test_phase_7u.py -q
"""
from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path

import pytest

from scripts.backup_sqlite import (
    REQUIRED_BACKUP_TABLES,
    BackupVerificationError,
    backup_sqlite,
    verify_backup,
)
from scripts.restore_drill import (
    DrillError,
    build_gunicorn_command,
    drill_environment,
    pick_free_port,
    run_drill,
    sqlite_url_for_path,
    wait_for_healthz,
)


ROOT = Path(__file__).resolve().parents[1]


def _healthy(url: str) -> int:
    """Stands in for the /healthz probe so drill tests don't wait on a socket."""
    return 200


def _make_backup(path: Path) -> Path:
    conn = sqlite3.connect(path)
    try:
        for table in REQUIRED_BACKUP_TABLES:
            conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()
    return path


class FakeProcess:
    """Stands in for the gunicorn Popen: alive until terminated."""

    def __init__(self, *, hang_on_terminate: bool = False):
        self.returncode: int | None = None
        self.hang_on_terminate = hang_on_terminate
        self.terminated = False
        self.killed = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        if not self.hang_on_terminate:
            self.returncode = 0

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("gunicorn", timeout)
        return self.returncode


def test_sqlite_url_for_absolute_path_uses_four_slashes(tmp_path):
    """Three slashes resolves against Flask's instance folder, which would
    quietly drill a database other than the one being restored."""
    url = sqlite_url_for_path(tmp_path / "restore-drill.sqlite3")

    assert url.startswith("sqlite:////")
    assert url.endswith("restore-drill.sqlite3")


def test_gunicorn_command_pins_single_worker_and_target_port():
    command = build_gunicorn_command(54321, gunicorn_bin="/venv/bin/gunicorn")

    assert command[0] == "/venv/bin/gunicorn"
    assert "--bind" in command
    assert "127.0.0.1:54321" in command
    # SQLite is single-writer; more workers means lock errors, not a real drill.
    assert command[command.index("--workers") + 1] == "1"
    assert command[-1] == "app:app"


def test_drill_environment_points_at_the_copy_with_a_throwaway_secret(tmp_path):
    db_path = tmp_path / "restore-drill.sqlite3"

    env = drill_environment(db_path, base_env={"PATH": "/usr/bin"})

    assert env["DATABASE_URL"] == sqlite_url_for_path(db_path)
    assert env["PATH"] == "/usr/bin"
    assert len(env["FLASK_SECRET_KEY"]) >= 32


def test_drill_environment_drops_inherited_maintenance_mode(tmp_path):
    """The restore runbook tells you to enable maintenance mode, so an operator
    mid-restore may well have it exported. Left set, every smoke check would
    hit the maintenance page and the drill would prove nothing."""
    env = drill_environment(
        tmp_path / "db.sqlite3",
        base_env={"MAINTENANCE_MODE": "1", "MAINTENANCE_MESSAGE": "brb"},
    )

    assert "MAINTENANCE_MODE" not in env
    assert "MAINTENANCE_MESSAGE" not in env


def test_pick_free_port_returns_a_usable_port():
    port = pick_free_port()

    assert 1024 < port < 65536


def test_wait_for_healthz_returns_once_the_app_answers():
    statuses = [None, None, 503, 200]
    slept = []

    wait_for_healthz(
        "http://127.0.0.1:9",
        is_alive=lambda: True,
        fetch=lambda url: statuses.pop(0),
        sleep=slept.append,
        now=lambda: 0.0,
    )

    assert statuses == []
    assert len(slept) == 3


def test_wait_for_healthz_fails_fast_when_gunicorn_dies():
    """The interesting failure: a backup this code cannot load makes the worker
    exit on boot, and waiting out the full timeout hides the reason."""
    with pytest.raises(DrillError, match="exited before it answered"):
        wait_for_healthz(
            "http://127.0.0.1:9",
            is_alive=lambda: False,
            fetch=lambda url: None,
            sleep=lambda seconds: None,
            now=lambda: 0.0,
        )


def test_wait_for_healthz_times_out():
    clock = iter([0.0, 1.0, 99.0])

    with pytest.raises(DrillError, match="timed out"):
        wait_for_healthz(
            "http://127.0.0.1:9",
            is_alive=lambda: True,
            timeout=5.0,
            fetch=lambda url: None,
            sleep=lambda seconds: None,
            now=lambda: next(clock),
        )


def test_corrupt_backup_never_launches_anything(tmp_path):
    backup = tmp_path / "bad.sqlite3"
    backup.write_text("not a database")
    launches = []

    with pytest.raises(BackupVerificationError):
        run_drill(
            backup,
            port=9999,
            launch=lambda *a, **kw: launches.append(kw) or FakeProcess(),
            smoke=lambda base_url: 0,
        )

    assert launches == []


def test_drill_serves_a_byte_identical_copy_and_cleans_it_up(tmp_path):
    """The smoke suite signs users up, so the drill must never point gunicorn
    at the backup itself."""
    backup = _make_backup(tmp_path / "pantrypal-backup.sqlite3")
    original_bytes = backup.read_bytes()
    captured = {}

    def fake_launch(command, env, cwd):
        captured["url"] = env["DATABASE_URL"]
        return FakeProcess()

    def fake_smoke(base_url):
        served = Path(captured["url"].replace("sqlite:///", "", 1))
        captured["served_path"] = served
        captured["served_bytes"] = served.read_bytes()
        return 0

    exit_code = run_drill(
        backup,
        port=9999,
        launch=fake_launch,
        smoke=fake_smoke,
        fetch=_healthy,
    )

    assert exit_code == 0
    assert captured["served_path"] != backup
    assert captured["served_bytes"] == original_bytes
    assert backup.read_bytes() == original_bytes
    # Temp copy is a restore point's worth of real data; it must not linger.
    assert not captured["served_path"].exists()
    assert not captured["served_path"].parent.exists()


def test_drill_returns_the_smoke_exit_code(tmp_path):
    backup = _make_backup(tmp_path / "pantrypal-backup.sqlite3")

    exit_code = run_drill(
        backup,
        port=9999,
        launch=lambda *a, **kw: FakeProcess(),
        smoke=lambda base_url: 3,
        fetch=_healthy,
    )

    assert exit_code == 3


def test_drill_terminates_gunicorn_even_when_smoke_explodes(tmp_path):
    backup = _make_backup(tmp_path / "pantrypal-backup.sqlite3")
    process = FakeProcess()

    def exploding_smoke(base_url):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_drill(
            backup,
            port=9999,
            launch=lambda *a, **kw: process,
            smoke=exploding_smoke,
            fetch=_healthy,
        )

    assert process.terminated


def test_drill_kills_gunicorn_when_it_ignores_terminate(tmp_path):
    backup = _make_backup(tmp_path / "pantrypal-backup.sqlite3")
    process = FakeProcess(hang_on_terminate=True)

    run_drill(
        backup,
        port=9999,
        launch=lambda *a, **kw: process,
        smoke=lambda base_url: 0,
        fetch=_healthy,
    )

    assert process.terminated
    assert process.killed


def test_verify_accepts_a_wal_mode_backup(tmp_path):
    """The first thing the drill caught, on its first real run.

    Phase 7K put production SQLite in WAL mode, so every real backup carries
    WAL in its header, and SQLite refuses a read-only open of such a file
    unless the reader declares it immutable. Phase 7T's verification only ever
    saw journal-mode fixtures, so it passed its own tests while rejecting every
    backup it exists to check -- including in the nightly workflow.
    """
    source = tmp_path / "wal-source.sqlite3"
    conn = sqlite3.connect(source)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        for table in REQUIRED_BACKUP_TABLES:
            conn.execute(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
        conn.commit()
    finally:
        conn.close()

    backup = backup_sqlite(source, tmp_path / "wal-backup.sqlite3")

    assert not backup.with_name(backup.name + "-shm").exists()
    assert sorted(verify_backup(backup)) == sorted(REQUIRED_BACKUP_TABLES)


def test_backup_captures_uncheckpointed_wal_writes(tmp_path):
    """The other half of the WAL fix, and the tempting way to get it wrong.

    Reading the *live* database as immutable would also have silenced the error
    above -- and would skip the `-wal`, backing up stale pages while every
    integrity check still passed. Only the finished artifact may be read that
    way.
    """
    source = tmp_path / "live.sqlite3"
    conn = sqlite3.connect(source)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT)")
        conn.commit()
        conn.execute("INSERT INTO users (email) VALUES ('late@example.com')")
        conn.commit()
        # Committed but still only in the -wal: exactly what an immutable read
        # would throw away.
        assert source.with_name(source.name + "-wal").stat().st_size > 0

        backup = backup_sqlite(source, tmp_path / "live-backup.sqlite3")
    finally:
        conn.close()

    restored = sqlite3.connect(backup)
    try:
        emails = [row[0] for row in restored.execute("SELECT email FROM users")]
    finally:
        restored.close()

    assert emails == ["late@example.com"]


def test_readme_documents_the_restore_drill():
    readme = (ROOT / "README.md").read_text()

    assert ".venv/bin/python scripts/restore_drill.py backups/pantrypal-backup.sqlite3" in readme
    assert "exit code 0" in readme.lower()
