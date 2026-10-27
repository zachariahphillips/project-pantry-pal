"""
Phase 13A.3 regression suite — ordered upcoming-week Meals section.

The view is a rolling seven-day list, not a calendar. Scheduled meals in that
window are promoted out of the historical list, ordered by cook date, and
still respect the existing household and Pinned filters.

Tier-1 dev loop:

    pytest tests/test_phase_13a1.py tests/test_phase_13a2.py \
        tests/test_phase_13a3.py -q
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from extensions import db
from models import MealPlan, User
from tests.conftest import sign_up


def _create_plan(
    app,
    email: str,
    name: str,
    *,
    planned_for: date | None = None,
    is_favorite: bool = False,
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
            is_favorite=is_favorite,
        )
        db.session.add(plan)
        db.session.commit()
        return plan.id


def _upcoming_section(html: str) -> str:
    start = html.index('id="upcoming-week-meals"')
    end = html.index('id="meals-list"')
    return html[start:end]


class TestUpcomingWeekMeals:
    def test_next_seven_days_are_promoted_in_cook_date_order(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        today = date.today()
        # Create in non-calendar order to prove the view sorts on planned_for,
        # rather than retaining the history section's newest-first order.
        later_id = _create_plan(
            app, "alice@example.com", "Saturday tacos",
            planned_for=today + timedelta(days=5),
        )
        today_id = _create_plan(
            app, "alice@example.com", "Today soup", planned_for=today,
        )
        last_day_id = _create_plan(
            app, "alice@example.com", "Week-end pasta",
            planned_for=today + timedelta(days=6),
        )
        outside_week_id = _create_plan(
            app, "alice@example.com", "Next week curry",
            planned_for=today + timedelta(days=7),
        )
        unscheduled_id = _create_plan(
            app, "alice@example.com", "Unscheduled salad",
        )

        html = client.get("/meals").get_data(as_text=True)
        upcoming = _upcoming_section(html)

        assert "Upcoming this week" in upcoming
        assert "3 planned" in upcoming
        assert (
            upcoming.index(f'id="meal-plan-{today_id}"')
            < upcoming.index(f'id="meal-plan-{later_id}"')
            < upcoming.index(f'id="meal-plan-{last_day_id}"')
        )
        assert f'id="meal-plan-{outside_week_id}"' not in upcoming
        assert f'id="meal-plan-{unscheduled_id}"' not in upcoming
        # Promoted cards are not duplicated below the history heading.
        assert html.count(f'id="meal-plan-{today_id}"') == 1
        history_start = html.index('id="meals-list"')
        history = html[history_start:]
        assert f'id="meal-plan-{outside_week_id}"' in history
        assert f'id="meal-plan-{unscheduled_id}"' in history
        assert "Meal history" in html

    def test_pinned_filter_applies_to_the_upcoming_week_section(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        today = date.today()
        favorite_id = _create_plan(
            app, "alice@example.com", "Pinned dinner",
            planned_for=today + timedelta(days=1),
            is_favorite=True,
        )
        unpinned_id = _create_plan(
            app, "alice@example.com", "Unpinned dinner",
            planned_for=today + timedelta(days=2),
        )

        html = client.get("/meals?filter=favorites").get_data(as_text=True)
        upcoming = _upcoming_section(html)

        assert f'id="meal-plan-{favorite_id}"' in upcoming
        assert f'id="meal-plan-{unpinned_id}"' not in html
        assert "1 planned" in upcoming
        assert 'aria-current="page"' in html

    def test_no_upcoming_section_is_rendered_without_week_dates(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        plan_id = _create_plan(
            app, "alice@example.com", "Later meal",
            planned_for=date.today() + timedelta(days=7),
        )

        html = client.get("/meals").get_data(as_text=True)

        assert 'id="upcoming-week-meals"' not in html
        assert f'id="meal-plan-{plan_id}"' in html

    def test_another_households_upcoming_plans_are_not_exposed(
        self, two_clients, app,
    ):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        plan_id = _create_plan(
            app, "alice@example.com", "Alice's dinner",
            planned_for=date.today() + timedelta(days=1),
        )
        sign_up(bob, "bob@example.com", "Bob")

        html = bob.get("/meals").get_data(as_text=True)

        assert 'id="upcoming-week-meals"' not in html
        assert f'id="meal-plan-{plan_id}"' not in html
        assert "Alice&#39;s dinner" not in html
