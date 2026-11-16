"""
Phase 17A.1 regression suite — manual quantity review for unresolved gaps.

Partial and mixed-unit weekly gaps stay non-inferential, but a household can
explicitly supply an amount/unit for a separate Shopping row. Legacy-only
gaps do not expose that control, and a manual entry remains subject to the
same active-overlap review as every other weekly handoff.

Tier-1 dev loop:

    pytest tests/test_phase_16a2.py tests/test_phase_16a3_3_3b.py \
        tests/test_phase_17a1.py -q
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


def _manual_fields(
    quantity: str,
    unit: str,
    *,
    overlap: bool = False,
) -> dict[str, str]:
    key = "Milk".casefold().encode("utf-8").hex()
    prefix = "weekly_gap_overlap_manual" if overlap else "weekly_gap_manual"
    return {
        f"{prefix}_quantity__{key}": quantity,
        f"{prefix}_unit__{key}": unit,
    }


class TestManualWeeklyQuantityReview:
    def test_partial_gap_can_create_a_separate_user_entered_amount(
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

        html = client.get("/meals").get_data(as_text=True)
        response = client.post(
            "/meals/weekly-shopping-gaps/add",
            data=_manual_fields("2.5", "bottles"),
            htmx=True,
        )

        assert "Set an amount yourself" in html
        assert "PantryPal does not convert the known totals." in html
        assert 'name="weekly_gap_manual_quantity__6d696c6b"' in html
        assert response.status_code == 200
        with app.app_context():
            row = ShoppingItem.query.one()
            assert (row.name, row.quantity, row.unit, row.notes) == (
                "Milk",
                2.5,
                "bottles",
                "Suggested for 2 upcoming meals · amount entered manually",
            )

    def test_mixed_units_can_be_resolved_by_a_user_chosen_unit(
        self, client, app,
    ):
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

        response = client.post(
            "/meals/weekly-shopping-gaps/add",
            data=_manual_fields("1", "carton"),
            htmx=True,
        )

        assert response.status_code == 200
        with app.app_context():
            row = ShoppingItem.query.one()
            assert (row.quantity, row.unit) == (1, "carton")

    def test_legacy_only_gap_cannot_receive_a_manual_amount(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        _create_plan(
            app, "alice@example.com",
            quantity=None,
            planned_for=date.today(),
        )

        html = client.get("/meals").get_data(as_text=True)
        legacy = client.post(
            "/meals/weekly-shopping-gaps/add",
            data=_manual_fields("2", "bottles"),
            htmx=True,
        )

        assert "Set an amount yourself" not in html
        assert legacy.status_code == 409
        with app.app_context():
            assert ShoppingItem.query.count() == 0

    def test_manual_amount_requires_a_positive_number_and_unit(self, client, app):
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

        missing_unit = client.post(
            "/meals/weekly-shopping-gaps/add",
            data=_manual_fields("2", ""),
            htmx=True,
        )
        non_positive = client.post(
            "/meals/weekly-shopping-gaps/add",
            data=_manual_fields("0", "bottles"),
            htmx=True,
        )

        assert missing_unit.status_code == 409
        assert non_positive.status_code == 409
        with app.app_context():
            assert ShoppingItem.query.count() == 0

    def test_manual_overlap_amount_is_an_explicit_separate_entry(
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
        _add_shopping(app, "alice@example.com", "milk")

        html = client.get("/meals").get_data(as_text=True)
        response = client.post(
            "/meals/weekly-shopping-gaps/add",
            data=_manual_fields("2", "cartons", overlap=True),
            htmx=True,
        )

        assert "Add a separate amount yourself" in html
        assert response.status_code == 200
        with app.app_context():
            rows = ShoppingItem.query.order_by(ShoppingItem.id).all()
            assert [(row.name, row.quantity, row.unit) for row in rows] == [
                ("milk", None, None),
                ("Milk", 2, "cartons"),
            ]
