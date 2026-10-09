"""
Phase 11B.3 regression suite — restock-to-shopping handoff.

Flagging an item offers an immediate, explicit "Add to shopping" action. The
handoff is intentionally ephemeral: manually flagged rows remain compact on
later visits, while the normal +Shop control stays available.

Tier-1 dev loop:

    pytest tests/test_phase_11b3.py -q
"""
from __future__ import annotations

from tests.conftest import Client, id_for, sign_up


def _add_pantry(
    client: Client, name: str, *, quantity: str = "", unit: str = "",
) -> None:
    response = client.post("/pantry", htmx=True, data={
        "name": name,
        "quantity": quantity,
        "unit": unit,
        "notes": "",
        "expiry_date": "",
    })
    assert response.status_code in (200, 204)


def _flag_for_restock(client: Client, item_id: str) -> str:
    response = client.post(f"/pantry/{item_id}/low-stock", htmx=True)
    assert response.status_code == 200
    return response.get_data(as_text=True)


class TestRestockShoppingHandoff:
    def test_flagging_an_item_offers_an_explicit_shopping_handoff(
        self, client,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Olive oil")
        item_id = id_for(
            client.get("/pantry").get_data(as_text=True),
            "Olive oil",
            "pantry-item",
        )
        assert item_id is not None

        html = _flag_for_restock(client, item_id)

        assert "data-restock-shopping-prompt" in html
        assert "Restock" in html and "Olive oil" in html
        assert "Add to shopping" in html
        assert (
            f'hx-post="/pantry/{item_id}/add-to-shopping"' in html
        )
        assert 'aria-label="Add Olive oil to shopping list"' in html
        assert "hx-disabled-elt=\"this\"" in html
        assert "this.closest('[data-restock-shopping-prompt]').remove()" in html

    def test_handoff_prompt_is_only_shown_when_the_item_is_newly_flagged(
        self, client,
    ):
        sign_up(client, "compact@example.com", "Compact")
        _add_pantry(client, "Olive oil")
        item_id = id_for(
            client.get("/pantry").get_data(as_text=True),
            "Olive oil",
            "pantry-item",
        )
        assert item_id is not None

        _flag_for_restock(client, item_id)
        later_page = client.get("/pantry").get_data(as_text=True)
        assert ">Restock<" in later_page
        assert "data-restock-shopping-prompt" not in later_page

        cleared = _flag_for_restock(client, item_id)
        assert ">Restock<" not in cleared
        assert "data-restock-shopping-prompt" not in cleared

    def test_handoff_uses_existing_pantry_to_shopping_behavior(
        self, client, app,
    ):
        sign_up(client, "handoff@example.com", "Handoff")
        _add_pantry(client, "Olive oil", quantity="1", unit="bottle")
        item_id = id_for(
            client.get("/pantry").get_data(as_text=True),
            "Olive oil",
            "pantry-item",
        )
        assert item_id is not None
        _flag_for_restock(client, item_id)

        response = client.post(
            f"/pantry/{item_id}/add-to-shopping", htmx=True,
        )
        assert response.status_code == 200
        assert response.headers.get("HX-Trigger") == "shopping:added"

        with app.app_context():
            from models import PantryItem, ShoppingItem

            shopping_item = ShoppingItem.query.filter_by(
                name="Olive oil",
            ).one()
            assert shopping_item.quantity == 1
            assert shopping_item.unit == "bottle"
            assert PantryItem.query.filter_by(
                name="Olive oil",
            ).one().low_stock is True
