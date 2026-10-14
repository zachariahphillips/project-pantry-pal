"""
Phase 11C.1 regression suite — shopping-category foundation.

Categories begin as nullable data only. Existing items stay uncategorized
until the later grouping and classification slices deliberately assign labels.

Tier-1 dev loop:

    pytest tests/test_phase_11c1.py -q
"""
from __future__ import annotations

import sqlite3

from sqlalchemy import inspect

from tests.conftest import Client, id_for, sign_up


def _add_shopping(client: Client, name: str) -> None:
    response = client.post("/shopping", htmx=True, data={
        "name": name,
        "quantity": "",
        "unit": "",
        "notes": "",
    })
    assert response.status_code in (200, 204)


class TestShoppingCategoryFoundation:
    def test_unknown_shopping_items_start_uncategorized_and_persist_labels(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Specialty spice blend")

        with app.app_context():
            from extensions import db
            from models import ShoppingItem

            item = ShoppingItem.query.filter_by(
                name="Specialty spice blend",
            ).one()
            assert item.category is None

            item.category = "Dairy"
            db.session.commit()
            assert db.session.get(ShoppingItem, item.id).category == "Dairy"

    def test_shopping_delete_undo_preserves_a_category(
        self, client, app,
    ):
        sign_up(client, "undo@example.com", "Undo")
        _add_shopping(client, "Milk")
        item_id = id_for(
            client.get("/shopping").get_data(as_text=True),
            "Milk",
            "shopping-item",
        )
        assert item_id is not None

        with app.app_context():
            from extensions import db
            from models import ShoppingItem

            item = db.session.get(ShoppingItem, int(item_id))
            item.category = "Dairy"
            db.session.commit()

        response = client.delete(f"/shopping/{item_id}")
        assert response.status_code == 200
        response = client.post("/shopping/undo", htmx=True)
        assert response.status_code == 200

        with app.app_context():
            from models import ShoppingItem

            restored = ShoppingItem.query.filter_by(name="Milk").one()
            assert restored.category == "Dairy"

    def test_legacy_shopping_table_gets_nullable_category(self, tmp_path, monkeypatch):
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
                expiry_date DATE,
                low_stock BOOLEAN NOT NULL DEFAULT 0,
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
            INSERT INTO shopping_items (
                id, user_id, household_id, name, added_at
            ) VALUES (1, 1, 1, 'Milk', '2026-10-12 00:00:00');
        """)
        connection.commit()
        connection.close()

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
        monkeypatch.setenv("FLASK_SECRET_KEY", "migration-test-secret")

        from app import create_app, _ensure_shopping_category_column
        from extensions import db
        from models import ShoppingItem

        migrated_app = create_app()
        with migrated_app.app_context():
            columns = {
                column["name"]: column
                for column in inspect(db.engine).get_columns("shopping_items")
            }
            assert "category" in columns
            assert columns["category"]["nullable"] is True
            assert db.session.get(ShoppingItem, 1).category is None

            _ensure_shopping_category_column()
            _ensure_shopping_category_column()
