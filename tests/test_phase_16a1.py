"""
Phase 16A.1 regression suite — read-only weekly shopping-gap preview.

The preview consolidates only the saved `need` values for uncooked, scheduled
plans in the coming seven days. It never estimates quantities or writes a
ShoppingItem.

Tier-1 dev loop:

    pytest tests/test_phase_13a3.py tests/test_phase_16a1.py -q
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
    need: list[str],
    planned_for: date,
    cooked_at: datetime | None = None,
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
                "need": need,
                "steps": ["Cook it."],
            }),
            meal_name=name,
            planned_for=planned_for,
            cooked_at=cooked_at,
            is_favorite=is_favorite,
        )
        db.session.add(plan)
        db.session.commit()
        return plan.id


def _preview(html: str) -> str:
    start = html.index('id="weekly-shopping-gaps"')
    end = html.index('<div class="space-y-4">', start)
    return html[start:end]


class TestWeeklyShoppingGapPreview:
    def test_preview_groups_and_consolidates_uncooked_weekly_needs(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        today = date.today()
        _create_plan(
            app, "alice@example.com", "Pasta night",
            need=["Milk", "Spinach", "Milk"],
            planned_for=today + timedelta(days=1),
        )
        _create_plan(
            app, "alice@example.com", "Chicken curry",
            need=[" milk ", "Chicken"],
            planned_for=today + timedelta(days=2),
        )
        _create_plan(
            app, "alice@example.com", "Pantry lunch",
            need=[],
            planned_for=today + timedelta(days=3),
        )
        _create_plan(
            app, "alice@example.com", "Future dinner",
            need=["Tomatoes"],
            planned_for=today + timedelta(days=7),
        )
        _create_plan(
            app, "alice@example.com", "Already cooked",
            need=["Pasta"],
            planned_for=today + timedelta(days=3),
            cooked_at=datetime.utcnow(),
        )

        html = client.get("/meals").get_data(as_text=True)
        preview = _preview(html)
        preview_text = " ".join(preview.split())

        assert "You may need" in preview
        assert "for 2 upcoming meals" in preview_text
        assert "Based on the saved meal plans." in preview
        assert "Review before adding anything to your shopping list." in preview_text
        assert "Dairy &amp; Eggs" in preview
        assert "Produce" in preview
        assert "Meat &amp; Seafood" in preview
        assert preview.count("Milk") == 1
        assert "2 meals" in preview_text
        assert "Spinach" in preview
        assert "Chicken" in preview
        assert "Tomatoes" not in preview
        assert "Pasta" not in preview

    def test_preview_is_hidden_when_scheduled_plans_have_no_need_items(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _create_plan(
            app, "alice@example.com", "Pantry dinner",
            need=[],
            planned_for=date.today(),
        )

        html = client.get("/meals").get_data(as_text=True)

        assert 'id="weekly-shopping-gaps"' not in html

    def test_preview_does_not_misrepresent_a_pinned_filter(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _create_plan(
            app, "alice@example.com", "Pinned dinner",
            need=["Milk"],
            planned_for=date.today(),
            is_favorite=True,
        )

        html = client.get("/meals?filter=favorites").get_data(as_text=True)

        assert 'id="weekly-shopping-gaps"' not in html
        assert "Pinned dinner" in html

    def test_another_households_weekly_gaps_are_not_exposed(
        self, two_clients, app,
    ):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        _create_plan(
            app, "alice@example.com", "Alice's dinner",
            need=["Secret ingredient"],
            planned_for=date.today(),
        )
        sign_up(bob, "bob@example.com", "Bob")

        html = bob.get("/meals").get_data(as_text=True)

        assert 'id="weekly-shopping-gaps"' not in html
        assert "Secret ingredient" not in html
