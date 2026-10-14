"""
Phase 11C.2 regression suite — shopping-list aisle grouping.

Unchecked items group under alphabetical category headers once at least one
category is available. The Other group holds uncategorized items, while
checked-off items retain their established global section at the bottom.

Tier-1 dev loop:

    pytest tests/test_phase_11c2.py -q
"""
from __future__ import annotations

from types import SimpleNamespace

from app import _group_shopping_items
from extensions import db
from models import ShoppingItem
from tests.conftest import Client, id_for, sign_up


def _add_shopping(client: Client, name: str) -> str:
    response = client.post("/shopping", htmx=True, data={
        "name": name,
        "quantity": "",
        "unit": "",
        "notes": "",
    })
    assert response.status_code in (200, 204)
    item_id = id_for(
        client.get("/shopping").get_data(as_text=True),
        name,
        "shopping-item",
    )
    assert item_id is not None
    return item_id


def _set_category(app, item_id: str, category: str | None) -> None:
    with app.app_context():
        item = db.session.get(ShoppingItem, int(item_id))
        item.category = category
        db.session.commit()


class TestShoppingCategoryGroups:
    def test_group_helper_sorts_aisles_and_keeps_item_order(self):
        dairy = SimpleNamespace(name="Milk", category="Dairy")
        produce = SimpleNamespace(name="Apples", category="Produce")
        pasta = SimpleNamespace(name="Pasta", category="Pantry")
        other = SimpleNamespace(name="Batteries", category=None)
        blank = SimpleNamespace(name="Napkins", category="   ")

        groups = _group_shopping_items([
            produce, other, dairy, pasta, blank,
        ])

        assert [label for label, _ in groups] == [
            "Dairy", "Pantry", "Produce", "Other",
        ]
        assert [item.name for item in groups[-1][1]] == [
            "Batteries", "Napkins",
        ]

    def test_categorized_unchecked_items_render_in_aisle_groups(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        milk_id = _add_shopping(client, "Milk")
        pasta_id = _add_shopping(client, "Pasta")
        apples_id = _add_shopping(client, "Apples")
        gift_wrap_id = _add_shopping(client, "Gift wrap")
        _set_category(app, milk_id, "Dairy")
        _set_category(app, pasta_id, "Pantry")
        _set_category(app, apples_id, "Produce")

        html = client.get("/shopping").get_data(as_text=True)

        dairy = html.index('data-shopping-category-group="Dairy"')
        pantry = html.index('data-shopping-category-group="Pantry"')
        produce = html.index('data-shopping-category-group="Produce"')
        other = html.index('data-shopping-category-group="Other"')
        assert dairy < pantry < produce < other
        assert dairy < html.index(f'id="shopping-item-{milk_id}"') < pantry
        assert pantry < html.index(f'id="shopping-item-{pasta_id}"') < produce
        assert produce < html.index(f'id="shopping-item-{apples_id}"') < other
        assert other < html.index(f'id="shopping-item-{gift_wrap_id}"')

    def test_uncategorized_list_stays_flat_until_an_aisle_exists(
        self, client,
    ):
        sign_up(client, "flat@example.com", "Flat")
        _add_shopping(client, "Gift wrap")
        _add_shopping(client, "Unusual spice blend")

        html = client.get("/shopping").get_data(as_text=True)

        assert "data-shopping-category-group" not in html
        assert "shopping-category-" not in html

    def test_checked_items_remain_below_all_unchecked_aisle_groups(
        self, client, app,
    ):
        sign_up(client, "checked@example.com", "Checked")
        milk_id = _add_shopping(client, "Milk")
        apples_id = _add_shopping(client, "Apples")
        _set_category(app, milk_id, "Dairy")
        _set_category(app, apples_id, "Produce")
        response = client.post(f"/shopping/{milk_id}/toggle", htmx=True)
        assert response.status_code == 200

        html = response.get_data(as_text=True)

        assert 'data-shopping-category-group="Produce"' in html
        assert 'data-shopping-category-group="Dairy"' not in html
        assert (
            html.index(f'id="shopping-item-{apples_id}"')
            < html.index("Checked off (1)")
            < html.index(f'id="shopping-item-{milk_id}"')
        )
