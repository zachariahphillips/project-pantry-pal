"""
Phase 12A.2 regression suite — reviewed AI deduction proposals.

Suggestions are constrained to the current household's measured pantry
items, strictly validated, and displayed as editable values only. They never
write pantry rows; confirmation belongs to the next phase.

Tier-1 dev loop:

    pytest tests/test_phase_12a2.py -q
"""
from __future__ import annotations

import json

from extensions import db
from models import MealPlan, PantryItem, User
from tests.conftest import Client, sign_up


def _add_pantry(
    client: Client, name: str, *, quantity: str = "", unit: str = "",
) -> None:
    response = client.post("/pantry", htmx=True, data={
        "name": name,
        "quantity": quantity,
        "unit": unit,
        "notes": "",
        "expiry_date": "",
    })
    assert response.status_code in (200, 204)


def _create_plan(app, email: str, *, have: list[str]) -> int:
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        plan = MealPlan(
            household_id=user.household_id,
            created_by_user_id=user.id,
            prompt="Dinner",
            response_json=json.dumps({
                "meal_name": "Test dinner",
                "have": have,
                "need": [],
                "steps": ["Cook it."],
            }),
            meal_name="Test dinner",
        )
        db.session.add(plan)
        db.session.commit()
        return plan.id


def _pantry_item_id(app, name: str) -> int:
    with app.app_context():
        return PantryItem.query.filter_by(name=name).one().id


class TestReviewedDeductionProposal:
    def test_measured_current_match_offers_an_ai_suggestion(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Eggs", quantity="6", unit="ea")
        plan_id = _create_plan(app, "alice@example.com", have=["Eggs"])

        response = client.post(
            f"/meal-plan/{plan_id}/cook-preview", htmx=True,
        )

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Suggest deductions" in html
        assert (
            f'hx-post="/meal-plan/{plan_id}/deduction-proposal"' in html
        )

    def test_proposal_uses_current_candidates_and_does_not_mutate(
        self, client, app, monkeypatch,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Eggs", quantity="6", unit="ea")
        _add_pantry(client, "Pasta", quantity="1", unit="lb")
        plan_id = _create_plan(app, "alice@example.com", have=["Eggs"])
        eggs_id = _pantry_item_id(app, "Eggs")
        captured = {}

        def fake_openai(plan, candidates):
            captured["plan_id"] = plan.id
            captured["candidates"] = [
                (item.id, item.name, item.quantity, item.unit)
                for item in candidates
            ]
            return {
                "deductions": [{
                    "pantry_item_id": eggs_id,
                    "quantity_to_deduct": 2,
                }],
            }, None

        monkeypatch.setattr(
            "app._ask_openai_for_deduction_proposal", fake_openai,
        )
        response = client.post(
            f"/meal-plan/{plan_id}/deduction-proposal", htmx=True,
        )

        assert response.status_code == 200
        assert captured == {
            "plan_id": plan_id,
            "candidates": [(eggs_id, "Eggs", 6, "ea")],
        }
        html = response.get_data(as_text=True)
        assert "Review suggested deductions" in html
        assert "PantryPal has not changed your pantry." in html
        assert f'name="deduction-{eggs_id}"' in html
        assert 'value="2.0"' in html
        assert "would leave 4 ea" in html

        with app.app_context():
            eggs = PantryItem.query.filter_by(name="Eggs").one()
            pasta = PantryItem.query.filter_by(name="Pasta").one()
            assert eggs.quantity == 6
            assert pasta.quantity == 1

    def test_rejects_an_ai_item_id_that_is_not_a_meal_match(
        self, client, app, monkeypatch,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Eggs", quantity="6", unit="ea")
        _add_pantry(client, "Pasta", quantity="1", unit="lb")
        plan_id = _create_plan(app, "alice@example.com", have=["Eggs"])
        pasta_id = _pantry_item_id(app, "Pasta")

        monkeypatch.setattr(
            "app._ask_openai_for_deduction_proposal",
            lambda _plan, _candidates: ({
                "deductions": [{
                    "pantry_item_id": pasta_id,
                    "quantity_to_deduct": 1,
                }],
            }, None),
        )
        response = client.post(
            f"/meal-plan/{plan_id}/deduction-proposal", htmx=True,
        )

        assert response.status_code == 502
        html = response.get_data(as_text=True)
        assert "unsafe deduction suggestion" in html
        assert '<input type="number"' not in html
        with app.app_context():
            assert PantryItem.query.filter_by(name="Pasta").one().quantity == 1

    def test_rejects_a_suggested_amount_above_current_quantity(
        self, client, app, monkeypatch,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Eggs", quantity="6", unit="ea")
        plan_id = _create_plan(app, "alice@example.com", have=["Eggs"])
        eggs_id = _pantry_item_id(app, "Eggs")

        monkeypatch.setattr(
            "app._ask_openai_for_deduction_proposal",
            lambda _plan, _candidates: ({
                "deductions": [{
                    "pantry_item_id": eggs_id,
                    "quantity_to_deduct": 6.1,
                }],
            }, None),
        )
        response = client.post(
            f"/meal-plan/{plan_id}/deduction-proposal", htmx=True,
        )

        assert response.status_code == 502
        assert "unsafe deduction suggestion" in response.get_data(
            as_text=True,
        )
        with app.app_context():
            assert PantryItem.query.filter_by(name="Eggs").one().quantity == 6

    def test_unmeasured_matches_cannot_request_a_proposal(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Salt")
        plan_id = _create_plan(app, "alice@example.com", have=["Salt"])

        preview = client.post(
            f"/meal-plan/{plan_id}/cook-preview", htmx=True,
        )
        assert "Suggest deductions" not in preview.get_data(as_text=True)
        assert "Add a quantity" in preview.get_data(as_text=True)

        response = client.post(
            f"/meal-plan/{plan_id}/deduction-proposal", htmx=True,
        )
        assert response.status_code == 422
        assert "Add a current quantity" in response.get_data(as_text=True)

    def test_another_household_cannot_request_a_proposal(
        self, two_clients, app,
    ):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        _add_pantry(alice, "Eggs", quantity="6", unit="ea")
        plan_id = _create_plan(app, "alice@example.com", have=["Eggs"])
        sign_up(bob, "bob@example.com", "Bob")

        response = bob.post(
            f"/meal-plan/{plan_id}/deduction-proposal", htmx=True,
        )

        assert response.status_code == 404
