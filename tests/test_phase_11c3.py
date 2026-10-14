"""
Phase 11C.3 regression suite — local shopping-category defaults.

Known grocery names receive exact-match aisle defaults through every route
that creates a ShoppingItem. Unknown names remain uncategorized; this phase
does not make an AI/network request during ordinary list entry.

Tier-1 dev loop:

    pytest tests/test_phase_11c3.py -q
"""
from __future__ import annotations

import json

import pytest

from app import _default_shopping_category
from extensions import db
from models import MealPlan, ShoppingItem, User
from tests.conftest import Client, id_for, sign_up


@pytest.mark.parametrize(
    ("raw_name", "category"),
    [
        ("  APPLES  ", "Produce"),
        ("Milk", "Dairy & Eggs"),
        ("chicken breast", "Meat & Seafood"),
        ("Tortillas", "Bakery"),
        ("Olive oil", "Pantry"),
        ("frozen peas", "Frozen"),
        ("Coffee", "Beverages"),
        ("Paper towels", "Household"),
        ("Almond milk", None),
        ("Specialty spice blend", None),
    ],
)
def test_exact_local_category_defaults(raw_name, category):
    assert _default_shopping_category(raw_name) == category


def _add_pantry(client: Client, name: str) -> str:
    response = client.post("/pantry", htmx=True, data={
        "name": name,
        "quantity": "",
        "unit": "",
        "notes": "",
        "expiry_date": "",
    })
    assert response.status_code in (200, 204)
    item_id = id_for(
        client.get("/pantry").get_data(as_text=True),
        name,
        "pantry-item",
    )
    assert item_id is not None
    return item_id


class TestCategoryDefaultsAcrossShoppingCreationPaths:
    def test_manual_add_categorizes_known_names_and_leaves_unknown_names(
        self, client, app,
    ):
        sign_up(client, "manual@example.com", "Manual")
        for name in ("Milk", "Specialty spice blend"):
            response = client.post("/shopping", htmx=True, data={
                "name": name,
                "quantity": "",
                "unit": "",
                "notes": "",
            })
            assert response.status_code == 200

        with app.app_context():
            categories = {
                item.name: item.category
                for item in ShoppingItem.query.all()
            }
        assert categories == {
            "Milk": "Dairy & Eggs",
            "Specialty spice blend": None,
        }

    def test_pantry_copy_uses_the_same_category_default(self, client, app):
        sign_up(client, "pantry@example.com", "Pantry")
        item_id = _add_pantry(client, "Avocados")

        response = client.post(
            f"/pantry/{item_id}/add-to-shopping", htmx=True,
        )
        assert response.status_code == 200

        with app.app_context():
            copied = ShoppingItem.query.filter_by(name="Avocados").one()
            assert copied.category == "Produce"

    def test_meal_plan_single_and_bulk_adds_apply_defaults(
        self, client, app,
    ):
        sign_up(client, "meal@example.com", "Meal")
        with app.app_context():
            user = User.query.filter_by(email="meal@example.com").one()
            plan = MealPlan(
                household_id=user.household_id,
                created_by_user_id=user.id,
                prompt="Dinner",
                response_json=json.dumps({
                    "meal_name": "Dinner",
                    "have": [],
                    "need": ["Chicken breast", "Mystery condiment"],
                    "steps": ["Cook."],
                }),
                meal_name="Dinner",
            )
            db.session.add(plan)
            db.session.commit()
            plan_id = plan.id

        response = client.post(
            f"/meal-plan/{plan_id}/need-to-shopping",
            htmx=True,
            data={"name": "Chicken breast"},
        )
        assert response.status_code == 200
        response = client.post(
            f"/meal-plan/{plan_id}/need-all-to-shopping", htmx=True,
        )
        assert response.status_code == 200

        with app.app_context():
            categories_by_name = {
                name: {
                    item.category
                    for item in ShoppingItem.query.filter_by(name=name).all()
                }
                for name in ("Chicken breast", "Mystery condiment")
            }
        assert categories_by_name == {
            "Chicken breast": {"Meat & Seafood"},
            "Mystery condiment": {None},
        }
