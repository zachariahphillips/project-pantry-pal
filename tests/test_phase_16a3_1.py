"""
Phase 16A.3.1 regression suite — active-shopping overlap warnings.

Warnings are informational only: they match case-insensitively against
unchecked rows in the current household and never block or mutate the
reviewed weekly-gap handoff.

Tier-1 dev loop:

    pytest tests/test_phase_16a1.py tests/test_phase_16a2.py \
        tests/test_phase_16a3_1.py -q
"""
from __future__ import annotations

import json
from datetime import date

from extensions import db
from models import MealPlan, ShoppingItem, User
from tests.conftest import sign_up


def _create_plan(app, email: str, *, need: list[str]) -> None:
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        db.session.add(MealPlan(
            household_id=user.household_id,
            created_by_user_id=user.id,
            prompt="Dinner",
            response_json=json.dumps({
                "meal_name": "Test dinner",
                "have": [],
                "need": need,
                "steps": ["Cook it."],
            }),
            meal_name="Test dinner",
            planned_for=date.today(),
        ))
        db.session.commit()


def _add_shopping(
    app,
    email: str,
    name: str,
    *,
    checked: bool,
) -> None:
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        db.session.add(ShoppingItem(
            household_id=user.household_id,
            added_by_user_id=user.id,
            name=name,
            checked=checked,
        ))
        db.session.commit()


def _gap_item(html: str, name: str) -> str:
    value_index = html.index(f'value="{name}"')
    start = html.rfind("<li", 0, value_index)
    return html[start:html.index("</li>", value_index)]


class TestWeeklyShoppingGapOverlapWarnings:
    def test_active_matching_item_has_an_informational_warning(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _create_plan(app, "alice@example.com", need=["Milk", "Chicken"])
        _add_shopping(app, "alice@example.com", "  milk  ", checked=False)
        _add_shopping(app, "alice@example.com", "Chicken", checked=True)

        html = client.get("/meals").get_data(as_text=True)

        milk = _gap_item(html, "Milk")
        chicken = _gap_item(html, "Chicken")
        assert "On shopping list" in milk
        assert "Add a separate shopping entry" in milk
        assert "On shopping list" not in chicken
        # The preview is display-only. Its GET cannot create another row.
        with app.app_context():
            assert ShoppingItem.query.count() == 2

    def test_another_households_active_item_does_not_warn(
        self, two_clients, app,
    ):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        _add_shopping(app, "alice@example.com", "Milk", checked=False)
        sign_up(bob, "bob@example.com", "Bob")
        _create_plan(app, "bob@example.com", need=["Milk"])

        html = bob.get("/meals").get_data(as_text=True)

        assert "On shopping list" not in _gap_item(html, "Milk")
