"""
Phase 7G regression suite — SQLite busy timeout + WAL.

Fly runs gunicorn with one worker and multiple threads. SQLite remains the
right v1 database, but each SQLite connection should tolerate brief writer
contention and use WAL mode so readers and writers interfere less.

Tier-1 dev loop:

    pytest tests/test_phase_7g.py -q
"""
from __future__ import annotations

from sqlalchemy import text

from app import SQLITE_BUSY_TIMEOUT_SECONDS, create_app


def _fresh_sqlite_app(tmp_path, monkeypatch):
    db_file = tmp_path / "phase_7g.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret-not-for-production")
    return create_app()


def test_sqlite_engine_uses_busy_timeout(tmp_path, monkeypatch):
    app = _fresh_sqlite_app(tmp_path, monkeypatch)

    assert app.config["SQLALCHEMY_ENGINE_OPTIONS"] == {
        "connect_args": {"timeout": SQLITE_BUSY_TIMEOUT_SECONDS},
    }


def test_sqlite_connections_enable_wal_journal_mode(tmp_path, monkeypatch):
    app = _fresh_sqlite_app(tmp_path, monkeypatch)

    with app.app_context():
        from extensions import db

        journal_mode = db.session.execute(text("PRAGMA journal_mode")).scalar()

    assert journal_mode.lower() == "wal"
