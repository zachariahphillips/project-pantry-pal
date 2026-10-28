"""
Phase 14A.1 regression suite — household-shared cooked-meal history.

An actual cook timestamp is recorded only with a confirmed pantry deduction.
It is part of that same single-use Undo transaction, so restoring quantities
also restores the previous cook state.

Tier-1 dev loop:

    pytest tests/test_phase_12a3.py tests/test_phase_14a1.py -q
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from sqlalchemy import inspect

from extensions import db
from models import MealPlan, PantryItem, User
from tests.conftest import Client, sign_up


def _add_pantry(client: Client, name: str, *, quantity: str) -> None:
    response = client.post("/pantry", htmx=True, data={
        "name": name,
        "quantity": quantity,
        "unit": "ea",
        "notes": "",
        "expiry_date": "",
    })
    assert response.status_code in (200, 204)


def _create_plan(app, email: str) -> int:
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        plan = MealPlan(
            household_id=user.household_id,
            created_by_user_id=user.id,
            prompt="Dinner",
            response_json=json.dumps({
                "meal_name": "Test dinner",
                "have": ["Eggs"],
                "need": [],
                "steps": ["Cook it."],
            }),
            meal_name="Test dinner",
        )
        db.session.add(plan)
        db.session.commit()
        return plan.id


def _egg_id(app) -> int:
    with app.app_context():
        return PantryItem.query.filter_by(name="Eggs").one().id


class TestCookedMealHistory:
    def test_confirmed_deduction_marks_the_shared_meal_as_cooked(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Eggs", quantity="6")
        plan_id = _create_plan(app, "alice@example.com")

        response = client.post(
            f"/meal-plan/{plan_id}/deduction-apply",
            data={f"deduction-{_egg_id(app)}": "2"},
            htmx=True,
        )

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'hx-swap-oob="outerHTML"' in html
        assert f'id="meal-plan-cooked-status-{plan_id}"' in html
        assert "Cooked today" in html
        with app.app_context():
            cooked_at = db.session.get(MealPlan, plan_id).cooked_at
            assert cooked_at is not None
            assert cooked_at.date() == datetime.utcnow().date()

        cards_html = client.get("/meals").get_data(as_text=True)
        assert f'id="meal-plan-cooked-status-{plan_id}"' in cards_html
        assert "Cooked today" in cards_html

    def test_undo_clears_a_new_cooked_status_with_the_pantry_restore(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Eggs", quantity="6")
        plan_id = _create_plan(app, "alice@example.com")

        client.post(
            f"/meal-plan/{plan_id}/deduction-apply",
            data={f"deduction-{_egg_id(app)}": "2"},
            htmx=True,
        )
        response = client.post(
            f"/meal-plan/{plan_id}/deduction-undo", htmx=True,
        )

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert f'id="meal-plan-cooked-status-{plan_id}"' in html
        assert 'hx-swap-oob="outerHTML"' in html
        assert "Cooked today" not in html
        with app.app_context():
            assert db.session.get(MealPlan, plan_id).cooked_at is None
            assert db.session.get(PantryItem, _egg_id(app)).quantity == 6

    def test_undo_restores_a_previous_cooked_timestamp(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Eggs", quantity="6")
        plan_id = _create_plan(app, "alice@example.com")
        original_cooked_at = datetime(2026, 10, 1, 18, 30)
        with app.app_context():
            db.session.get(MealPlan, plan_id).cooked_at = original_cooked_at
            db.session.commit()

        client.post(
            f"/meal-plan/{plan_id}/deduction-apply",
            data={f"deduction-{_egg_id(app)}": "2"},
            htmx=True,
        )
        client.post(f"/meal-plan/{plan_id}/deduction-undo", htmx=True)

        with app.app_context():
            assert (
                db.session.get(MealPlan, plan_id).cooked_at
                == original_cooked_at
            )

    def test_undo_does_not_overwrite_newer_cooked_state(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Eggs", quantity="6")
        plan_id = _create_plan(app, "alice@example.com")

        client.post(
            f"/meal-plan/{plan_id}/deduction-apply",
            data={f"deduction-{_egg_id(app)}": "2"},
            htmx=True,
        )
        newer_cooked_at = datetime.utcnow() + timedelta(minutes=1)
        with app.app_context():
            db.session.get(MealPlan, plan_id).cooked_at = newer_cooked_at
            db.session.commit()

        response = client.post(
            f"/meal-plan/{plan_id}/deduction-undo", htmx=True,
        )

        assert response.status_code == 200
        assert "could not undo safely" in response.get_data(as_text=True)
        with app.app_context():
            assert db.session.get(MealPlan, plan_id).cooked_at == newer_cooked_at
            assert db.session.get(PantryItem, _egg_id(app)).quantity == 4

    def test_invalid_deduction_does_not_mark_a_plan_as_cooked(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Eggs", quantity="6")
        plan_id = _create_plan(app, "alice@example.com")

        response = client.post(
            f"/meal-plan/{plan_id}/deduction-apply",
            data={f"deduction-{_egg_id(app)}": "0"},
            htmx=True,
        )

        assert response.status_code == 200
        assert "Choose at least one positive amount" in response.get_data(
            as_text=True,
        )
        with app.app_context():
            assert db.session.get(MealPlan, plan_id).cooked_at is None

    def test_legacy_meal_plans_get_a_nullable_cooked_timestamp_idempotently(
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
                'Legacy dinner', '2026-10-27 00:00:00'
            );
        """)
        connection.commit()
        connection.close()

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
        monkeypatch.setenv("FLASK_SECRET_KEY", "migration-test-secret")
        from app import create_app, _ensure_meal_plan_cooked_at_column

        migrated_app = create_app()
        with migrated_app.app_context():
            columns = {
                column["name"]: column
                for column in inspect(db.engine).get_columns("meal_plans")
            }
            assert "cooked_at" in columns
            assert columns["cooked_at"]["nullable"] is True
            assert db.session.get(MealPlan, 1).cooked_at is None

            _ensure_meal_plan_cooked_at_column()
            _ensure_meal_plan_cooked_at_column()
