"""
Phase 12C.3 regression suite — household dietary defaults.

Saving is explicit: a meal request can differ from the household defaults
without changing them. A saved choice is shared by the household and becomes
the checked state for the next planner form.

Tier-1 dev loop:

    pytest tests/test_phase_12c3.py -q
"""
from __future__ import annotations

import json
import re
import sqlite3

from sqlalchemy import inspect

from extensions import db
from models import Household, User
from tests.conftest import sign_up


PLAN = {
    "meal_name": "Test dinner",
    "have": [],
    "need": [],
    "steps": ["Cook it."],
}


def _add_pantry(client, name: str) -> None:
    response = client.post("/pantry", htmx=True, data={
        "name": name,
        "quantity": "",
        "unit": "",
        "notes": "",
        "expiry_date": "",
    })
    assert response.status_code in (200, 204)


def _diet_chip_is_checked(html: str, value: str) -> bool:
    match = re.search(
        rf'<input\s+type="checkbox"\s+name="dietary_preferences"\s+'
        rf'value="{value}"(?P<attributes>[^>]*)>',
        html,
    )
    assert match, f"Could not find dietary chip for {value!r}."
    return "checked" in match.group("attributes")


class TestHouseholdDietaryDefaults:
    def test_saved_defaults_preselect_the_next_planner_request(
        self, client, app, monkeypatch,
    ):
        captured = {}

        def fake_openai(prompt, pantry, servings=2, dietary_preferences=()):
            captured["diets"] = dietary_preferences
            return PLAN, None

        monkeypatch.setattr("app._ask_openai_for_meal", fake_openai)
        sign_up(client, "alice@example.com", "Alice")

        response = client.post(
            "/meal-plan",
            data={
                "prompt": "dinner",
                "dietary_preferences": ["vegetarian", "gluten_free"],
                "save_dietary_preferences": "1",
            },
            htmx=True,
        )

        assert response.status_code == 200
        assert captured["diets"] == ("vegetarian", "gluten_free")
        with app.app_context():
            household = Household.query.one()
            assert household.dietary_preferences_json == json.dumps([
                "vegetarian", "gluten_free",
            ])

        for name in ("Pasta", "Eggs", "Olive oil"):
            _add_pantry(client, name)
        html = client.get("/pantry").get_data(as_text=True)

        assert _diet_chip_is_checked(html, "vegetarian") is True
        assert _diet_chip_is_checked(html, "gluten_free") is True
        assert 'name="save_dietary_preferences"' in html
        assert "Save these as household defaults" in html

    def test_one_off_diets_do_not_overwrite_household_defaults(
        self, client, app, monkeypatch,
    ):
        monkeypatch.setattr(
            "app._ask_openai_for_meal", lambda *_args: (PLAN, None),
        )
        sign_up(client, "alice@example.com", "Alice")
        with app.app_context():
            household = Household.query.one()
            household.dietary_preferences_json = json.dumps(["gluten_free"])
            db.session.commit()

        response = client.post(
            "/meal-plan",
            data={
                "prompt": "one-off vegetarian dinner",
                "dietary_preferences": ["vegetarian"],
            },
            htmx=True,
        )

        assert response.status_code == 200
        with app.app_context():
            assert Household.query.one().dietary_preferences_json == json.dumps(
                ["gluten_free"],
            )

    def test_explicit_save_with_no_dietary_chips_clears_defaults(
        self, client, app, monkeypatch,
    ):
        monkeypatch.setattr(
            "app._ask_openai_for_meal", lambda *_args: (PLAN, None),
        )
        sign_up(client, "alice@example.com", "Alice")
        with app.app_context():
            household = Household.query.one()
            household.dietary_preferences_json = json.dumps(["vegetarian"])
            db.session.commit()

        response = client.post(
            "/meal-plan",
            data={
                "prompt": "dinner",
                "save_dietary_preferences": "1",
            },
            htmx=True,
        )

        assert response.status_code == 200
        with app.app_context():
            assert Household.query.one().dietary_preferences_json == "[]"

    def test_malformed_saved_data_is_not_rendered_as_a_default(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        with app.app_context():
            household = Household.query.one()
            household.dietary_preferences_json = '["vegan"]'
            db.session.commit()
        for name in ("Pasta", "Eggs", "Olive oil"):
            _add_pantry(client, name)

        html = client.get("/pantry").get_data(as_text=True)

        assert _diet_chip_is_checked(html, "vegetarian") is False
        assert _diet_chip_is_checked(html, "gluten_free") is False

    def test_defaults_do_not_leak_between_households(
        self, two_clients, app, monkeypatch,
    ):
        alice, bob = two_clients
        monkeypatch.setattr(
            "app._ask_openai_for_meal", lambda *_args: (PLAN, None),
        )
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")

        response = alice.post(
            "/meal-plan",
            data={
                "prompt": "dinner",
                "dietary_preferences": ["vegetarian"],
                "save_dietary_preferences": "1",
            },
            htmx=True,
        )
        assert response.status_code == 200

        with app.app_context():
            alice = User.query.filter_by(email="alice@example.com").one()
            bob = User.query.filter_by(email="bob@example.com").one()
            assert alice.household.dietary_preferences_json == json.dumps(
                ["vegetarian"],
            )
            assert bob.household.dietary_preferences_json == "[]"

    def test_legacy_households_get_an_empty_default_idempotently(
        self, tmp_path, monkeypatch,
    ):
        db_file = tmp_path / "legacy.sqlite3"
        connection = sqlite3.connect(db_file)
        connection.executescript("""
            CREATE TABLE households (
                id INTEGER PRIMARY KEY,
                name VARCHAR(120) NOT NULL,
                created_at DATETIME NOT NULL
            );
            INSERT INTO households (id, name, created_at) VALUES (
                1, 'Legacy home', '2026-10-22 00:00:00'
            );
        """)
        connection.commit()
        connection.close()

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
        monkeypatch.setenv("FLASK_SECRET_KEY", "migration-test-secret")
        from app import create_app, _ensure_household_dietary_preferences_column

        migrated_app = create_app()
        with migrated_app.app_context():
            columns = {
                column["name"]: column
                for column in inspect(db.engine).get_columns("households")
            }
            assert "dietary_preferences_json" in columns
            assert columns["dietary_preferences_json"]["nullable"] is False
            assert db.session.get(Household, 1).dietary_preferences_json == "[]"

            _ensure_household_dietary_preferences_column()
            _ensure_household_dietary_preferences_column()
