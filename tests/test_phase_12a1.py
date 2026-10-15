"""
Phase 12A.1 regression suite — cooked-meal deduction preview.

The preview shows a plan's current pantry matches without calling AI or
writing any pantry changes. It is the safe review step before later phases
propose and apply quantity deductions.

Tier-1 dev loop:

    pytest tests/test_phase_12a1.py -q
"""
from __future__ import annotations

import json

from extensions import db
from models import MealPlan, PantryItem, User
from tests.conftest import Client, sign_up


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


def _create_plan(app, email: str, *, have: list[str]) -> int:
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        plan = MealPlan(
            household_id=user.household_id,
            created_by_user_id=user.id,
            prompt="Dinner",
            response_json=json.dumps({
                "meal_name": "Test dinner",
                "have": have,
                "need": [],
                "steps": ["Cook it."],
            }),
            meal_name="Test dinner",
        )
        db.session.add(plan)
        db.session.commit()
        return plan.id


class TestCookedMealPreview:
    def test_cards_with_pantry_ingredients_offer_a_cooked_preview(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        plan_id = _create_plan(app, "alice@example.com", have=["Eggs"])

        html = client.get("/meals").get_data(as_text=True)

        assert "Cooked it" in html
        assert f'hx-post="/meal-plan/{plan_id}/cook-preview"' in html
        assert f'id="meal-plan-cook-preview-{plan_id}"' in html

    def test_preview_uses_current_pantry_and_never_mutates_it(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Eggs", quantity="6", unit="ea")
        _add_pantry(client, "Pasta")
        plan_id = _create_plan(
            app,
            "alice@example.com",
            have=["Eggs", "Milk", "Eggs"],
        )

        response = client.post(
            f"/meal-plan/{plan_id}/cook-preview", htmx=True,
        )

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Review pantry changes" in html
        assert "No pantry changes have been made." in html
        assert "Eggs" in html
        assert "6 ea" in html
        assert "Not currently in your pantry:" in html
        assert "Milk" in html
        assert html.count("Milk") == 1

        with app.app_context():
            eggs = PantryItem.query.filter_by(name="Eggs").one()
            assert eggs.quantity == 6
            assert eggs.unit == "ea"
            assert PantryItem.query.count() == 2

    def test_card_hides_the_action_when_a_plan_has_no_pantry_items(
        self, client, app,
    ):
        sign_up(client, "empty@example.com", "Empty")
        _create_plan(app, "empty@example.com", have=[])

        html = client.get("/meals").get_data(as_text=True)

        assert "meal-plan-cook-preview-" not in html
        assert "Cooked it" not in html

    def test_another_household_cannot_open_a_preview(
        self, two_clients, app,
    ):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        plan_id = _create_plan(app, "alice@example.com", have=["Eggs"])
        sign_up(bob, "bob@example.com", "Bob")

        response = bob.post(
            f"/meal-plan/{plan_id}/cook-preview", htmx=True,
        )

        assert response.status_code == 404
