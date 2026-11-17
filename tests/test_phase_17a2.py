"""
Phase 17A.2 regression suite — manual unit helper.

Manual amount review offers only the units already recorded for that
ingredient's unresolved weekly gap. A chip fills the editable unit field; it
does not choose a quantity or convert between units.
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


class TestManualUnitHelper:
    def test_mixed_units_offer_tappable_contextual_suggestions(
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

        html = client.get("/meals").get_data(as_text=True)

        assert html.count("data-weekly-gap-manual-unit-suggestion") == 2
        assert 'data-unit="cup"' in html
        assert 'data-unit="ml"' in html
        assert "Use a shown unit:" in html
        assert (
            "document.getElementById('weekly-gap-manual-unit-6d696c6b')"
            ".value = this.dataset.unit"
        ) in html

    def test_overlap_suggestions_fill_the_separate_entry_unit_field(
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
            quantity=None,
            planned_for=date.today() + timedelta(days=1),
        )
        _add_shopping(app, "alice@example.com", "Milk")

        html = client.get("/meals").get_data(as_text=True)

        assert html.count("data-weekly-gap-manual-unit-suggestion") == 1
        assert re.search(
            r"document\.getElementById\('weekly-gap-overlap-manual-unit-"
            r"6d696c6b'\)\.value = this\.dataset\.unit",
            html,
        )

    def test_legacy_only_gap_offers_no_unit_suggestion(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        _create_plan(
            app, "alice@example.com",
            quantity=None,
            planned_for=date.today(),
        )

        html = client.get("/meals").get_data(as_text=True)

        assert "data-weekly-gap-manual-unit-suggestion" not in html
