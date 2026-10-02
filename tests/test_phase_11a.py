"""
Phase 11A.1 regression suite — pantry expiry-date foundation.

This first expiry slice adds an optional date to pantry CRUD, preserves it
through duplicate merge and delete/undo, and lazy-migrates installed SQLite
databases. Urgency colors and AI prompts intentionally belong to later slices.

Tier-1 dev loop:

    pytest tests/test_phase_11a.py -q
"""
from __future__ import annotations

import re
import sqlite3
from datetime import date

from sqlalchemy import inspect

from tests.conftest import Client, sign_up


def _add_pantry(
    client: Client,
    name: str,
    *,
    expiry_date: str = "",
    quantity: str = "",
) -> None:
    response = client.post("/pantry", htmx=True, data={
        "name": name,
        "quantity": quantity,
        "unit": "",
        "notes": "",
        "expiry_date": expiry_date,
    })
    assert response.status_code in (200, 204)


def _pantry_id(html: str, name: str) -> int:
    for match in re.finditer(r'id="pantry-item-(\d+)"(.*?)(?=id="pantry-item-|\Z)', html, re.DOTALL):
        if name in match.group(2):
            return int(match.group(1))
    raise AssertionError(f"Could not find pantry item {name!r}")


class TestExpiryDateFormBoundary:
    def test_expiry_belongs_to_pantry_form_not_shopping_form(self, app):
        with app.test_request_context():
            from forms import PantryItemForm, ShoppingItemForm

            assert "expiry_date" in PantryItemForm()._fields
            assert "expiry_date" not in ShoppingItemForm()._fields

    def test_add_renders_expiry_date_on_pantry_row(self, client):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Milk", expiry_date="2099-10-05")

        html = client.get("/pantry").get_data(as_text=True)
        assert 'name="expiry_date"' in html
        assert "Expires" in html
        assert "Expires Oct 5, 2099" in html
        assert 'datetime="2099-10-05"' in html

    def test_edit_round_trip_updates_and_clears_expiry_date(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Milk", expiry_date="2099-10-05")
        item_id = _pantry_id(client.get("/pantry").get_data(as_text=True), "Milk")

        edit_html = client.get(
            f"/pantry/{item_id}/edit", htmx=True,
        ).get_data(as_text=True)
        assert 'type="date"' in edit_html
        assert 'value="2099-10-05"' in edit_html

        response = client.put(f"/pantry/{item_id}", data={
            "name": "Milk",
            "quantity": "",
            "unit": "",
            "notes": "",
            "expiry_date": "2099-10-07",
        })
        assert response.status_code == 200
        assert "Expires Oct 7, 2099" in response.get_data(as_text=True)

        response = client.put(f"/pantry/{item_id}", data={
            "name": "Milk",
            "quantity": "",
            "unit": "",
            "notes": "",
            "expiry_date": "",
        })
        assert response.status_code == 200
        assert "Expires" not in response.get_data(as_text=True)

        with app.app_context():
            from extensions import db
            from models import PantryItem

            assert db.session.get(PantryItem, item_id).expiry_date is None

    def test_invalid_expiry_date_is_a_validation_error(self, client):
        sign_up(client, "alice@example.com", "Alice")
        response = client.post("/pantry", htmx=True, data={
            "name": "Milk",
            "quantity": "",
            "unit": "",
            "notes": "",
            "expiry_date": "not-a-date",
        })

        assert response.status_code == 422
        assert response.headers["HX-Retarget"] == "#add-form-errors"


class TestExpiryDateLifecycle:
    def test_duplicate_merge_keeps_earliest_expiry_date(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Milk", expiry_date="2026-10-10")
        page = client.get("/pantry").get_data(as_text=True)
        item_id = _pantry_id(page, "Milk")

        response = client.post("/pantry", htmx=True, data={
            "name": "Milk",
            "quantity": "",
            "unit": "",
            "notes": "",
            "expiry_date": "2026-10-05",
        })
        assert response.status_code == 200
        confirmation = response.get_data(as_text=True)
        assert 'name="expiry_date"' in confirmation
        assert 'value="2026-10-05"' in confirmation

        response = client.post(f"/pantry/merge/{item_id}", htmx=True, data={
            "name": "Milk",
            "quantity": "",
            "unit": "",
            "notes": "",
            "expiry_date": "2026-10-05",
        })
        assert response.status_code == 200

        with app.app_context():
            from extensions import db
            from models import PantryItem

            assert db.session.get(PantryItem, item_id).expiry_date == date(2026, 10, 5)

    def test_delete_undo_preserves_expiry_date(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        for name in ("Milk", "Rice", "Salt", "Garlic", "Onion"):
            _add_pantry(
                client, name,
                expiry_date="2026-10-05" if name == "Milk" else "",
            )
        item_id = _pantry_id(client.get("/pantry").get_data(as_text=True), "Milk")

        response = client.delete(f"/pantry/{item_id}", htmx=True)
        assert response.status_code == 200
        response = client.post("/pantry/undo", htmx=True)
        assert response.status_code == 200

        with app.app_context():
            from extensions import db
            from models import PantryItem

            restored = PantryItem.query.filter_by(name="Milk").one()
            assert restored.expiry_date == date(2026, 10, 5)


class TestExpiryDateMigration:
    def test_legacy_pantry_table_gets_nullable_expiry_date(
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
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                name VARCHAR(120) NOT NULL,
                household_id INTEGER REFERENCES households(id),
                created_at DATETIME NOT NULL
            );
            CREATE TABLE pantry_items (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                household_id INTEGER REFERENCES households(id),
                name VARCHAR(120) NOT NULL,
                quantity FLOAT,
                unit VARCHAR(40),
                notes VARCHAR(280),
                added_at DATETIME NOT NULL
            );
            CREATE TABLE shopping_items (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                household_id INTEGER REFERENCES households(id),
                name VARCHAR(120) NOT NULL,
                quantity FLOAT,
                unit VARCHAR(40),
                notes VARCHAR(280),
                checked BOOLEAN NOT NULL DEFAULT 0,
                added_at DATETIME NOT NULL,
                checked_at DATETIME
            );
        """)
        connection.commit()
        connection.close()

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
        monkeypatch.setenv("FLASK_SECRET_KEY", "migration-test-secret")

        from app import create_app, _ensure_pantry_expiry_date_column
        from extensions import db

        migrated_app = create_app()
        with migrated_app.app_context():
            columns = {
                column["name"]
                for column in inspect(db.engine).get_columns("pantry_items")
            }
            assert "expiry_date" in columns
            _ensure_pantry_expiry_date_column()
            _ensure_pantry_expiry_date_column()
