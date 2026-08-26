"""
Phase 7I regression suite — deploy smoke cookie checks.

The production smoke test now verifies cookie flags on HTTPS deploys. These
tests keep the flag parser honest without requiring a live gunicorn process.

Tier-1 dev loop:

    pytest tests/test_phase_7i.py -q
"""
from __future__ import annotations

from http.cookiejar import Cookie

from scripts.prod_smoke import _missing_cookie_security_flags


def _cookie(*, secure: bool, rest: dict[str, str | None]) -> Cookie:
    return Cookie(
        version=0,
        name="session",
        value="abc123",
        port=None,
        port_specified=False,
        domain="example.com",
        domain_specified=True,
        domain_initial_dot=False,
        path="/",
        path_specified=True,
        secure=secure,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest=rest,
        rfc2109=False,
    )


def test_cookie_security_helper_accepts_hardened_cookie():
    cookie = _cookie(
        secure=True,
        rest={"HttpOnly": None, "SameSite": "Lax"},
    )

    assert _missing_cookie_security_flags(cookie) == []


def test_cookie_security_helper_reports_missing_flags():
    cookie = _cookie(
        secure=False,
        rest={"SameSite": "Strict"},
    )

    assert _missing_cookie_security_flags(cookie) == [
        "Secure",
        "HttpOnly",
        "SameSite=Lax",
    ]
