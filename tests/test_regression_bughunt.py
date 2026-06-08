"""
Bug-hunt regression suite — 2026-06-08.

Three issues surfaced during a pre-Phase-3 code review. Each test below
REPRODUCES the bug first (red), then the corresponding fix in app.py
turns it green. Keeping these in the suite so we never regress.

1) ProxyFix not installed: behind a reverse proxy (Fly.io's edge), Flask
   doesn't trust X-Forwarded-Proto / X-Forwarded-For headers, so
   `url_for(_external=True)` and `request.is_secure` lie. Result: the
   invite-share URL in _household_share.html would say `http://` on
   the production Fly.dev URL even though Fly serves over HTTPS.

2) SECRET_KEY default fallback in production: if the user forgets to
   `fly secrets set FLASK_SECRET_KEY=...`, the app starts with a
   well-known default value, making session cookies forgeable and
   CSRF tokens predictable. We want to FAIL LOUD when running with
   FLASK_ENV=production + a placeholder secret.

3) Open-redirect via backslash on /login?next=...: the existing check
   (`next_url.startswith("/") and not next_url.startswith("//")`) lets
   `next=/\\evil.com` through. Some browsers normalize `\\` to `//`,
   redirecting users off-site after login. Werkzeug's url_parse +
   netloc check is the right defense.
"""
from __future__ import annotations

import os

import pytest

from tests.conftest import sign_up


# ---------------------------------------------------------------------------
# Bug 1: ProxyFix
# ---------------------------------------------------------------------------

class TestProxyFix:
    def test_proxy_fix_is_installed(self, app):
        """Structural check: ProxyFix must be wrapped around app.wsgi_app.
        Without it, X-Forwarded-Proto/Host/For headers from Fly's edge
        proxy are ignored and `url_for(_external=True)` builds http://
        URLs. The behavioral test below confirms the wiring works."""
        from werkzeug.middleware.proxy_fix import ProxyFix
        assert isinstance(app.wsgi_app, ProxyFix), (
            "ProxyFix not installed on app.wsgi_app. On Fly.io, the "
            "invite-share Copy field would show http:// URLs even though "
            "Fly serves over HTTPS. See create_app() in app.py."
        )

    def test_x_forwarded_proto_https_promotes_request_to_secure(
            self, client, app):
        """End-to-end: a request to the running app with
        X-Forwarded-Proto=https should be seen as request.is_secure=True
        AND url_for(_external=True) should produce https:// URLs.

        We hit a tiny throwaway route registered just for this test —
        adding it permanently to app.py would be noise."""
        captured = {}

        @app.route("/_test_proxy_fix_probe")
        def _probe():
            from flask import request, url_for
            captured["is_secure"] = request.is_secure
            captured["scheme"] = request.scheme
            captured["host"] = request.host
            captured["external_url"] = url_for(
                "join_landing", token="abc", _external=True,
            )
            return "", 204

        flask_client = app.test_client()
        resp = flask_client.get(
            "/_test_proxy_fix_probe",
            headers={
                "X-Forwarded-Proto": "https",
                "X-Forwarded-Host": "pantrypal-riah.fly.dev",
                "X-Forwarded-For": "203.0.113.1",
            },
        )
        assert resp.status_code == 204
        assert captured["is_secure"] is True, (
            "X-Forwarded-Proto=https was ignored — ProxyFix probably "
            "isn't passing it through. Invite share URLs would say "
            f"http:// on Fly. Captured: {captured!r}"
        )
        assert captured["scheme"] == "https", captured
        assert captured["external_url"].startswith("https://"), (
            f"Expected https:// invite URL, got {captured['external_url']!r}"
        )
        assert "pantrypal-riah.fly.dev" in captured["external_url"], captured


# ---------------------------------------------------------------------------
# Bug 2: SECRET_KEY production guard
# ---------------------------------------------------------------------------

