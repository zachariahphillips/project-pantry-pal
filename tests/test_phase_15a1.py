"""
Phase 15A.1 regression suite — household-shared cooked meal notes.

Notes are optional reflections on a confirmed cook, not AI prompt context.
They are included in the deduction Undo conflict check so a new note is never
silently overwritten by a stale Undo.

Tier-1 dev loop:

    pytest tests/test_phase_14a1.py tests/test_phase_15a1.py -q
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime

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


def _create_plan(
    app,
    email: str,
    *,
    cooked_at: datetime | None = None,
    cooked_note: str | None = None,
) -> int:
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
            cooked_at=cooked_at,
            cooked_note=cooked_note,
        )
        db.session.add(plan)
        db.session.commit()
        return plan.id


def _egg_id(app) -> int:
    with app.app_context():
        return PantryItem.query.filter_by(name="Eggs").one().id


class TestCookedMealNotes:
    def test_cooked_card_can_save_and_display_a_household_note(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        plan_id = _create_plan(
            app, "alice@example.com", cooked_at=datetime.utcnow(),
        )

        cards_html = client.get("/meals").get_data(as_text=True)
        assert f'id="meal-plan-cooked-note-{plan_id}"' in cards_html
        assert "Add a cook note" in cards_html
        assert f'hx-post="/meal-plan/{plan_id}/cooked-note"' in cards_html

        response = client.post(
            f"/meal-plan/{plan_id}/cooked-note",
            data={"cooked_note": "Use less salt next time."},
            htmx=True,
        )

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert f'id="meal-plan-cooked-note-{plan_id}"' in html
        assert "Cook note:" in html
        assert "Use less salt next time." in html
        assert "<article" not in html
        with app.app_context():
            assert (
                db.session.get(MealPlan, plan_id).cooked_note
                == "Use less salt next time."
            )

        cooked_html = client.get("/meals?filter=cooked").get_data(as_text=True)
        assert "Use less salt next time." in cooked_html

    def test_clear_removes_a_cooked_note(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        plan_id = _create_plan(
            app,
            "alice@example.com",
            cooked_at=datetime.utcnow(),
            cooked_note="Add lemon.",
        )

        response = client.post(
            f"/meal-plan/{plan_id}/cooked-note",
            data={"clear": "1"},
            htmx=True,
        )

        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Add a cook note" in html
        assert "Add lemon." not in html
        with app.app_context():
            assert db.session.get(MealPlan, plan_id).cooked_note is None

    def test_uncooked_plan_cannot_receive_a_cook_note(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        plan_id = _create_plan(app, "alice@example.com")

        response = client.post(
            f"/meal-plan/{plan_id}/cooked-note",
            data={"cooked_note": "Great meal."},
            htmx=True,
        )

        assert response.status_code == 409
        with app.app_context():
            assert db.session.get(MealPlan, plan_id).cooked_note is None

    def test_overlong_note_is_rejected_without_changing_the_existing_note(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        plan_id = _create_plan(
            app,
            "alice@example.com",
            cooked_at=datetime.utcnow(),
            cooked_note="Keep this.",
        )

        response = client.post(
            f"/meal-plan/{plan_id}/cooked-note",
            data={"cooked_note": "x" * 281},
            htmx=True,
        )

        assert response.status_code == 422
        assert "Keep your cooking note to 280 characters or fewer." in (
            response.get_data(as_text=True)
        )
        with app.app_context():
            assert db.session.get(MealPlan, plan_id).cooked_note == "Keep this."

    def test_confirmed_cook_clears_note_and_undo_restores_it(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Eggs", quantity="6")
        plan_id = _create_plan(
            app,
            "alice@example.com",
            cooked_at=datetime(2026, 10, 1, 18, 30),
            cooked_note="Use less salt.",
        )

        applied = client.post(
            f"/meal-plan/{plan_id}/deduction-apply",
            data={f"deduction-{_egg_id(app)}": "2"},
            htmx=True,
        )

        assert applied.status_code == 200
        applied_html = applied.get_data(as_text=True)
        assert 'hx-swap-oob="outerHTML"' in applied_html
        assert "Add a cook note" in applied_html
        assert "Use less salt." not in applied_html
        with app.app_context():
            assert db.session.get(MealPlan, plan_id).cooked_note is None

        undone = client.post(
            f"/meal-plan/{plan_id}/deduction-undo", htmx=True,
        )

        assert undone.status_code == 200
        assert "Use less salt." in undone.get_data(as_text=True)
        with app.app_context():
            assert (
                db.session.get(MealPlan, plan_id).cooked_note
                == "Use less salt."
            )

    def test_undo_does_not_overwrite_a_newer_cook_note(
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
        client.post(
            f"/meal-plan/{plan_id}/cooked-note",
            data={"cooked_note": "Roommate added this note."},
            htmx=True,
        )

        response = client.post(
            f"/meal-plan/{plan_id}/deduction-undo", htmx=True,
        )

        assert response.status_code == 200
        assert "could not undo safely" in response.get_data(as_text=True)
        with app.app_context():
            plan = db.session.get(MealPlan, plan_id)
            assert plan.cooked_note == "Roommate added this note."
            assert db.session.get(PantryItem, _egg_id(app)).quantity == 4

    def test_legacy_meal_plans_gain_a_nullable_cooked_note_idempotently(
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
                'Legacy dinner', '2026-10-30 00:00:00'
            );
        """)
        connection.commit()
        connection.close()

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
        monkeypatch.setenv("FLASK_SECRET_KEY", "migration-test-secret")
        from app import create_app, _ensure_meal_plan_cooked_note_column

        migrated_app = create_app()
        with migrated_app.app_context():
            columns = {
                column["name"]: column
                for column in inspect(db.engine).get_columns("meal_plans")
            }
            assert "cooked_note" in columns
            assert columns["cooked_note"]["nullable"] is True
            assert db.session.get(MealPlan, 1).cooked_note is None

            _ensure_meal_plan_cooked_note_column()
            _ensure_meal_plan_cooked_note_column()
