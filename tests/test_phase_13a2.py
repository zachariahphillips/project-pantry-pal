"""
Phase 13A.2 regression suite — Pantry's Today meal shortcut.

The shortcut is scoped to plans explicitly scheduled for the current date. It
links into the established Meals view and opens just that card, avoiding a
parallel recipe/cooking surface on Pantry.

Tier-1 dev loop:

    pytest tests/test_phase_13a1.py tests/test_phase_13a2.py -q
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from extensions import db
from models import MealPlan, User
from tests.conftest import sign_up


def _create_plan(
    app, email: str, name: str, *, planned_for: date | None = None,
) -> int:
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        plan = MealPlan(
            household_id=user.household_id,
            created_by_user_id=user.id,
            prompt="Dinner",
            response_json=json.dumps({
                "meal_name": name,
                "have": [],
                "need": [],
                "steps": ["Cook it."],
            }),
            meal_name=name,
            planned_for=planned_for,
        )
        db.session.add(plan)
        db.session.commit()
        return plan.id


class TestTodaysMealShortcut:
    def test_no_shortcut_renders_without_a_meal_scheduled_for_today(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _create_plan(
            app, "alice@example.com", "Tomorrow dinner",
            planned_for=date.today() + timedelta(days=1),
        )

        html = client.get("/pantry").get_data(as_text=True)

        assert 'id="todays-meal-shortcut"' not in html

    def test_today_plan_appears_on_pantry_and_opens_its_meals_card(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        plan_id = _create_plan(
            app, "alice@example.com", "Tonight's pasta",
            planned_for=date.today(),
        )

        pantry_html = client.get("/pantry").get_data(as_text=True)

        assert 'id="todays-meal-shortcut"' in pantry_html
        assert "Today’s meal" in pantry_html
        assert "Tonight&#39;s pasta" in pantry_html
        assert f'id="todays-meal-plan-{plan_id}"' in pantry_html
        assert (
            f'href="/meals?open={plan_id}#meal-plan-{plan_id}"'
            in pantry_html
        )
        assert "View recipe" in pantry_html

        meals_html = client.get(
            f"/meals?open={plan_id}",
        ).get_data(as_text=True)
        card_start = meals_html.index(f'id="meal-plan-{plan_id}"')
        card_html = meals_html[card_start:]
        assert "<details open" in card_html
        assert "Cook again →" in card_html
        assert "Plan another meal" not in card_html

    def test_multiple_meals_scheduled_for_today_are_all_visible(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        first_id = _create_plan(
            app, "alice@example.com", "Lunch soup", planned_for=date.today(),
        )
        second_id = _create_plan(
            app, "alice@example.com", "Dinner tacos", planned_for=date.today(),
        )

        html = client.get("/pantry").get_data(as_text=True)

        assert "Today’s meals" in html
        assert f'id="todays-meal-plan-{first_id}"' in html
        assert f'id="todays-meal-plan-{second_id}"' in html
        assert "Lunch soup" in html
        assert "Dinner tacos" in html

    def test_another_households_today_plan_is_not_exposed(
        self, two_clients, app,
    ):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        plan_id = _create_plan(
            app, "alice@example.com", "Alice's dinner",
            planned_for=date.today(),
        )
        sign_up(bob, "bob@example.com", "Bob")

        html = bob.get("/pantry").get_data(as_text=True)

        assert 'id="todays-meal-shortcut"' not in html
        assert f'id="todays-meal-plan-{plan_id}"' not in html
        assert "Alice&#39;s dinner" not in html
