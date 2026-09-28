"""
Phase 10C regression suite — swipe-to-delete on pantry rows.

The gesture is an additive mobile shortcut: it calls the existing pantry
DELETE route, while the visible Delete control remains available for keyboard
and assistive-technology users. The route continues to own undo-toast and
onboarding-boundary behavior.

Tier-1 dev loop:

    pytest tests/test_phase_10c.py -q
"""
from __future__ import annotations

import re

from tests.conftest import Client, sign_up


def _add_pantry(client: Client, name: str) -> None:
    response = client.post("/pantry", htmx=True, data={
        "name": name, "quantity": "", "unit": "", "notes": "",
    })
    assert response.status_code in (200, 204)


def _first_pantry_id(html: str) -> int:
    match = re.search(r'id="pantry-item-(\d+)"', html)
    assert match, "Expected a pantry item in the rendered page"
    return int(match.group(1))


def _pantry_item_block(html: str, item_id: int) -> str:
    match = re.search(
        rf'id="pantry-item-{item_id}"(.*?)(?=id="pantry-item-|\Z)',
        html,
        re.DOTALL,
    )
    assert match, f"Could not locate pantry item {item_id}"
    return match.group(0)


class TestPantrySwipeRow:
    def test_row_exposes_swipe_structure_and_delete_route(self, client):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Olive oil")
        page = client.get("/pantry").get_data(as_text=True)
        item_id = _first_pantry_id(page)
        block = _pantry_item_block(page, item_id)

        assert "data-pantry-swipe-row" in block
        assert "relative" in block
        assert "overflow-hidden" in block
        assert "data-pantry-swipe-affordance" in block
        assert 'aria-hidden="true"' in block
        assert "data-pantry-swipe-content" in block
        assert f'data-pantry-delete-url="/pantry/{item_id}"' in block

    def test_visible_actions_remain_available(self, client):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Olive oil")
        page = client.get("/pantry").get_data(as_text=True)
        item_id = _first_pantry_id(page)
        block = _pantry_item_block(page, item_id)

        assert f"/pantry/{item_id}/add-to-shopping" in block
        assert f"/pantry/{item_id}/edit" in block
        assert f'hx-delete="/pantry/{item_id}"' in block

    def test_edit_response_is_swipe_free(self, client):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Olive oil")
        item_id = _first_pantry_id(client.get("/pantry").get_data(as_text=True))

        edit_html = client.get(
            f"/pantry/{item_id}/edit", htmx=True,
        ).get_data(as_text=True)
        assert "data-pantry-swipe-row" not in edit_html
        assert "data-pantry-swipe-content" not in edit_html

    def test_delete_route_still_removes_item(self, client):
        sign_up(client, "alice@example.com", "Alice")
        # Keep the post-delete count above the three-item onboarding gate so
        # the route returns the #pantry-list partial instead of HX-Refresh.
        for name in ("Olive oil", "Rice", "Salt", "Garlic", "Onion"):
            _add_pantry(client, name)
        page = client.get("/pantry").get_data(as_text=True)
        item_id = _first_pantry_id(page)

        response = client.delete(f"/pantry/{item_id}", htmx=True)
        assert response.status_code == 200
        assert f'id="pantry-item-{item_id}"' not in response.get_data(
            as_text=True,
        )


class TestPantrySwipeScript:
    def test_script_is_scoped_to_pantry_and_targets_pantry_list(self, client):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Olive oil")

        pantry = client.get("/pantry").get_data(as_text=True)
        assert "initPantrySwipe" in pantry
        for constant in ("SWIPE_THRESHOLD", "MAX_SWIPE", "SCROLL_LOCK_DELTA"):
            assert constant in pantry
        assert re.search(
            r"htmx\.ajax\([^)]*['\"]#pantry-list['\"]",
            pantry,
            re.DOTALL,
        )

        shopping = client.get("/shopping").get_data(as_text=True)
        assert "initPantrySwipe" not in shopping
