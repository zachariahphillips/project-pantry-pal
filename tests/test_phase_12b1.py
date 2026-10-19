"""
Phase 12B.1 regression suite — household-shared favorite foundation.

This slice adds only durable data. Pin/unpin controls and Favorites filtering
ship separately, after old SQLite databases can safely load the new model.

Tier-1 dev loop:

    pytest tests/test_phase_12b1.py -q
"""
from __future__ import annotations

import json
import sqlite3

from sqlalchemy import inspect

from extensions import db
from models import MealPlan, User
from tests.conftest import sign_up


class TestMealPlanFavoriteFoundation:
    def test_new_meal_plans_default_to_not_favorited_and_persist(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        with app.app_context():
            user = User.query.filter_by(email="alice@example.com").one()
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

            assert db.session.get(MealPlan, plan.id).is_favorite is False

            plan.is_favorite = True
            db.session.commit()
            assert db.session.get(MealPlan, plan.id).is_favorite is True

    def test_legacy_meal_plan_table_gets_safe_favorite_default(
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
                'Legacy dinner', '2026-10-18 00:00:00'
            );
        """)
        connection.commit()
        connection.close()

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
        monkeypatch.setenv("FLASK_SECRET_KEY", "migration-test-secret")

        from app import create_app, _ensure_meal_plan_is_favorite_column

        migrated_app = create_app()
        with migrated_app.app_context():
            columns = {
                column["name"]: column
                for column in inspect(db.engine).get_columns("meal_plans")
            }
            assert "is_favorite" in columns
            assert columns["is_favorite"]["nullable"] is False
            assert db.session.get(MealPlan, 1).is_favorite is False

            _ensure_meal_plan_is_favorite_column()
            _ensure_meal_plan_is_favorite_column()
