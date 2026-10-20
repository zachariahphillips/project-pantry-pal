"""
Phase 12B.2 regression suite — household-shared meal pin controls.

The card-local htmx control toggles only the favorite affordance, leaving
expanded/collapsed card state and other controls untouched.

Tier-1 dev loop:

    pytest tests/test_phase_12b2.py -q
"""
from __future__ import annotations

import json

from extensions import db
from models import Household, MealPlan, User
from tests.conftest import sign_up


def _create_plan(app, email: str) -> int:
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        plan = MealPlan(
            household_id=user.household_id,
            created_by_user_id=user.id,
            prompt="Dinner",
            response_json=json.dumps({
                "meal_name": "Test dinner",
                "have": [],
                "need": [],
                "steps": ["Cook it."],
            }),
            meal_name="Test dinner",
        )
        db.session.add(plan)
        db.session.commit()
        return plan.id


class TestMealPlanFavoriteToggle:
    def test_meal_cards_render_an_unpinned_household_star(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        plan_id = _create_plan(app, "alice@example.com")

        html = client.get("/meals").get_data(as_text=True)

        assert f'id="meal-plan-favorite-{plan_id}"' in html
        assert f'hx-post="/meal-plan/{plan_id}/favorite"' in html
        assert f'hx-target="#meal-plan-favorite-{plan_id}"' in html
        assert 'aria-pressed="false"' in html
        assert "Pin Test dinner to household favorites" in html

    def test_toggle_updates_only_its_card_control_and_persists(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        plan_id = _create_plan(app, "alice@example.com")

        pinned = client.post(
            f"/meal-plan/{plan_id}/favorite", htmx=True,
        )

        assert pinned.status_code == 200
        html = pinned.get_data(as_text=True)
        assert f'id="meal-plan-favorite-{plan_id}"' in html
        assert 'aria-pressed="true"' in html
        assert "Unpin Test dinner from household favorites" in html
        assert "<article" not in html
        with app.app_context():
            assert db.session.get(MealPlan, plan_id).is_favorite is True

        unpinned = client.post(
            f"/meal-plan/{plan_id}/favorite", htmx=True,
        )

        assert unpinned.status_code == 200
        assert 'aria-pressed="false"' in unpinned.get_data(as_text=True)
        with app.app_context():
            assert db.session.get(MealPlan, plan_id).is_favorite is False

    def test_another_household_cannot_pin_or_unpin_a_meal(
        self, two_clients, app,
    ):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        plan_id = _create_plan(app, "alice@example.com")
        sign_up(bob, "bob@example.com", "Bob")

        response = bob.post(
            f"/meal-plan/{plan_id}/favorite", htmx=True,
        )

        assert response.status_code == 404
        with app.app_context():
            assert db.session.get(MealPlan, plan_id).is_favorite is False

    def test_anonymous_toggle_redirects_to_login(self, client, app):
        with app.app_context():
            household = Household(name="Alice's home")
            db.session.add(household)
            db.session.flush()
            user = User(
                email="alice@example.com",
                name="Alice",
                password_hash="unused",
                household_id=household.id,
            )
            db.session.add(user)
            db.session.flush()
            plan = MealPlan(
                household_id=user.household_id,
                created_by_user_id=user.id,
                prompt="Dinner",
                response_json=json.dumps({}),
                meal_name="Test dinner",
            )
            db.session.add(plan)
            db.session.commit()
            plan_id = plan.id

        response = client.post(f"/meal-plan/{plan_id}/favorite", htmx=True)

        assert response.status_code == 302
        assert "/login" in response.headers["Location"]
