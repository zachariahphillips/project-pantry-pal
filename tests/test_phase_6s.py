"""
Phase 6S regression suite — auto-dismiss non-error flash banners.

Small interaction-polish chunk from `PLANS/ux-improvements-plan.md` §3.4.
Success/info/warning flashes should confirm the action, then get out of
the way. Error flashes stay persistent because they may carry actionable
account or validation information.

Tier-1 dev loop:

    pytest tests/test_phase_6s.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.conftest import Client, sign_up


BASE_TEMPLATE = (
    Path(__file__).resolve().parents[1] / "templates" / "base.html"
)


def _body(resp) -> str:
    return resp.get_data(as_text=True)


def _flash_block(html: str, text: str) -> str:
    for match in re.finditer(
        r'(<div class="rounded-xl border[^>]*data-flash-message[\s\S]*?</div>)',
        html,
    ):
        if text in match.group(1):
            return match.group(1)
    raise AssertionError(f"flash containing {text!r} not found")


def _base_source() -> str:
    return BASE_TEMPLATE.read_text()


def test_success_flash_auto_dismisses(client: Client):
    body = sign_up(client, "flash-success@example.com", "Flash Success")

    block = _flash_block(body, "Welcome to PantryPal, Flash Success!")

    assert 'data-flash-category="success"' in block
    assert 'data-flash-auto-dismiss="true"' in block
    assert 'role="status"' in block
    assert "transition-opacity" in block
    assert "duration-300" in block


def test_error_flash_is_persistent(client: Client):
    resp = client.post("/login", data={
        "email": "missing@example.com",
        "password": "not-the-password",
        "submit": "Sign in",
    })

    block = _flash_block(_body(resp), "Invalid email or password.")

    assert 'data-flash-category="error"' in block
    assert 'data-flash-auto-dismiss="true"' not in block
    assert 'role="alert"' in block


def test_flash_auto_dismiss_timer_targets_only_opted_in_flashes():
    src = _base_source()

    assert 'querySelectorAll(\'[data-flash-auto-dismiss="true"]\')' in src
    assert "}, 4000);" in src
    assert "flash.classList.add('opacity-0');" in src
    assert "flash.setAttribute('aria-hidden', 'true');" in src
    assert "flash.remove()" in src


def test_danger_category_is_treated_like_error_for_persistence():
    src = _base_source()

    assert "{% set is_error = category in ['error', 'danger'] %}" in src
    assert "'danger':  'bg-red-50 border-red-200 text-red-900'" in src
