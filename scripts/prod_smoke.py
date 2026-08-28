"""
Phase 2C prod-shape smoke test.

Hits a running gunicorn instance (NOT the Flask dev server) on port 8080
and exercises the full Phase 1B / 1C / 2A / 2B happy paths to confirm
nothing about the prod WSGI runtime breaks behavior we tested under the
Flask dev server. Specifically catches:

- gunicorn worker import errors (missing deps, wrong app factory shape)
- CSRF token / cookie handling differences under gthread vs single-threaded dev
- the migration-on-boot path under prod-shape DATABASE_URL (absolute SQLite)
- htmx fragment responses (which are the bulk of POST/PUT/DELETE traffic)
- Phase 7I secure cookie flags on HTTPS deploys

This is intentionally NOT a pytest test — it requires an externally-running
gunicorn, and that's exactly what we're trying to validate ("does the same
code that passes pytest also work under gunicorn?").

Run locally before deploy:
    1. terminal A: rm -f /tmp/pantrypal-prod-smoke.sqlite3
    2. terminal A: DATABASE_URL=sqlite:////tmp/pantrypal-prod-smoke.sqlite3 \
                   FLASK_SECRET_KEY=secret \
                   .venv/bin/gunicorn --bind 127.0.0.1:8080 \
                   --workers 1 --threads 4 'app:app'
    3. terminal B: .venv/bin/python scripts/prod_smoke.py
    4. Ctrl-C the gunicorn process when done.

Run against an HTTPS deploy to include Phase 7I cookie hardening checks:
    BASE=https://<your-app>.fly.dev EXPECT_SECURE_COOKIES=1 \
        .venv/bin/python scripts/prod_smoke.py

Expected PASS coverage: /healthz current phase, signup, htmx pantry add,
invite minting, anonymous invite preview, invited roommate signup, shared
pantry attribution, logout, remember-me login, and hardened cookie flags
when EXPECT_SECURE_COOKIES is enabled or BASE uses HTTPS.
"""
from __future__ import annotations

import http.cookiejar
import os
import re
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request


BASE = os.environ.get("BASE", "http://127.0.0.1:8080")
EXPECT_SECURE_COOKIES = (
    os.environ.get("EXPECT_SECURE_COOKIES", "").lower() in {"1", "true", "yes"}
    or urllib.parse.urlsplit(BASE).scheme == "https"
)
# Randomize email/name per run so the smoke test is idempotent against a
# persistent gunicorn DB. (Restarting gunicorn between runs is a pain;
# we'd rather pollute the smoke DB with N test users than couple the
# test to a clean-DB precondition.)
RUN_ID = secrets.token_hex(4)
SMOKE_EMAIL = f"smoke-{RUN_ID}@example.com"
SMOKE_NAME = f"Smoke {RUN_ID}"
ROOMMATE_EMAIL = f"roommate-{RUN_ID}@example.com"
COOKIE_JAR = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(COOKIE_JAR),
)


def _request(
        method: str,
        path: str,
        data: dict | None = None,
        extra_headers: dict | None = None,
        allow_redirect: bool = True,
) -> tuple[int, str, str]:
    """Returns (status, body, final_url)."""
    url = f"{BASE}{path}"
    body = None
    headers = {"User-Agent": "pantrypal-prod-smoke/1.0"}
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        if allow_redirect:
            resp = OPENER.open(req, timeout=10)
        else:
            # Disable auto-redirect for testing 302 targets
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def http_error_302(self, req, fp, code, msg, headers):
                    raise urllib.error.HTTPError(req.full_url, code, msg, headers, fp)
                http_error_301 = http_error_303 = http_error_307 = http_error_302
            no_redirect_opener = urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(COOKIE_JAR),
                NoRedirect,
            )
            resp = no_redirect_opener.open(req, timeout=10)
        return resp.status, resp.read().decode("utf-8", "replace"), resp.url
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), e.url


def _get_csrf(path: str) -> str:
    status, body, _ = _request("GET", path)
    if status != 200:
        raise SystemExit(f"GET {path} returned {status}, can't fetch CSRF")
    # Flask-WTF renders `<input id="csrf_token" name="csrf_token" type="hidden"
    # value="…">` — `name` and `value` aren't adjacent because of `type=`.
    # Match by id instead, which is stable across Flask-WTF versions.
    m = re.search(r'id="csrf_token"[^>]*value="([^"]+)"', body)
    if not m:
        raise SystemExit(f"no csrf_token field on {path}")
    return m.group(1)


def check(name: str, condition: bool, detail: str = "") -> None:
    marker = "PASS" if condition else "FAIL"
    print(f"  [{marker}] {name}" + (f"  -- {detail}" if detail and not condition else ""))
    if not condition:
        raise SystemExit(1)


def _latest_cookie(named: str) -> http.cookiejar.Cookie | None:
    cookies = [cookie for cookie in COOKIE_JAR if cookie.name == named]
    return cookies[-1] if cookies else None


def _missing_cookie_security_flags(cookie: http.cookiejar.Cookie) -> list[str]:
    rest = {
        key.lower(): value
        for key, value in getattr(cookie, "_rest", {}).items()
    }
    missing = []
    if not cookie.secure:
        missing.append("Secure")
    if "httponly" not in rest:
        missing.append("HttpOnly")
    if str(rest.get("samesite", "")).lower() != "lax":
        missing.append("SameSite=Lax")
    return missing


