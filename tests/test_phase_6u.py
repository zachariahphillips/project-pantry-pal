"""
Phase 6U regression suite — one-shot shopping helper strip.

Small copy-polish chunk from `PLANS/ux-improvements-plan.md` §4.2.
The "Tap the checkbox as you shop..." nudge is valuable first-run help,
but it duplicates the shopping heading on repeat visits. 6U shows it on
the first qualifying render in a browser session, then retires it via a
session flag.

Tier-1 dev loop:

    pytest tests/test_phase_6u.py -q
"""
from __future__ import annotations

from app import SHOPPING_HELPER_SEEN_SESSION_KEY
from tests.conftest import Client, sign_up


def _body(resp) -> str:
    return resp.get_data(as_text=True)


def _add_shopping(c: Client, name: str = "tortillas"):
    return c.post("/shopping", htmx=True, data={
        "name": name,
        "quantity": "",
        "unit": "",
        "notes": "",
        "submit": "Add",
    })


def _login(c: Client, email: str, password: str = "testpass123"):
    return c.post("/login", follow_redirects=True, data={
        "email": email,
        "password": password,
        "submit": "Sign in",
    })


def test_first_qualifying_shopping_render_shows_helper(client: Client):
    sign_up(client, "helper-first@example.com", "Helper First")

    body = _body(_add_shopping(client, "tortillas"))

    assert 'id="nudge-crossoff"' in body
    assert "checkbox" in body
    assert "I&#39;m home" in body or "I'm home" in body


def test_first_qualifying_render_sets_seen_session_flag(client: Client):
    sign_up(client, "helper-flag@example.com", "Helper Flag")
    _add_shopping(client, "tortillas")

    with client._c.session_transaction() as sess:
        assert sess.get(SHOPPING_HELPER_SEEN_SESSION_KEY) is True


def test_second_qualifying_render_in_same_session_hides_helper(client: Client):
    sign_up(client, "helper-second@example.com", "Helper Second")
    _add_shopping(client, "tortillas")

    body = _body(client.get("/shopping"))

    assert 'id="nudge-crossoff"' not in body
    assert "tortillas" in body


def test_fresh_session_for_same_account_gets_helper_once(app, client: Client):
    email = "helper-fresh-session@example.com"
    password = "testpass123"
    sign_up(client, email, "Helper Fresh", password=password)
    _add_shopping(client, "tortillas")
    assert 'id="nudge-crossoff"' not in _body(client.get("/shopping"))

    fresh_client = Client(app.test_client())
    _login(fresh_client, email, password=password)

    first_fresh_body = _body(fresh_client.get("/shopping"))
    second_fresh_body = _body(fresh_client.get("/shopping"))

    assert 'id="nudge-crossoff"' in first_fresh_body
    assert 'id="nudge-crossoff"' not in second_fresh_body
