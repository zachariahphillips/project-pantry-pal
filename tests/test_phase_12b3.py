"""
Phase 12B.3 regression suite — favorite meal filter.

The view uses an explicit, shareable query parameter. Unpinning from the
filtered view redirects back to it so an unpinned card cannot linger.

Tier-1 dev loop:

    pytest tests/test_phase_12b3.py -q
"""
from __future__ import annotations

import json

from extensions import db
from models import MealPlan, User
from tests.conftest import sign_up


def _create_plan(app, email: str, *, name: str, favorite: bool) -> int:
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
            is_favorite=favorite,
        )
        db.session.add(plan)
        db.session.commit()
        return plan.id


class TestFavoriteMealFilter:
    def test_favorites_filter_shows_only_pinned_meals(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        _create_plan(
            app, "alice@example.com", name="Pinned pasta", favorite=True,
        )
        _create_plan(
            app, "alice@example.com", name="Weeknight soup", favorite=False,
        )

        response = client.get("/meals?filter=favorites")

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Pinned pasta" in html
        assert "Weeknight soup" not in html
        assert 'aria-current="page"' in html
        assert 'href="/meals"' in html

    def test_pinned_empty_state_keeps_a_path_back_to_all_meals(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _create_plan(
            app, "alice@example.com", name="Weeknight soup", favorite=False,
        )

        html = client.get("/meals?filter=favorites").get_data(as_text=True)

        assert "No pinned meals yet" in html
        assert "Pin a meal with its star" in html
        assert 'href="/meals"' in html
        assert "Weeknight soup" not in html

    def test_unknown_filter_falls_back_to_all_meals(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        _create_plan(
            app, "alice@example.com", name="Weeknight soup", favorite=False,
        )

        html = client.get("/meals?filter=unexpected").get_data(as_text=True)

        assert "Weeknight soup" in html
        assert "No pinned meals yet" not in html

    def test_unpinning_from_favorites_redirects_to_the_filtered_view(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        plan_id = _create_plan(
            app, "alice@example.com", name="Pinned pasta", favorite=True,
        )

        response = client.post(
            f"/meal-plan/{plan_id}/favorite",
            data={"meal_filter": "favorites"},
            htmx=True,
        )

        assert response.status_code == 200
        assert response.headers["HX-Redirect"] == "/meals?filter=favorites"
        with app.app_context():
            assert db.session.get(MealPlan, plan_id).is_favorite is False
