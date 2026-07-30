"""
Phase 6M regression suite — icon-only row actions.

Small visual-density chunk from `PLANS/ux-improvements-plan.md` §2.1.
Before 6M, pantry rows rendered three text actions (`+ Shop`, `Edit`,
`Delete`) and shopping rows rendered two (`Edit`, `Delete`). Those labels
ate horizontal space on mobile and truncated longer item names.

6M keeps the same routes and touch targets but swaps the visible labels
for icons. Accessibility stays explicit: pantry +Shop uses sr-only text
that can still flip to "Added", and Edit/Delete use aria-labels.

Tier-1 dev loop:

    pytest tests/test_phase_6m.py -q
"""
from __future__ import annotations

import re

from tests.conftest import Client, sign_up


def _body(resp) -> str:
    return resp.get_data(as_text=True)


def _add_pantry(c: Client, name: str = "Extra long pantry item name"):
    return c.post("/pantry", htmx=True, data={
        "name": name, "quantity": "", "unit": "", "notes": "",
        "submit": "Add",
    })


def _add_shopping(c: Client, name: str = "Extra long shopping item name"):
    return c.post("/shopping", htmx=True, data={
        "name": name, "quantity": "", "unit": "", "notes": "",
        "submit": "Add",
    })


def _button_block(html: str, attr_pattern: str) -> str:
    match = re.search(
        rf'(<button(?=[^>]*{attr_pattern})[^>]*>.*?</button>)',
        html,
        re.DOTALL,
    )
    assert match, f"button not found for {attr_pattern}"
    return match.group(1)


def _assert_icon_button(block: str) -> None:
    assert "h-10 w-10" in block
    assert "<svg" in block
    assert 'aria-hidden="true"' in block


def test_pantry_row_actions_are_icon_only_with_accessible_names(client: Client):
    sign_up(client, "pantryicons@example.com", "Pantry Icons")
    _add_pantry(client)

    html = _body(client.get("/pantry"))
    shop = _button_block(html, r'hx-post="/pantry/\d+/add-to-shopping"')
    edit = _button_block(html, r'hx-get="/pantry/\d+/edit"')
    delete = _button_block(html, r'hx-delete="/pantry/\d+"')

    _assert_icon_button(shop)
    assert 'class="sr-only shop-label"' in shop
    assert "+ Shop: add Extra long pantry item name to shopping list" in shop
    assert ">+ Shop<" not in shop

    _assert_icon_button(edit)
    assert 'aria-label="Edit Extra long pantry item name"' in edit
    assert ">Edit<" not in edit

    _assert_icon_button(delete)
    assert 'aria-label="Delete Extra long pantry item name"' in delete
    assert ">Delete<" not in delete


def test_shopping_row_actions_are_icon_only_with_accessible_names(
        client: Client):
    sign_up(client, "shoppingicons@example.com", "Shopping Icons")
    _add_shopping(client)

    html = _body(client.get("/shopping"))
    edit = _button_block(html, r'hx-get="/shopping/\d+/edit"')
    delete = _button_block(html, r'hx-delete="/shopping/\d+"')

    _assert_icon_button(edit)
    assert 'aria-label="Edit Extra long shopping item name"' in edit
    assert ">Edit<" not in edit

    _assert_icon_button(delete)
    assert 'aria-label="Delete Extra long shopping item name"' in delete
    assert ">Delete<" not in delete


def test_pantry_shop_feedback_restores_original_accessible_label(client: Client):
    """The temporary Added state should not erase the item-specific label."""
    sign_up(client, "shoplabel@example.com", "Shop Label")
    _add_pantry(client, "Olive oil")

    html = _body(client.get("/pantry"))
    shop = _button_block(html, r'hx-post="/pantry/\d+/add-to-shopping"')

    assert "const original = lbl.textContent;" in shop
    assert "lbl.textContent = original" in shop
    assert "lbl.textContent = '+ Shop'" not in shop
