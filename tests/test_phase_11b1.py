"""
Phase 11B.1 regression suite — manual low-stock foundation.

The persisted manual restock flag is intentionally distinct from Phase 4C's
quantity-derived "Low" heuristic. It lets a later one-tap control flag
unmeasured staples without changing the existing automatic filter.

Tier-1 dev loop:

    pytest tests/test_phase_11b1.py -q
"""
from __future__ import annotations

import sqlite3

from sqlalchemy import inspect

from tests.conftest import Client, sign_up


def _add_pantry(client: Client, name: str) -> None:
    response = client.post("/pantry", htmx=True, data={
        "name": name,
        "quantity": "",
        "unit": "",
        "notes": "",
        "expiry_date": "",
    })
    assert response.status_code in (200, 204)


class TestManualLowStockFoundation:
    def test_new_pantry_items_default_to_not_manually_flagged(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Olive oil")

        with app.app_context():
            from extensions import db
            from models import PantryItem

            item = PantryItem.query.filter_by(name="Olive oil").one()
            assert item.low_stock is False

            item.low_stock = True
            db.session.commit()
            assert db.session.get(PantryItem, item.id).low_stock is True

    def test_legacy_pantry_table_gets_low_stock_with_safe_default(
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
                expiry_date DATE,
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
            INSERT INTO pantry_items (
                id, user_id, household_id, name, added_at
            ) VALUES (1, 1, 1, 'Olive oil', '2026-10-07 00:00:00');
        """)
        connection.commit()
        connection.close()

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
        monkeypatch.setenv("FLASK_SECRET_KEY", "migration-test-secret")

        from app import create_app, _ensure_pantry_low_stock_column
        from extensions import db
        from models import PantryItem

        migrated_app = create_app()
        with migrated_app.app_context():
            columns = {
                column["name"]: column
                for column in inspect(db.engine).get_columns("pantry_items")
            }
            assert "low_stock" in columns
            assert columns["low_stock"]["nullable"] is False
            assert db.session.get(PantryItem, 1).low_stock is False

            _ensure_pantry_low_stock_column()
            _ensure_pantry_low_stock_column()
