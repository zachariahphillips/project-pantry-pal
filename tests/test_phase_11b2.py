"""
Phase 11B.2 regression suite — pantry-row manual restock toggle.

The one-tap marker is independent from the existing quantity-derived "Low"
badge. It makes an item's deliberate restock state obvious, works without
opening Edit, and remains household-scoped.

Tier-1 dev loop:

    pytest tests/test_phase_11b2.py -q
"""
from __future__ import annotations

import re

from tests.conftest import Client, id_for, sign_up


def _add_pantry(client: Client, name: str, quantity: str = "") -> None:
    response = client.post("/pantry", htmx=True, data={
        "name": name,
        "quantity": quantity,
        "unit": "",
        "notes": "",
        "expiry_date": "",
    })
    assert response.status_code in (200, 204)


def _item_block(html: str, item_id: str) -> str:
    match = re.search(
        rf'id="pantry-item-{item_id}".*?(?=id="pantry-item-\d+"|\Z)',
        html,
        re.DOTALL,
    )
    assert match, f"Could not find pantry item {item_id}."
    return match.group(0)


class TestPantryRestockToggle:
    def test_unflagged_item_has_an_accessible_restock_toggle(self, client):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Olive oil")
        html = client.get("/pantry").get_data(as_text=True)
        item_id = id_for(html, "Olive oil", "pantry-item")
        assert item_id is not None

        block = _item_block(html, item_id)
        assert f'hx-post="/pantry/{item_id}/low-stock"' in block
        assert 'aria-label="Mark Olive oil for restock"' in block
        assert 'hx-disabled-elt="this"' in block
        assert ">Restock<" not in block

    def test_toggle_marks_and_clears_the_manual_restock_state(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Olive oil")
        html = client.get("/pantry").get_data(as_text=True)
        item_id = id_for(html, "Olive oil", "pantry-item")
        assert item_id is not None

        response = client.post(
            f"/pantry/{item_id}/low-stock", htmx=True,
        )
        assert response.status_code == 200
        marked = response.get_data(as_text=True)
        assert f'id="pantry-item-{item_id}"' in marked
        assert 'aria-label="Mark Olive oil as stocked"' in marked
        assert ">Restock<" in marked

        with app.app_context():
            from models import PantryItem

            assert (
                PantryItem.query.filter_by(name="Olive oil").one().low_stock
                is True
            )

        response = client.post(
            f"/pantry/{item_id}/low-stock", htmx=True,
        )
        cleared = response.get_data(as_text=True)
        assert 'aria-label="Mark Olive oil for restock"' in cleared
        assert ">Restock<" not in cleared

    def test_manual_restock_marker_does_not_change_quantity_low_status(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Rice", quantity="1")
        html = client.get("/pantry").get_data(as_text=True)
        item_id = id_for(html, "Rice", "pantry-item")
        assert item_id is not None

        response = client.post(
            f"/pantry/{item_id}/low-stock", htmx=True,
        )
        marked = response.get_data(as_text=True)
        assert ">Low<" in marked
        assert ">Restock<" in marked

        with app.app_context():
            from models import PantryItem

            item = PantryItem.query.filter_by(name="Rice").one()
            assert item.quantity == 1
            assert item.low_stock is True

        response = client.post(
            f"/pantry/{item_id}/low-stock", htmx=True,
        )
        cleared = response.get_data(as_text=True)
        assert ">Low<" in cleared
        assert ">Restock<" not in cleared

    def test_delete_undo_preserves_the_manual_restock_marker(
        self, client, app,
    ):
        sign_up(client, "undo@example.com", "Undo")
        for name in ("Olive oil", "Rice", "Salt", "Garlic", "Onion"):
            _add_pantry(client, name)
        html = client.get("/pantry").get_data(as_text=True)
        item_id = id_for(html, "Olive oil", "pantry-item")
        assert item_id is not None

        client.post(f"/pantry/{item_id}/low-stock", htmx=True)
        response = client.delete(f"/pantry/{item_id}")
        assert response.status_code == 200
        response = client.post("/pantry/undo", htmx=True)
        assert response.status_code == 200

        with app.app_context():
            from models import PantryItem

            restored = PantryItem.query.filter_by(name="Olive oil").one()
            assert restored.low_stock is True

    def test_another_household_cannot_toggle_the_item(self, two_clients):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        _add_pantry(alice, "Olive oil")
        item_id = id_for(
            alice.get("/pantry").get_data(as_text=True),
            "Olive oil",
            "pantry-item",
        )
        assert item_id is not None
        sign_up(bob, "bob@example.com", "Bob")

        response = bob.post(f"/pantry/{item_id}/low-stock", htmx=True)

        assert response.status_code == 404
