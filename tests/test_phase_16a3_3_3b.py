"""
Phase 16A.3.3.3b regression suite — reviewed weekly quantity handoff.

Only a complete, single-unit weekly subtotal can be explicitly copied to a
separate Shopping row. The server re-derives the total, so partial, mixed-unit,
stale, and overlap-bypassing requests cannot invent or silently merge amounts.

Tier-1 dev loop:

    pytest tests/test_phase_16a2.py tests/test_phase_16a3_3_2a.py \
        tests/test_phase_16a3_3_3b.py -q
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
    quantity: float | None,
    unit: str = "cup",
    planned_for: date,
) -> None:
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        response = {
            "meal_name": "Test dinner",
            "have": [],
            "need": ["Milk"],
            "steps": ["Cook it."],
        }
        if quantity is not None:
            response["need_details"] = [{
                "name": "Milk",
                "quantity": quantity,
                "unit": unit,
            }]
        db.session.add(MealPlan(
            household_id=user.household_id,
            created_by_user_id=user.id,
            prompt="Dinner",
            response_json=json.dumps(response),
            meal_name="Test dinner",
            planned_for=planned_for,
        ))
        db.session.commit()


def _add_shopping(app, email: str, name: str) -> None:
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        db.session.add(ShoppingItem(
            household_id=user.household_id,
            added_by_user_id=user.id,
            name=name,
        ))
        db.session.commit()


def _reviewed_selection(
    name: str,
    quantity: float,
    unit: str,
) -> str:
    return json.dumps(
        {"name": name, "quantity": quantity, "unit": unit},
        separators=(",", ":"),
    )


class TestReviewedWeeklyQuantityHandoff:
    def test_complete_single_unit_total_can_be_explicitly_added(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _create_plan(
            app, "alice@example.com",
            quantity=1,
            planned_for=date.today(),
        )
        _create_plan(
            app, "alice@example.com",
            quantity=0.5,
            planned_for=date.today() + timedelta(days=1),
        )

        html = client.get("/meals").get_data(as_text=True)
        response = client.post(
            "/meals/weekly-shopping-gaps/add",
            data={"weekly_gap_quantity": _reviewed_selection("Milk", 1.5, "cup")},
            htmx=True,
        )

        assert 'name="weekly_gap_quantity"' in html
        assert "Add 1.5 cup to shopping" in html
        assert response.status_code == 200
        with app.app_context():
            row = ShoppingItem.query.one()
            assert (row.name, row.quantity, row.unit, row.notes) == (
                "Milk", 1.5, "cup", "Suggested for 2 upcoming meals",
            )

    def test_partial_or_mixed_unit_total_cannot_be_copied_as_a_quantity(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _create_plan(
            app, "alice@example.com",
            quantity=1,
            planned_for=date.today(),
        )
        _create_plan(
            app, "alice@example.com",
            quantity=None,
            planned_for=date.today() + timedelta(days=1),
        )

        partial_html = client.get("/meals").get_data(as_text=True)
        partial = client.post(
            "/meals/weekly-shopping-gaps/add",
            data={"weekly_gap_quantity": _reviewed_selection("Milk", 1, "cup")},
            htmx=True,
        )
        name_only = client.post(
            "/meals/weekly-shopping-gaps/add",
            data={"weekly_gap": "Milk"},
            htmx=True,
        )

        assert 'name="weekly_gap_quantity"' not in partial_html
        assert 'name="weekly_gap"' in partial_html
        assert partial.status_code == 409
        assert name_only.status_code == 200
        with app.app_context():
            row = ShoppingItem.query.one()
            assert row.quantity is None
            assert row.unit is None
            assert row.notes == "Suggested for upcoming meals"

    def test_mixed_units_remain_review_only(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        _create_plan(
            app, "alice@example.com",
            quantity=1,
            unit="cup",
            planned_for=date.today(),
        )
        _create_plan(
            app, "alice@example.com",
            quantity=250,
            unit="ml",
            planned_for=date.today() + timedelta(days=1),
        )

        html = client.get("/meals").get_data(as_text=True)
        response = client.post(
            "/meals/weekly-shopping-gaps/add",
            data={"weekly_gap_quantity": _reviewed_selection("Milk", 1, "cup")},
            htmx=True,
        )

        assert 'name="weekly_gap_quantity"' not in html
        assert response.status_code == 409
        with app.app_context():
            assert ShoppingItem.query.count() == 0

    def test_changed_total_rejects_a_stale_reviewed_selection(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _create_plan(
            app, "alice@example.com",
            quantity=1,
            planned_for=date.today(),
        )
        client.get("/meals")
        _create_plan(
            app, "alice@example.com",
            quantity=0.5,
            planned_for=date.today() + timedelta(days=1),
        )

        response = client.post(
            "/meals/weekly-shopping-gaps/add",
            data={"weekly_gap_quantity": _reviewed_selection("Milk", 1, "cup")},
            htmx=True,
        )

        assert response.status_code == 409
        with app.app_context():
            assert ShoppingItem.query.count() == 0

    def test_quantity_overlap_still_requires_a_separate_entry_choice(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _create_plan(
            app, "alice@example.com",
            quantity=2,
            planned_for=date.today(),
        )
        _add_shopping(app, "alice@example.com", "milk")

        html = client.get("/meals").get_data(as_text=True)
        blocked = client.post(
            "/meals/weekly-shopping-gaps/add",
            data={"weekly_gap_quantity": _reviewed_selection("Milk", 2, "cup")},
            htmx=True,
        )
        added = client.post(
            "/meals/weekly-shopping-gaps/add",
            data={
                "weekly_gap_overlap_quantity": _reviewed_selection(
                    "Milk", 2, "cup",
                ),
            },
            htmx=True,
        )

        assert 'name="weekly_gap_overlap_quantity"' in html
        assert "Add a separate 2 cup entry" in html
        assert blocked.status_code == 409
        assert added.status_code == 200
        with app.app_context():
            rows = ShoppingItem.query.order_by(ShoppingItem.id).all()
            assert [(row.name, row.quantity, row.unit) for row in rows] == [
                ("milk", None, None),
                ("Milk", 2, "cup"),
            ]
            assert rows[1].notes == "Suggested for 1 upcoming meal"
