"""
Phase 7L regression suite — maintenance mode for restore safety.

MAINTENANCE_MODE blocks normal app traffic with a friendly 503 while keeping
health checks and static assets reachable during planned restore windows.

Tier-1 dev loop:

    pytest tests/test_phase_7l.py -q
"""
from __future__ import annotations

from app import create_app


def _maintenance_app(tmp_path, monkeypatch):
    db_file = tmp_path / "phase_7l.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret-not-for-production")
    monkeypatch.setenv("MAINTENANCE_MODE", "1")
    return create_app()


def test_maintenance_mode_blocks_normal_app_routes(tmp_path, monkeypatch):
    app = _maintenance_app(tmp_path, monkeypatch)

    resp = app.test_client().get("/login")

    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == "300"
    body = resp.get_data(as_text=True)
    assert "PantryPal is down for maintenance" in body
    assert "Please try again in about five minutes." in body


def test_maintenance_mode_allows_healthz(tmp_path, monkeypatch):
    app = _maintenance_app(tmp_path, monkeypatch)

    resp = app.test_client().get("/healthz")

    assert resp.status_code == 200
    assert resp.json == {"status": "ok", "phase": "7R"}


def test_maintenance_mode_allows_static_assets(tmp_path, monkeypatch):
    app = _maintenance_app(tmp_path, monkeypatch)

    resp = app.test_client().get("/static/site.webmanifest")

    assert resp.status_code == 200
    assert "PantryPal" in resp.get_data(as_text=True)
