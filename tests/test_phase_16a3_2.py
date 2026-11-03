"""
Phase 16A.3.2 regression suite — explicit add-or-skip overlap decision.

Active overlaps default to skipping. A separate shopping row is permitted
only through the dedicated explicit choice, which is rechecked server-side
against the current household's active Shopping rows.

Tier-1 dev loop:

    pytest tests/test_phase_16a2.py tests/test_phase_16a3_1.py \
        tests/test_phase_16a3_2.py -q
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
    checked: bool = False,
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


class TestWeeklyShoppingGapOverlapDecision:
    def test_active_overlap_requires_explicit_separate_entry_choice(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _create_plan(app, "alice@example.com", need=["Milk"])
        _add_shopping(app, "alice@example.com", "milk")

        html = client.get("/meals").get_data(as_text=True)
        blocked = client.post(
            "/meals/weekly-shopping-gaps/add",
            data={"weekly_gap": "Milk"},
            htmx=True,
        )
        added = client.post(
            "/meals/weekly-shopping-gaps/add",
            data={"weekly_gap_overlap_add": "Milk"},
            htmx=True,
        )

        assert 'name="weekly_gap_overlap_add"' in html
        assert "Add a separate shopping entry" in html
        assert "Leave unchecked to skip this existing item." in html
        assert blocked.status_code == 409
        assert added.status_code == 200
        with app.app_context():
            rows = ShoppingItem.query.order_by(ShoppingItem.id).all()
            assert len(rows) == 2
            assert rows[1].name == "Milk"
            assert rows[1].notes == "Suggested for upcoming meals"

    def test_separate_entry_intent_is_rejected_when_overlap_is_stale(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _create_plan(app, "alice@example.com", need=["Milk"])

        response = client.post(
            "/meals/weekly-shopping-gaps/add",
            data={"weekly_gap_overlap_add": "Milk"},
            htmx=True,
        )

        assert response.status_code == 409
        with app.app_context():
            assert ShoppingItem.query.count() == 0

    def test_checked_item_remains_a_regular_gap_selection(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _create_plan(app, "alice@example.com", need=["Milk"])
        _add_shopping(app, "alice@example.com", "Milk", checked=True)

        response = client.post(
            "/meals/weekly-shopping-gaps/add",
            data={"weekly_gap": "Milk"},
            htmx=True,
        )

        assert response.status_code == 200
        with app.app_context():
            assert ShoppingItem.query.count() == 2
