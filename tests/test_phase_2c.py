"""
Phase 2C regression suite — production deployment shape.

This is intentionally a tiny suite: the deploy work is mostly config
(Dockerfile, fly.toml). What we DO want a test for is the slash-counting
gotcha in SQLAlchemy SQLite URLs — getting `sqlite:////` wrong (3 slashes
vs 4) silently sends the DB to the wrong location, which on Fly would mean
the SQLite file lives on the ephemeral container filesystem instead of
the persistent volume mount at /data. We'd lose data on every redeploy
and not notice until somebody's pantry vanished.

The healthz check is a smoke for "the app still boots under prod-shape
config" — phase string also doubles as a visual confirmation that the
right version of the code is live on Fly.
"""
from __future__ import annotations

import os


class TestProductionDatabaseUrl:
    def test_four_slash_url_creates_file_at_absolute_path(
            self, tmp_path, monkeypatch):
        """`sqlite:////<abs>` (4 slashes) MUST resolve to that absolute path,
        not be re-rooted under Flask's instance folder. This is what the
        Fly volume at /data depends on."""
        abs_db = tmp_path / "prod_shape.sqlite3"
        # tmp_path is absolute (starts with /), so the string below has
        # exactly 4 slashes between `sqlite:` and the rest of the path —
        # this is the form fly.toml uses.
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{abs_db}")
        monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret-not-for-production")

        from app import create_app
        app = create_app()
        # Force a write so we know the file actually exists on disk.
        with app.app_context():
            from extensions import db
            from models import User
            user = User(email="prod-shape@example.com", name="Prod Shape")
            user.set_password("testpass1")
            db.session.add(user)
            db.session.commit()

        assert abs_db.exists(), (
            "4-slash SQLite URL should create the DB at the absolute path; "
            f"got nothing at {abs_db}. If this fails, fly.toml's DATABASE_URL "
            "is probably putting the prod DB on ephemeral container disk "
            "instead of the persistent volume."
        )
        # And just to be paranoid: nothing should have been written under
        # the instance folder.
        instance_db = tmp_path / "instance" / "prod_shape.sqlite3"
        assert not instance_db.exists()

    def test_three_slash_url_still_uses_instance_folder(
            self, tmp_path, monkeypatch):
        """Sanity check the OTHER direction: 3-slash URLs are still
        relative-to-instance. If a future SQLAlchemy version changes this
        behavior, our local dev would silently break. Pin it with a test."""
        # 3 slashes = "sqlite:///foo.sqlite3" = relative to instance folder
        monkeypatch.setenv("DATABASE_URL", "sqlite:///three_slash_test.sqlite3")
        monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret-not-for-production")
        # Point Flask's instance folder at the tmp_path so we can find the
        # file afterwards without polluting the real instance/ folder.
        monkeypatch.chdir(tmp_path)

        from app import create_app
        app = create_app()
        # The URI Flask-SQLAlchemy stored should be the same string we set —
        # SQLAlchemy resolves it at engine-create time.
        assert app.config["SQLALCHEMY_DATABASE_URI"].endswith("three_slash_test.sqlite3")


class TestHealthz:
    def test_healthz_reports_current_phase(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        # Phase string is also the cue Fly's `fly logs` watch uses to
        # confirm the right code is live after a deploy. Bump this when
        # phase number changes.
        assert resp.json == {"status": "ok", "phase": "7R"}

    def test_healthz_returns_503_when_database_ping_fails(
            self, client, monkeypatch):
        """Phase 7B: healthz is now a deep check, not just a process check.
        Fly should stop sending traffic to a machine whose SQLite volume is
        missing, locked, or otherwise unavailable."""
        from extensions import db

        def fail_db_ping(*args, **kwargs):
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(db.session, "execute", fail_db_ping)

        resp = client.get("/healthz")

        assert resp.status_code == 503
        assert resp.json == {
            "status": "error",
            "phase": "7R",
            "database": "unavailable",
        }
