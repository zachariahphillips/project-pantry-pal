"""
Phase 16A.2 regression suite — reviewed weekly-gap handoff to Shopping.

Only explicitly selected, server-recomputed current-week gaps can create
ShoppingItem rows. The preview remains a review surface; it neither accepts
arbitrary names nor silently consolidates duplicate shopping entries.

Tier-1 dev loop:

    pytest tests/test_phase_11c3.py tests/test_phase_16a1.py \
        tests/test_phase_16a2.py -q
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

from extensions import db
from models import MealPlan, ShoppingItem, User
from tests.conftest import sign_up


def _create_plan(
    app,
    email: str,
    *,
    need: list[str],
    planned_for: date | None = None,
) -> int:
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        plan = MealPlan(
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
            planned_for=planned_for,
        )
        db.session.add(plan)
        db.session.commit()
        return plan.id


class TestWeeklyShoppingGapHandoff:
    def test_preview_offers_unchecked_explicit_item_selection(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _create_plan(
            app, "alice@example.com",
            need=["Milk", "Chicken"],
            planned_for=date.today(),
        )

        html = client.get("/meals").get_data(as_text=True)

        assert 'action="/meals/weekly-shopping-gaps/add"' in html
        assert 'hx-post="/meals/weekly-shopping-gaps/add"' in html
        assert 'name="weekly_gap"' in html
        assert 'value="Milk"' in html
        assert 'value="Chicken"' in html
        assert "Add selected to shopping" in html
        assert "Selected items are added as separate shopping entries." in html
        checkbox_tags = re.findall(
            r'<input type="checkbox"[^>]*name="weekly_gap"[^>]*>',
            html,
        )
        assert len(checkbox_tags) == 2
        assert all("checked" not in tag for tag in checkbox_tags)

    def test_selected_current_week_gaps_create_categorized_shopping_rows(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _create_plan(
            app, "alice@example.com",
            need=["Milk", "Chicken"],
            planned_for=date.today() + timedelta(days=1),
        )

        response = client.post(
            "/meals/weekly-shopping-gaps/add",
            data={"weekly_gap": ["Milk", "Chicken"]},
            htmx=True,
        )

        assert response.status_code == 200
        assert '"count": 2' in response.headers["HX-Trigger"]
        with app.app_context():
            rows = ShoppingItem.query.order_by(ShoppingItem.name).all()
            assert [(row.name, row.category, row.notes) for row in rows] == [
                (
                    "Chicken",
                    "Meat & Seafood",
                    "Suggested for upcoming meals",
                ),
                ("Milk", "Dairy & Eggs", "Suggested for upcoming meals"),
            ]
            assert all(row.quantity is None and row.unit is None for row in rows)

    def test_empty_or_unrecognized_selection_cannot_add_arbitrary_items(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _create_plan(
            app, "alice@example.com",
            need=["Milk"],
            planned_for=date.today(),
        )

        empty = client.post(
            "/meals/weekly-shopping-gaps/add", data={}, htmx=True,
        )
        malicious = client.post(
            "/meals/weekly-shopping-gaps/add",
            data={"weekly_gap": ["Milk", "Injected item"]},
            htmx=True,
        )

        assert empty.status_code == 422
        assert malicious.status_code == 409
        with app.app_context():
            assert ShoppingItem.query.count() == 0

    def test_another_households_weekly_gap_cannot_be_added(
        self, two_clients, app,
    ):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        _create_plan(
            app, "alice@example.com",
            need=["Alice's secret ingredient"],
            planned_for=date.today(),
        )
        sign_up(bob, "bob@example.com", "Bob")

        response = bob.post(
            "/meals/weekly-shopping-gaps/add",
            data={"weekly_gap": "Alice's secret ingredient"},
            htmx=True,
        )

        assert response.status_code == 409
        with app.app_context():
            bob_user = User.query.filter_by(email="bob@example.com").one()
            assert ShoppingItem.query.filter_by(
                household_id=bob_user.household_id,
            ).count() == 0
