"""
Phase 14A.2 regression suite — shareable cooked meal history filter.

The Cooked view is retrospective: it sorts by actual cook timestamp and does
not mix forward-looking scheduled meals into the seven-day planner section.

Tier-1 dev loop:

    pytest tests/test_phase_12b3.py tests/test_phase_14a1.py \
        tests/test_phase_14a2.py -q
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from extensions import db
from models import MealPlan, User
from tests.conftest import sign_up


def _create_plan(
    app,
    email: str,
    name: str,
    *,
    cooked_at: datetime | None = None,
    planned_for: date | None = None,
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
            cooked_at=cooked_at,
            planned_for=planned_for,
        )
        db.session.add(plan)
        db.session.commit()
        return plan.id


class TestCookedMealFilter:
    def test_filter_shows_only_cooked_meals_newest_first(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        now = datetime.utcnow().replace(microsecond=0)
        older_id = _create_plan(
            app, "alice@example.com", "Earlier dinner",
            cooked_at=now - timedelta(days=3),
        )
        newer_id = _create_plan(
            app, "alice@example.com", "Recent dinner",
            cooked_at=now - timedelta(hours=1),
            planned_for=date.today(),
        )
        uncooked_id = _create_plan(
            app, "alice@example.com", "Future idea",
            planned_for=date.today() + timedelta(days=1),
        )

        html = client.get("/meals?filter=cooked").get_data(as_text=True)

        assert 'href="/meals?filter=cooked"' in html
        assert 'aria-current="page"' in html
        assert f'id="meal-plan-{newer_id}"' in html
        assert f'id="meal-plan-{older_id}"' in html
        assert f'id="meal-plan-{uncooked_id}"' not in html
        assert html.index(f'id="meal-plan-{newer_id}"') < html.index(
            f'id="meal-plan-{older_id}"',
        )
        assert 'id="upcoming-week-meals"' not in html
        assert "Upcoming this week" not in html

    def test_empty_cooked_filter_explains_how_history_is_created(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _create_plan(app, "alice@example.com", "Uncooked dinner")

        html = client.get("/meals?filter=cooked").get_data(as_text=True)

        assert "No cooked meals yet" in html
        assert "Confirm pantry changes after cooking" in html
        assert "Uncooked dinner" not in html
        assert 'href="/meals"' in html

    def test_another_households_cooked_meals_are_not_exposed(
        self, two_clients, app,
    ):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        plan_id = _create_plan(
            app, "alice@example.com", "Alice's dinner",
            cooked_at=datetime.utcnow(),
        )
        sign_up(bob, "bob@example.com", "Bob")

        html = bob.get("/meals?filter=cooked").get_data(as_text=True)

        assert "No cooked meals yet" in html
        assert f'id="meal-plan-{plan_id}"' not in html
        assert "Alice&#39;s dinner" not in html
