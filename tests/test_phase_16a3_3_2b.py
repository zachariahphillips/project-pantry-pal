"""
Phase 16A.3.3.2b regression suite — source meals for weekly quantity totals.

The expanded source list is an audit trail for one displayed subtotal. It
uses only scheduled household plans with validated details and links to the
existing meal card; it does not change Shopping.

Tier-1 dev loop:

    pytest tests/test_phase_16a3_3_2a.py \
        tests/test_phase_16a3_3_2b.py -q
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from html import unescape

from extensions import db
from models import MealPlan, User
from tests.conftest import sign_up


def _create_plan(
    app,
    email: str,
    meal_name: str,
    *,
    quantity: float | None,
    unit: str = "cup",
    planned_for: date,
) -> int:
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        response = {
            "meal_name": meal_name,
            "have": [],
            "need": ["Milk"],
            "steps": ["Cook it."],
        }
        if quantity is not None:
            response["need_details"] = [
                {"name": "Milk", "quantity": quantity, "unit": unit},
            ]
        plan = MealPlan(
            household_id=user.household_id,
            created_by_user_id=user.id,
            prompt="Dinner",
            response_json=json.dumps(response),
            meal_name=meal_name,
            planned_for=planned_for,
        )
        db.session.add(plan)
        db.session.commit()
        return plan.id


def _gap_item(html: str, name: str) -> str:
    value_index = html.index(f'value="{name}"')
    start = html.rfind("<li", 0, value_index)
    first_closing_tag = html.index("</li>", value_index)
    details_start = html.find("<details data-weekly-quantity-sources", value_index)
    if details_start != -1 and details_start < first_closing_tag:
        details_end = html.index("</details>", start) + len("</details>")
        return html[start:details_end]
    return html[start:first_closing_tag]


def _visible_text(markup: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", markup)).split())


class TestWeeklyQuantitySourceMeals:
    def test_known_total_lists_each_scheduled_meal_and_amount(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        today = date.today()
        first_id = _create_plan(
            app, "alice@example.com", "Monday chowder",
            quantity=1,
            planned_for=today,
        )
        second_id = _create_plan(
            app, "alice@example.com", "Tuesday pasta",
            quantity=0.5,
            planned_for=today + timedelta(days=1),
        )
        third_id = _create_plan(
            app, "alice@example.com", "Wednesday salad",
            quantity=3,
            unit="tbsp",
            planned_for=today + timedelta(days=2),
        )
        _create_plan(
            app, "alice@example.com", "Legacy dinner",
            quantity=None,
            planned_for=today + timedelta(days=3),
        )

        html = client.get("/meals").get_data(as_text=True)
        milk = _gap_item(html, "Milk")
        milk_text = _visible_text(milk)

        assert "See 3 contributing meals" in milk_text
        assert "1.5 cup subtotal · 2 meals" in milk_text
        assert "3 tbsp subtotal · 1 meal" in milk_text
        assert "Today · Monday chowder" in milk_text
        assert (
            f"{(today + timedelta(days=1)).strftime('%b %-d')} · Tuesday pasta"
            in milk_text
        )
        assert (
            f"{(today + timedelta(days=2)).strftime('%b %-d')} · Wednesday salad"
            in milk_text
        )
        assert "1 cup" in milk_text
        assert "0.5 cup" in milk_text
        assert "3 tbsp" in milk_text
        assert f'href="/meals?open={first_id}#meal-plan-{first_id}"' in milk
        assert f'href="/meals?open={second_id}#meal-plan-{second_id}"' in milk
        assert f'href="/meals?open={third_id}#meal-plan-{third_id}"' in milk
        assert "Legacy dinner" not in milk_text

    def test_detail_free_gap_has_no_source_disclosure(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _create_plan(
            app, "alice@example.com", "Legacy dinner",
            quantity=None,
            planned_for=date.today(),
        )

        html = client.get("/meals").get_data(as_text=True)

        assert "data-weekly-quantity-sources" not in _gap_item(html, "Milk")
