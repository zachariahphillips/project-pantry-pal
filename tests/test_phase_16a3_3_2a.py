"""
Phase 16A.3.3.2a regression suite — read-only weekly quantity subtotals.

Totals aggregate only identical canonical units. Different units are shown as
separate known amounts, and a legacy or detail-free plan makes coverage
explicit rather than causing PantryPal to invent a quantity.

Tier-1 dev loop:

    pytest tests/test_phase_16a1.py tests/test_phase_16a3_3_1.py \
        tests/test_phase_16a3_3_2a.py -q
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from extensions import db
from models import MealPlan, ShoppingItem, User
from tests.conftest import sign_up


def _create_plan(
    app,
    email: str,
    *,
    need: list[str],
    need_details: list[dict] | None,
    planned_for: date,
) -> None:
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        response = {
            "meal_name": "Test dinner",
            "have": [],
            "need": need,
            "steps": ["Cook it."],
        }
        if need_details is not None:
            response["need_details"] = need_details
        db.session.add(MealPlan(
            household_id=user.household_id,
            created_by_user_id=user.id,
            prompt="Dinner",
            response_json=json.dumps(response),
            meal_name="Test dinner",
            planned_for=planned_for,
        ))
        db.session.commit()


def _gap_item(html: str, name: str) -> str:
    value_index = html.index(f'value="{name}"')
    start = html.rfind("<li", 0, value_index)
    return html[start:html.index("</li>", value_index)]


class TestWeeklyQuantityTotals:
    def test_same_units_sum_and_different_units_stay_separate(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        today = date.today()
        _create_plan(
            app, "alice@example.com",
            need=["Milk"],
            need_details=[{"name": "Milk", "quantity": 1, "unit": "cup"}],
            planned_for=today,
        )
        _create_plan(
            app, "alice@example.com",
            need=["Milk"],
            need_details=[{"name": "Milk", "quantity": 0.5, "unit": "cup"}],
            planned_for=today + timedelta(days=1),
        )
        _create_plan(
            app, "alice@example.com",
            need=["Milk"],
            need_details=[{"name": "Milk", "quantity": 250, "unit": "ml"}],
            planned_for=today + timedelta(days=2),
        )
        # A legacy plan still contributes an ingredient gap but cannot make
        # the visible amount look complete.
        _create_plan(
            app, "alice@example.com",
            need=["Milk"],
            need_details=None,
            planned_for=today + timedelta(days=3),
        )

        html = client.get("/meals").get_data(as_text=True)
        milk = " ".join(_gap_item(html, "Milk").split())

        assert "Known totals stay grouped by unit" in html
        assert "Known totals (recorded for 3 of 4 meals):" in milk
        assert "1.5 cup for 2 meals" in milk
        assert "250 ml for 1 meal" in milk
        with app.app_context():
            assert ShoppingItem.query.count() == 0

    def test_detail_free_gaps_do_not_claim_a_quantity_total(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _create_plan(
            app, "alice@example.com",
            need=["Milk"],
            need_details=None,
            planned_for=date.today(),
        )

        html = client.get("/meals").get_data(as_text=True)

        assert "Known totals stay grouped by unit" not in html
        assert "Known totals" not in _gap_item(html, "Milk")
