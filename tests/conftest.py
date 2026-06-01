"""
Shared pytest fixtures for the PantryPal test suite.

Each test gets its own Flask app backed by a per-test SQLite file, so
test order is irrelevant and there's never a leftover-state surprise.
We keep CSRF protection *on* in the test client so the tests exercise
the same code path the browser does. The `Client` wrapper grabs the
rotating CSRF token out of the rendered HTML on first use, the same
way the htmx listener in `base.html` does.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

# Make the project root importable when pytest is invoked from anywhere.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def app(tmp_path, monkeypatch):
    """A fresh Flask app + empty SQLite file per test."""
    db_file = tmp_path / "test.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret-not-for-production")

    # Import inside the fixture so the env vars are read at create_app() time.
    from app import create_app

    app = create_app()
    app.config["TESTING"] = True
    # Flask-WTF refuses CSRF tokens whose Referer/Origin doesn't match the
    # server name when SERVER_NAME is set; we leave it unset and rely on the
    # default localhost.
    yield app


class Client:
    """Thin wrapper around Flask's test_client that auto-refreshes the
    per-session CSRF token and emits htmx-style headers when asked."""

    def __init__(self, flask_client):
        self._c = flask_client
        self._token: str | None = None

    # ---- internal helpers ----

    def _scrape_token(self, html: str) -> None:
        m = re.search(r'<meta name="csrf-token" content="([^"]+)"', html)
        if m:
            self._token = m.group(1)
            return
        m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
        if m:
            self._token = m.group(1)

    def _ensure_token(self) -> None:
        if self._token is None:
            resp = self._c.get("/signup")
            self._scrape_token(resp.get_data(as_text=True))

    # ---- public surface ----

    def get(self, path: str, *, htmx: bool = False, follow_redirects: bool = False):
        headers = {}
        if htmx:
            self._ensure_token()
            headers["HX-Request"] = "true"
            headers["X-CSRFToken"] = self._token or ""
        resp = self._c.get(path, headers=headers, follow_redirects=follow_redirects)
        self._scrape_token(resp.get_data(as_text=True))
        return resp

    def post(self, path: str, *, data: dict | None = None, htmx: bool = False,
             follow_redirects: bool = False):
        headers = {}
        if htmx:
            self._ensure_token()
            headers["HX-Request"] = "true"
            headers["X-CSRFToken"] = self._token or ""
        # Auto-attach the CSRF token to form bodies that don't already include it.
        body = dict(data) if data else {}
        if "csrf_token" not in body:
            self._ensure_token()
            body["csrf_token"] = self._token or ""
        resp = self._c.post(path, data=body, headers=headers,
                            follow_redirects=follow_redirects)
        self._scrape_token(resp.get_data(as_text=True))
        return resp

    def put(self, path: str, *, data: dict | None = None, htmx: bool = True):
        headers = {}
        if htmx:
            self._ensure_token()
            headers["HX-Request"] = "true"
            headers["X-CSRFToken"] = self._token or ""
        body = dict(data) if data else {}
        if "csrf_token" not in body:
            self._ensure_token()
            body["csrf_token"] = self._token or ""
        resp = self._c.put(path, data=body, headers=headers)
        self._scrape_token(resp.get_data(as_text=True))
        return resp

    def delete(self, path: str, *, htmx: bool = True):
        headers = {}
        if htmx:
            self._ensure_token()
            headers["HX-Request"] = "true"
            headers["X-CSRFToken"] = self._token or ""
        resp = self._c.delete(path, headers=headers)
        self._scrape_token(resp.get_data(as_text=True))
        return resp


@pytest.fixture
def client(app):
    """A Client wired up to a fresh test cookie jar."""
    return Client(app.test_client())


@pytest.fixture
def two_clients(app):
    """Two independent clients sharing the same app — used to verify
    cross-user isolation (alice can't reach bob's items and vice versa)."""
    return Client(app.test_client()), Client(app.test_client())


# ---- helpers callers re-use ----

def sign_up(c: Client, email: str, name: str, password: str = "testpass123"):
    """Create an account; expects landing on /pantry."""
    resp = c.post("/signup", data={
        "name": name, "email": email, "password": password,
        "submit": "Create account",
    }, follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Your pantry" in body, "signup didn't land on /pantry"
    return body


def id_for(html: str, name: str, prefix: str) -> str | None:
    """Return the numeric id of the row in `html` containing `name`."""
    for iid in re.findall(rf'id="{prefix}-(\d+)"', html):
        match = re.search(
            rf'id="{prefix}-{iid}".*?(?=id="{prefix}-\d+|'
            r'<div class="rounded-2xl border border-dashed|$)',
            html, re.DOTALL)
        if match and name in match.group(0):
            return iid
    return None