def _check_cookie_hardened(cookie_name: str) -> None:
    if not EXPECT_SECURE_COOKIES:
        print(
            f"  [SKIP] {cookie_name} cookie hardening "
            "(set EXPECT_SECURE_COOKIES=1 or use BASE=https://...)"
        )
        return

    cookie = _latest_cookie(cookie_name)
    check(f"{cookie_name} cookie present", cookie is not None)
    missing = _missing_cookie_security_flags(cookie)
    check(
        f"{cookie_name} cookie hardened",
        not missing,
        f"missing {', '.join(missing)}",
    )


def main() -> int:
    print("Phase 2C prod-shape smoke test")
    print(f"  target: {BASE}")
    print()

    # ----- healthz reports the current phase -----
    print("Healthz:")
    status, body, _ = _request("GET", "/healthz")
    check("status 200", status == 200, f"got {status}")
    check("phase == 7L", '"phase":"7L"' in body or '"phase": "7L"' in body, body)

    # ----- Phase 1A: signup -----
    print("\nSignup:")
    token = _get_csrf("/signup")
    status, body, final = _request(
        "POST", "/signup",
        data={
            "csrf_token": token,
            "email": SMOKE_EMAIL,
            "name": SMOKE_NAME,
            "password": "smokepass1",
            "confirm_password": "smokepass1",
        },
    )
    check("signup landed on /pantry", "/pantry" in final, final)
    _check_cookie_hardened("session")
    # Stable markers on the pantry page: the H1 + the household-share aside
    # ID (rendered as an empty card on first signup).
    check("pantry H1 visible", "Your pantry" in body, body[:300])
    check("household-share aside rendered", 'id="household-share"' in body, body[:300])

    # ----- Phase 1B + 2A: add a pantry item -----
    print("\nPantry add:")
    token = _get_csrf("/pantry")
    # POST /pantry (the add route) — not /pantry/add. See app.py.
    # quantity is a FloatField, not a free-text field — pass the unit
    # ("bottle") in the `unit` slot.
    status, body, _ = _request(
        "POST", "/pantry",
        data={
            "csrf_token": token,
            "name": "Olive Oil",
            "quantity": "1",
            "unit": "bottle",
        },
        extra_headers={"HX-Request": "true"},
    )
    check("status 200", status == 200, f"got {status}")
    check("item rendered", "Olive Oil" in body, body[:300])

    # ----- Phase 2B: mint an invite -----
    print("\nInvite mint:")
    token = _get_csrf("/pantry")
    status, body, _ = _request(
        "POST", "/household/invite",
        data={"csrf_token": token},
        extra_headers={"HX-Request": "true"},
    )
    check("status 200", status == 200, f"got {status}")
    invite_match = re.search(r"/join/([A-Za-z0-9_-]+)", body)
    check("invite URL present in response", invite_match is not None, body[:300])
    invite_token = invite_match.group(1) if invite_match else None
    print(f"    minted token: {invite_token}")

    # ----- Phase 2B: anonymous user can preview the invite landing page -----
    print("\nInvite landing (anonymous):")
    _request("GET", "/logout")
    # Wipe the cookie jar so we're truly anonymous (logout drops the session
    # cookie, but the remember-me cookie can survive — clear everything to
    # be safe).
    COOKIE_JAR.clear()
    status, body, _ = _request("GET", f"/join/{invite_token}")
    check("status 200", status == 200, f"got {status}")
    check("join page mentions household", "household" in body.lower(), body[:300])

    # ----- Phase 2B: second signup uses the invite -> joins household -----
    print("\nSignup with invite:")
    token = _get_csrf(f"/signup?invite={invite_token}")
    status, body, final = _request(
        "POST", f"/signup?invite={invite_token}",
        data={
            "csrf_token": token,
            "email": ROOMMATE_EMAIL,
            "name": f"Roommate {RUN_ID}",
            "password": "roompass1",
            "confirm_password": "roompass1",
        },
    )
    check("redirected to /pantry", "/pantry" in final, final)
    check("roommate sees Olive Oil (shared household)", "Olive Oil" in body, body[:500])
    check(f"roommate sees 'added by {SMOKE_NAME}'", SMOKE_NAME in body, body[:500])

    # ----- Phase 7I: login emits hardened remember-me cookies on HTTPS deploys -----
    print("\nRemember-me login:")
    token = _get_csrf("/pantry")
    status, _, final = _request(
        "POST", "/logout",
        data={"csrf_token": token},
    )
    check("logged out", "/login" in final, final)
    COOKIE_JAR.clear()

    token = _get_csrf("/login")
    status, body, final = _request(
        "POST", "/login",
        data={
            "csrf_token": token,
            "email": ROOMMATE_EMAIL,
            "password": "roompass1",
            "remember": "y",
        },
    )
    check("remember login landed on /pantry", "/pantry" in final, final)
    check("remember login sees pantry", "Your pantry" in body, body[:300])
    _check_cookie_hardened("session")
    _check_cookie_hardened("remember_token")

    print("\nAll prod-shape smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