class TestSecretKeyGuard:
    """The .env file in this project's root sets a real FLASK_SECRET_KEY
    for local dev. python-dotenv's default behavior is "don't override
    existing env vars," so monkeypatch.setenv WINS over the .env file.
    We use that to force the placeholder value into env for guard tests."""

    PLACEHOLDER = "dev-secret-change-me-in-env"

    def test_production_with_placeholder_secret_raises(
            self, tmp_path, monkeypatch):
        """The first-deploy footgun: FLASK_ENV=production + the default
        placeholder key (because `fly secrets set FLASK_SECRET_KEY=...`
        was forgotten) → silent boot with a well-known secret. Guard
        must refuse to start.

        NB: the RuntimeError fires during `importlib.reload(app_module)`
        because app.py has `app = create_app()` at module scope — so we
        wrap the reload itself in pytest.raises, not a separate call."""
        db_file = tmp_path / "guard.sqlite3"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
        monkeypatch.setenv("FLASK_ENV", "production")
        # Force the placeholder into env BEFORE the reload, so load_dotenv()
        # doesn't override us with the .env's real key.
        monkeypatch.setenv("FLASK_SECRET_KEY", self.PLACEHOLDER)

        import importlib
        import app as app_module
        with pytest.raises(RuntimeError, match=r"FLASK_SECRET_KEY"):
            importlib.reload(app_module)

    def test_production_with_empty_secret_raises(self, tmp_path, monkeypatch):
        """`fly secrets set FLASK_SECRET_KEY=` (empty value) is also unsafe
        — the guard should catch both empty AND placeholder."""
        db_file = tmp_path / "empty.sqlite3"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("FLASK_SECRET_KEY", "")

        import importlib
        import app as app_module
        with pytest.raises(RuntimeError, match=r"FLASK_SECRET_KEY"):
            importlib.reload(app_module)

    def test_dev_with_placeholder_secret_still_starts(
            self, tmp_path, monkeypatch):
        """In dev mode, the placeholder secret should still work — we
        don't want to break the `python app.py` quick-start. Only
        FLASK_ENV=production triggers the guard."""
        db_file = tmp_path / "dev.sqlite3"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
        monkeypatch.delenv("FLASK_ENV", raising=False)
        monkeypatch.setenv("FLASK_SECRET_KEY", self.PLACEHOLDER)

        import importlib
        import app as app_module
        importlib.reload(app_module)

        app = app_module.create_app()
        assert app is not None
        assert app.config["SECRET_KEY"] == self.PLACEHOLDER

    def test_production_with_real_secret_starts(self, tmp_path, monkeypatch):
        """The happy path: FLASK_ENV=production + a real secret = boot OK."""
        db_file = tmp_path / "prod.sqlite3"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
        monkeypatch.setenv("FLASK_ENV", "production")
        monkeypatch.setenv("FLASK_SECRET_KEY", "a-real-secret-with-enough-entropy")

        import importlib
        import app as app_module
        importlib.reload(app_module)

        app = app_module.create_app()
        assert app.config["SECRET_KEY"] == "a-real-secret-with-enough-entropy"


# ---------------------------------------------------------------------------
# Bug 3: ?next= open-redirect via backslash
# ---------------------------------------------------------------------------

class TestNextRedirectSafety:
    def test_login_rejects_backslash_open_redirect(self, client, app):
        """`?next=/\\evil.com` looks like a safe relative path under the
        old startswith('/') check, but browsers normalize `\\` to `//`
        and follow it as a protocol-relative URL. The fixed code should
        refuse to redirect anywhere with a netloc and fall back to
        /pantry instead."""
        # Set up an account to log in as
        sign_up(client, email="redirect-test@example.com", name="Redirect")
        # Log them out so we can /login with ?next=
        client.post("/logout")

        resp = client.post(
            "/login?next=/\\evil.com",
            data={
                "email": "redirect-test@example.com",
                "password": "testpass123",
                "remember": "y",
            },
        )
        # Should redirect, but NOT to evil.com under any interpretation.
        assert resp.status_code == 302, f"expected redirect, got {resp.status_code}"
        location = resp.headers.get("Location", "")
        assert "evil.com" not in location, (
            f"open-redirect: server-side accepted /\\evil.com and redirected "
            f"to {location!r}. Browsers normalize \\ to / so this can land "
            "the user off-site."
        )
        # Should land on /pantry instead (the safe fallback)
        assert location.endswith("/pantry") or location == "/pantry", (
            f"expected safe fallback to /pantry, got {location!r}"
        )

    def test_login_accepts_real_relative_next(self, client, app):
        """Sanity check: the FIX shouldn't break legitimate ?next=
        redirects (e.g. someone hit /shopping while signed out)."""
        sign_up(client, email="real-next@example.com", name="Real Next")
        client.post("/logout")

        resp = client.post(
            "/login?next=/shopping",
            data={
                "email": "real-next@example.com",
                "password": "testpass123",
                "remember": "y",
            },
        )
        assert resp.status_code == 302
        location = resp.headers.get("Location", "")
        assert location.endswith("/shopping"), (
            f"legitimate ?next=/shopping should be honored, got {location!r}"
        )

    def test_login_rejects_protocol_relative_next(self, client, app):
        """Belt-and-suspenders: //evil.com (no backslash) was already
        caught by the old check — verify it still is after the fix."""
        sign_up(client, email="proto-rel@example.com", name="Proto Rel")
        client.post("/logout")

        resp = client.post(
            "/login?next=//evil.com",
            data={
                "email": "proto-rel@example.com",
                "password": "testpass123",
                "remember": "y",
            },
        )
        assert resp.status_code == 302
        location = resp.headers.get("Location", "")
        assert "evil.com" not in location
