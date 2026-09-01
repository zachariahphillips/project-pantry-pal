"""
Phase 7N regression suite — maintenance page polish.

MAINTENANCE_MESSAGE lets restore/deploy windows show specific, friendly copy
without changing code.

Tier-1 dev loop:

    pytest tests/test_phase_7n.py -q
"""
from __future__ import annotations

from app import DEFAULT_MAINTENANCE_MESSAGE, create_app


def _maintenance_app(tmp_path, monkeypatch, *, message: str | None = None):
    db_file = tmp_path / "phase_7n.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret-not-for-production")
    monkeypatch.setenv("MAINTENANCE_MODE", "1")
    if message is None:
        monkeypatch.delenv("MAINTENANCE_MESSAGE", raising=False)
    else:
        monkeypatch.setenv("MAINTENANCE_MESSAGE", message)
    return create_app()


def test_maintenance_page_uses_default_message(tmp_path, monkeypatch):
    app = _maintenance_app(tmp_path, monkeypatch)

    resp = app.test_client().get("/login")

    body = resp.get_data(as_text=True)
    assert resp.status_code == 503
    assert DEFAULT_MAINTENANCE_MESSAGE in body
    assert "Try refreshing this page in about five minutes." in body


def test_maintenance_page_uses_custom_message(tmp_path, monkeypatch):
    custom_message = "We are restoring PantryPal from backup."
    app = _maintenance_app(tmp_path, monkeypatch, message=custom_message)

    resp = app.test_client().get("/login")

    body = resp.get_data(as_text=True)
    assert resp.status_code == 503
    assert custom_message in body
    assert DEFAULT_MAINTENANCE_MESSAGE not in body
