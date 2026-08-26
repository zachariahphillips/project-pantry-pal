"""
Phase 7H regression suite — production cookie hardening.

Fly terminates HTTPS in front of the app, so production can require secure
cookies. Local dev and test still need plain HTTP to work.

Tier-1 dev loop:

    pytest tests/test_phase_7h.py -q
"""
from __future__ import annotations

from app import create_app


def _configured_app(tmp_path, monkeypatch, *, flask_env: str | None):
    db_file = tmp_path / "phase_7h.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret-not-for-production")
    if flask_env is None:
        monkeypatch.delenv("FLASK_ENV", raising=False)
    else:
        monkeypatch.setenv("FLASK_ENV", flask_env)

    return create_app()


def test_production_enables_secure_session_and_remember_cookies(
        tmp_path, monkeypatch):
    app = _configured_app(tmp_path, monkeypatch, flask_env="production")

    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["REMEMBER_COOKIE_SECURE"] is True
    assert app.config["REMEMBER_COOKIE_HTTPONLY"] is True
    assert app.config["REMEMBER_COOKIE_SAMESITE"] == "Lax"


def test_development_keeps_cookies_usable_over_plain_http(
        tmp_path, monkeypatch):
    app = _configured_app(tmp_path, monkeypatch, flask_env=None)

    assert app.config["SESSION_COOKIE_SECURE"] is False
    assert app.config.get("REMEMBER_COOKIE_SECURE", False) is False
