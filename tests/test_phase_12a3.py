"""
Phase 12A.3 regression suite — confirmed meal deductions and Undo.

The confirmation endpoint revalidates edited quantities, commits every
deduction atomically, and stores a one-time, household-scoped Undo snapshot.

Tier-1 dev loop:

    pytest tests/test_phase_12a3.py -q
"""
from __future__ import annotations

import json
from datetime import date

from extensions import db
from models import MealPlan, PantryItem, User
from tests.conftest import Client, sign_up


def _add_pantry(
    client: Client, name: str, *, quantity: str, unit: str = "",
    notes: str = "", expiry_date: str = "",
) -> None:
    response = client.post("/pantry", htmx=True, data={
        "name": name,
        "quantity": quantity,
        "unit": unit,
        "notes": notes,
        "expiry_date": expiry_date,
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


def _item_id(app, name: str) -> int:
    with app.app_context():
        return PantryItem.query.filter_by(name=name).one().id


def _trigger(response) -> dict:
    return json.loads(response.headers["HX-Trigger"])


class TestConfirmedMealDeductions:
    def test_apply_is_transactional_and_undo_restores_all_quantities(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Eggs", quantity="6", unit="ea")
        _add_pantry(client, "Pasta", quantity="2", unit="lb")
        plan_id = _create_plan(
            app, "alice@example.com", have=["Eggs", "Pasta"],
        )
        eggs_id = _item_id(app, "Eggs")
        pasta_id = _item_id(app, "Pasta")

        applied = client.post(
            f"/meal-plan/{plan_id}/deduction-apply", htmx=True,
            data={
                f"deduction-{eggs_id}": "2",
                f"deduction-{pasta_id}": "0.5",
            },
        )

        assert applied.status_code == 200
        applied_html = applied.get_data(as_text=True)
        assert "Deducted 2 pantry" in applied_html
        assert "items." in applied_html
        event = _trigger(applied)["meal-plan:deductions-applied"]
        assert event == {
            "count": 2,
            "undoUrl": f"/meal-plan/{plan_id}/deduction-undo",
            "target": f"#meal-plan-cook-preview-{plan_id}",
        }
        with app.app_context():
            assert db.session.get(PantryItem, eggs_id).quantity == 4
            assert db.session.get(PantryItem, pasta_id).quantity == 1.5

        undone = client.post(
            f"/meal-plan/{plan_id}/deduction-undo", htmx=True,
        )

        assert undone.status_code == 200
        assert "Review pantry changes" in undone.get_data(as_text=True)
        assert _trigger(undone) == {
            "meal-plan:deductions-undone": {"count": 2}
        }
        with app.app_context():
            assert db.session.get(PantryItem, eggs_id).quantity == 6
            assert db.session.get(PantryItem, pasta_id).quantity == 2

    def test_exact_depletion_removes_then_undo_restores_item_details(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(
            client, "Yogurt", quantity="2", unit="cups",
            notes="use first", expiry_date="2026-11-02",
        )
        plan_id = _create_plan(app, "alice@example.com", have=["Yogurt"])
        yogurt_id = _item_id(app, "Yogurt")

        applied = client.post(
            f"/meal-plan/{plan_id}/deduction-apply", htmx=True,
            data={f"deduction-{yogurt_id}": "2"},
        )

        assert "1 empty item was removed." in applied.get_data(as_text=True)
        with app.app_context():
            assert db.session.get(PantryItem, yogurt_id) is None

        client.post(f"/meal-plan/{plan_id}/deduction-undo", htmx=True)
        with app.app_context():
            yogurt = PantryItem.query.filter_by(name="Yogurt").one()
            assert yogurt.quantity == 2
            assert yogurt.unit == "cups"
            assert yogurt.notes == "use first"
            assert yogurt.expiry_date == date(2026, 11, 2)

    def test_invalid_batch_rolls_back_every_deduction(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Eggs", quantity="6", unit="ea")
        _add_pantry(client, "Pasta", quantity="2", unit="lb")
        plan_id = _create_plan(
            app, "alice@example.com", have=["Eggs", "Pasta"],
        )
        eggs_id = _item_id(app, "Eggs")
        pasta_id = _item_id(app, "Pasta")

        response = client.post(
            f"/meal-plan/{plan_id}/deduction-apply", htmx=True,
            data={
                f"deduction-{eggs_id}": "2",
                f"deduction-{pasta_id}": "3",
            },
        )

        assert response.status_code == 200
        assert "cannot deduct more Pasta" in response.get_data(as_text=True)
        with app.app_context():
            assert db.session.get(PantryItem, eggs_id).quantity == 6
            assert db.session.get(PantryItem, pasta_id).quantity == 2

    def test_undo_does_not_overwrite_a_newer_pantry_change(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Eggs", quantity="6", unit="ea")
        plan_id = _create_plan(app, "alice@example.com", have=["Eggs"])
        eggs_id = _item_id(app, "Eggs")

        client.post(
            f"/meal-plan/{plan_id}/deduction-apply", htmx=True,
            data={f"deduction-{eggs_id}": "2"},
        )
        with app.app_context():
            db.session.get(PantryItem, eggs_id).quantity = 3
            db.session.commit()

        response = client.post(
            f"/meal-plan/{plan_id}/deduction-undo", htmx=True,
        )

        assert response.status_code == 200
        assert "could not undo safely" in response.get_data(as_text=True)
        with app.app_context():
            assert db.session.get(PantryItem, eggs_id).quantity == 3

    def test_another_household_cannot_apply_or_undo(
        self, two_clients, app,
    ):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        _add_pantry(alice, "Eggs", quantity="6", unit="ea")
        plan_id = _create_plan(app, "alice@example.com", have=["Eggs"])
        eggs_id = _item_id(app, "Eggs")
        sign_up(bob, "bob@example.com", "Bob")

        apply_response = bob.post(
            f"/meal-plan/{plan_id}/deduction-apply", htmx=True,
            data={f"deduction-{eggs_id}": "2"},
        )
        undo_response = bob.post(
            f"/meal-plan/{plan_id}/deduction-undo", htmx=True,
        )

        assert apply_response.status_code == 404
        assert undo_response.status_code == 404

    def test_reviewed_proposal_has_a_confirm_action(
        self, client, app, monkeypatch,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Eggs", quantity="6", unit="ea")
        plan_id = _create_plan(app, "alice@example.com", have=["Eggs"])
        eggs_id = _item_id(app, "Eggs")
        monkeypatch.setattr(
            "app._ask_openai_for_deduction_proposal",
            lambda _plan, _candidates: ({
                "deductions": [{
                    "pantry_item_id": eggs_id,
                    "quantity_to_deduct": 2,
                }],
            }, None),
        )

        response = client.post(
            f"/meal-plan/{plan_id}/deduction-proposal", htmx=True,
        )

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Confirm pantry changes" in html
        assert f'hx-post="/meal-plan/{plan_id}/deduction-apply"' in html
