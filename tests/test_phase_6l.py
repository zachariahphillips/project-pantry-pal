"""
Phase 6L regression suite — quiet row Delete buttons.

Small visual-polish chunk from `PLANS/ux-improvements-plan.md` §2.2.
Before 6L, every visible row Delete action used `text-red-700` at rest,
so destructive actions competed with frequent actions like + Shop and
Edit. 6L keeps Delete discoverable but neutral at rest, then turns it red
on hover/focus when the user has shown intent.

Tier-1 dev loop:

    pytest tests/test_phase_6l.py -q
"""
from __future__ import annotations

import re

from tests.conftest import Client, sign_up


def _body(resp) -> str:
    return resp.get_data(as_text=True)


def _add_pantry(c: Client, name: str = "Olive oil"):
    return c.post("/pantry", htmx=True, data={
        "name": name, "quantity": "", "unit": "", "notes": "",
        "submit": "Add",
    })


def _add_shopping(c: Client, name: str = "Milk"):
    return c.post("/shopping", htmx=True, data={
        "name": name, "quantity": "", "unit": "", "notes": "",
        "submit": "Add",
    })


def _delete_button_tag(html: str, surface: str) -> str:
    """Extract the visible row Delete button for pantry/shopping rows."""
    match = re.search(
        rf'(<button[^>]*hx-delete="/{surface}/\d+"[^>]*>)\s*Delete',
        html,
        re.DOTALL,
    )
    assert match, f"{surface} Delete button not found"
    return match.group(1)


def _class_without_intent_variants(tag: str) -> str:
    """Strip hover/focus red variants before checking the rest state."""
    return (
        tag
        .replace("hover:text-red-700", "")
        .replace("focus:text-red-700", "")
        .replace("focus:ring-red-300", "")
        .replace("hover:bg-red-50", "")
    )


def _assert_quiet_delete_button(tag: str) -> None:
    assert "text-stone-500" in tag
    assert "hover:text-red-700" in tag
    assert "focus:text-red-700" in tag
    assert "hover:bg-red-50" in tag
    assert "focus:ring-red-300" in tag
    assert "text-red-700" not in _class_without_intent_variants(tag)


def test_pantry_delete_button_is_neutral_at_rest(client: Client):
    sign_up(client, "pantrydelete@example.com", "Pantry Delete")
    _add_pantry(client, "Olive oil")

    tag = _delete_button_tag(_body(client.get("/pantry")), "pantry")

    _assert_quiet_delete_button(tag)


def test_shopping_delete_button_is_neutral_at_rest(client: Client):
    sign_up(client, "shoppingdelete@example.com", "Shopping Delete")
    _add_shopping(client, "Milk")

    tag = _delete_button_tag(_body(client.get("/shopping")), "shopping")

    _assert_quiet_delete_button(tag)


def test_shopping_swipe_affordance_stays_red(client: Client):
    """Only the always-visible Delete text quiets down; swipe reveal stays red."""
    sign_up(client, "swipeaffordance@example.com", "Swipe")
    _add_shopping(client, "Milk")

    html = _body(client.get("/shopping"))
    match = re.search(
        r'(<div[^>]*data-swipe-affordance[^>]*>)',
        html,
    )
    assert match, "shopping swipe affordance layer missing"
    assert "bg-red-600" in match.group(1)
