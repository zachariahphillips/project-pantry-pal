"""
Phase 13A.1 regression suite — schedule a saved meal.

This foundation stores an optional household-visible cook date. It does not
introduce a calendar or alter meal-list ordering; unscheduled plans retain
their current behavior.

Tier-1 dev loop:

    pytest tests/test_phase_13a1.py -q
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

from sqlalchemy import inspect

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


class TestMealPlanScheduling:
    def test_unscheduled_card_renders_a_compact_schedule_control(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        plan_id = _create_plan(app, "alice@example.com")

        html = client.get("/meals").get_data(as_text=True)

        assert f'id="meal-plan-schedule-{plan_id}"' in html
        assert f'hx-post="/meal-plan/{plan_id}/schedule"' in html
        assert f'id="meal-plan-planned-for-{plan_id}"' in html
        assert 'name="planned_for"' in html
        assert "Plan for" in html
        assert "Schedule" in html

    def test_scheduling_a_meal_updates_only_its_date_control_and_persists(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        plan_id = _create_plan(app, "alice@example.com")
        planned_for = date.today() + timedelta(days=3)

        response = client.post(
            f"/meal-plan/{plan_id}/schedule",
            data={"planned_for": planned_for.isoformat()},
            htmx=True,
        )

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert f'id="meal-plan-schedule-{plan_id}"' in html
        assert f'value="{planned_for.isoformat()}"' in html
        assert "Update" in html
        assert "Clear" in html
        assert "<article" not in html
        with app.app_context():
            assert db.session.get(MealPlan, plan_id).planned_for == planned_for

    def test_clear_schedule_returns_plan_to_unscheduled_state(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        plan_id = _create_plan(app, "alice@example.com")
        with app.app_context():
            db.session.get(MealPlan, plan_id).planned_for = date.today()
            db.session.commit()

        response = client.post(
            f"/meal-plan/{plan_id}/schedule",
            data={"clear": "1"},
            htmx=True,
        )

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Schedule" in html
        assert "Clear" not in html
        with app.app_context():
            assert db.session.get(MealPlan, plan_id).planned_for is None

    def test_invalid_or_past_schedule_is_rejected_without_mutating(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        plan_id = _create_plan(app, "alice@example.com")

        for raw_date, message in (
            ("not-a-date", "Choose a valid date"),
            (
                (date.today() - timedelta(days=1)).isoformat(),
                "Choose today or a future date",
            ),
        ):
            response = client.post(
                f"/meal-plan/{plan_id}/schedule",
                data={"planned_for": raw_date},
                htmx=True,
            )
            assert response.status_code == 422
            assert message in response.get_data(as_text=True)

        with app.app_context():
            assert db.session.get(MealPlan, plan_id).planned_for is None

    def test_another_household_cannot_schedule_a_meal(
        self, two_clients, app,
    ):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        plan_id = _create_plan(app, "alice@example.com")
        sign_up(bob, "bob@example.com", "Bob")

        response = bob.post(
            f"/meal-plan/{plan_id}/schedule",
            data={"planned_for": (date.today() + timedelta(days=1)).isoformat()},
            htmx=True,
        )

        assert response.status_code == 404
        with app.app_context():
            assert db.session.get(MealPlan, plan_id).planned_for is None

    def test_anonymous_schedule_redirects_to_login(self, client, app):
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

        response = client.post(f"/meal-plan/{plan_id}/schedule", htmx=True)

        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_legacy_meal_plans_gain_a_nullable_schedule_date_idempotently(
        self, tmp_path, monkeypatch,
    ):
        db_file = tmp_path / "legacy.sqlite3"
        connection = sqlite3.connect(db_file)
        connection.executescript("""
            CREATE TABLE meal_plans (
                id INTEGER PRIMARY KEY,
                household_id INTEGER NOT NULL,
                created_by_user_id INTEGER NOT NULL,
                prompt TEXT NOT NULL,
                response_json TEXT NOT NULL,
                meal_name VARCHAR(200) NOT NULL,
                created_at DATETIME NOT NULL
            );
            INSERT INTO meal_plans (
                id, household_id, created_by_user_id, prompt, response_json,
                meal_name, created_at
            ) VALUES (
                1, 1, 1, 'Dinner',
                '{"meal_name":"Legacy dinner","have":[],"need":[],"steps":[]}',
                'Legacy dinner', '2026-10-25 00:00:00'
            );
        """)
        connection.commit()
        connection.close()

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
        monkeypatch.setenv("FLASK_SECRET_KEY", "migration-test-secret")
        from app import create_app, _ensure_meal_plan_planned_for_column

        migrated_app = create_app()
        with migrated_app.app_context():
            columns = {
                column["name"]: column
                for column in inspect(db.engine).get_columns("meal_plans")
            }
            assert "planned_for" in columns
            assert columns["planned_for"]["nullable"] is True
            assert db.session.get(MealPlan, 1).planned_for is None

            _ensure_meal_plan_planned_for_column()
            _ensure_meal_plan_planned_for_column()
