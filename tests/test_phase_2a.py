"""
Phase 2A regression suite — households, ownership semantics, provenance.

Covers the new behavior added on top of Phase 1C:
- Signup auto-creates a household-of-one
- Items carry both household_id (ownership) and added_by_user_id (provenance)
- Multiple users in the SAME household see each other's items (the multi-user
  payoff). Phase 2B builds the invite UI; here we manipulate the DB directly
  to set up that scenario.
- A member who didn't add an item can still edit/delete it (ownership now
  follows the household, not the original adder)
- "Added by [name]" stamp shows in the rendered HTML when added_by !=
  current_user, and is hidden otherwise (avoids noise in solo households)
- +Shop preserves provenance correctly (the cross-link's added_by_user_id is
  the user who tapped, not the original pantry adder)
- Migration is idempotent: pre-Phase-2A rows (household_id NULL) get
  backfilled on next startup; subsequent boots are no-ops
"""
from __future__ import annotations

import re

import pytest

from tests.conftest import Client, id_for, sign_up


# ---------------------------------------------------------------------------
# Signup -> auto-household
# ---------------------------------------------------------------------------

class TestSignupCreatesHousehold:
    def test_signup_assigns_a_household(self, app, client: Client):
        sign_up(client, "alice@example.com", "Alice Doe")
        with app.app_context():
            from models import User
            alice = User.query.filter_by(email="alice@example.com").first()
            assert alice.household_id is not None
            assert alice.household is not None

    def test_household_name_uses_first_name(self, app, client: Client):
        sign_up(client, "alice@example.com", "Alice Doe")
        with app.app_context():
            from models import User
            alice = User.query.filter_by(email="alice@example.com").first()
            assert alice.household.name == "Alice's home"

    def test_two_signups_create_two_households(self, app, two_clients):
        a, b = two_clients
        sign_up(a, "alice@example.com", "Alice")
        sign_up(b, "bob@example.com", "Bob")
        with app.app_context():
            from models import User
            alice = User.query.filter_by(email="alice@example.com").first()
            bob = User.query.filter_by(email="bob@example.com").first()
            assert alice.household_id != bob.household_id


# ---------------------------------------------------------------------------
# Items get household_id + added_by_user_id on create
# ---------------------------------------------------------------------------

class TestItemProvenance:
    def test_pantry_add_sets_household_and_added_by(self, app, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        client.post("/pantry", data={"name": "Olive oil", "submit": "Add"}, htmx=True)
        with app.app_context():
            from models import PantryItem, User
            alice = User.query.filter_by(email="alice@example.com").first()
            item = PantryItem.query.filter_by(name="Olive oil").first()
            assert item.household_id == alice.household_id
            assert item.added_by_user_id == alice.id

    def test_shopping_add_sets_household_and_added_by(self, app, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        client.post("/shopping", data={"name": "Milk", "submit": "Add"}, htmx=True)
        with app.app_context():
            from models import ShoppingItem, User
            alice = User.query.filter_by(email="alice@example.com").first()
            item = ShoppingItem.query.filter_by(name="Milk").first()
            assert item.household_id == alice.household_id
            assert item.added_by_user_id == alice.id


# ---------------------------------------------------------------------------
# Shared household: the multi-user payoff
# ---------------------------------------------------------------------------

class TestSharedHousehold:
    """No invite UI yet (Phase 2B). Directly stitch bob into alice's
    household via the DB and verify the household-scoped behaviors."""

    @pytest.fixture
    def shared(self, app, two_clients):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")
        with app.app_context():
            from extensions import db
            from models import User
            alice_db = User.query.filter_by(email="alice@example.com").first()
            bob_db = User.query.filter_by(email="bob@example.com").first()
            # Drop the household-of-one bob got at signup and put him in
            # alice's household. (Phase 2B's invite flow will do this cleanly.)
            bob_db.household_id = alice_db.household_id
            db.session.commit()
        return {"alice": alice, "bob": bob}

    def test_bob_sees_alices_pantry_items(self, shared):
        alice, bob = shared["alice"], shared["bob"]
        alice.post("/pantry", data={"name": "Olive oil", "submit": "Add"}, htmx=True)
        body = bob.get("/pantry").get_data(as_text=True)
        assert "Olive oil" in body, "shared household should expose alice's items to bob"

    def test_bob_can_edit_alices_pantry_item(self, shared):
        alice, bob = shared["alice"], shared["bob"]
        alice.post("/pantry", data={"name": "Olive oil", "submit": "Add"}, htmx=True)
        body = alice.get("/pantry").get_data(as_text=True)
        olive_id = id_for(body, "Olive oil", "pantry-item")
        resp = bob.put(f"/pantry/{olive_id}", data={
            "name": "EVOO", "submit": "Save",
        })
        assert resp.status_code == 200
        assert "EVOO" in resp.get_data(as_text=True)

    def test_bob_can_delete_alices_pantry_item(self, shared):
        alice, bob = shared["alice"], shared["bob"]
        alice.post("/pantry", data={"name": "Olive oil", "submit": "Add"}, htmx=True)
        body = alice.get("/pantry").get_data(as_text=True)
        olive_id = id_for(body, "Olive oil", "pantry-item")
        resp = bob.delete(f"/pantry/{olive_id}")
        assert resp.status_code == 200
        # Bob's list is alice's list; the item is gone for both.
        assert "Olive oil" not in alice.get("/pantry").get_data(as_text=True)

    def test_bob_can_check_off_alices_shopping_item(self, shared):
        alice, bob = shared["alice"], shared["bob"]
        alice.post("/shopping", data={"name": "Tortillas", "submit": "Add"}, htmx=True)
        body = alice.get("/shopping").get_data(as_text=True)
        tort_id = id_for(body, "Tortillas", "shopping-item")
        resp = bob.post(f"/shopping/{tort_id}/toggle", htmx=True)
        assert resp.status_code == 200
        # Alice sees the strikethrough now too.
        body = alice.get("/shopping").get_data(as_text=True)
        tort_block = re.search(
            rf'id="shopping-item-{tort_id}".*?(?=id="shopping-item-|$)',
            body, re.DOTALL).group(0)
        assert "line-through" in tort_block


# ---------------------------------------------------------------------------
# "Added by [name]" stamp visibility
# ---------------------------------------------------------------------------

class TestAddedByStamp:
    def test_solo_household_hides_added_by_stamp(self, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        client.post("/pantry", data={"name": "Olive oil", "submit": "Add"}, htmx=True)
        body = client.get("/pantry").get_data(as_text=True)
        assert "added by" not in body, "solo household shouldn't show 'added by you' noise"

    def test_shared_household_shows_added_by_for_others(self, app, two_clients):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")
        with app.app_context():
            from extensions import db
            from models import User
            alice_db = User.query.filter_by(email="alice@example.com").first()
            bob_db = User.query.filter_by(email="bob@example.com").first()
            bob_db.household_id = alice_db.household_id
            db.session.commit()

        alice.post("/pantry", data={"name": "Olive oil", "submit": "Add"}, htmx=True)
        # Bob sees the stamp because alice (not him) added it
        body = bob.get("/pantry").get_data(as_text=True)
        assert "added by Alice" in body

        # Alice does NOT see the stamp on her own item
        body = alice.get("/pantry").get_data(as_text=True)
        assert "added by" not in body


# ---------------------------------------------------------------------------
# Cross-link (+ Shop) provenance
# ---------------------------------------------------------------------------

class TestCrossLinkProvenance:
    """Alice adds an item to pantry; Bob taps +Shop. The shopping row's
    added_by should be BOB (he was the one shopping), not Alice (she
    just put it in the pantry)."""

    def test_plus_shop_records_tapper_as_added_by(self, app, two_clients):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")
        with app.app_context():
            from extensions import db
            from models import User
            a = User.query.filter_by(email="alice@example.com").first()
            b = User.query.filter_by(email="bob@example.com").first()
            b.household_id = a.household_id
            db.session.commit()
            alice_id, bob_id = a.id, b.id

        alice.post("/pantry", data={"name": "Olive oil", "submit": "Add"}, htmx=True)
        body = alice.get("/pantry").get_data(as_text=True)
        olive_pantry_id = id_for(body, "Olive oil", "pantry-item")

        resp = bob.post(f"/pantry/{olive_pantry_id}/add-to-shopping", htmx=True)
        assert resp.status_code == 200

        with app.app_context():
            from models import ShoppingItem
            shop_item = ShoppingItem.query.filter_by(name="Olive oil").first()
            assert shop_item is not None
            assert shop_item.added_by_user_id == bob_id, (
                "the tapper, not the original pantry adder, should be added_by"
            )


# ---------------------------------------------------------------------------
# Migration idempotence
# ---------------------------------------------------------------------------

class TestMigration:
    """Realistic upgrade-path test: build a Phase-1C-shaped SQLite file
    BY HAND (no households table, no household_id columns on users / items,
    DB column name still `user_id` for ownership), then boot create_app()
    against it and verify the Phase 2A migration ALTER-TABLEs in the new
    columns AND backfills the data. Second boot is a no-op."""

    def test_phase_1c_db_is_migrated_in_place(self, tmp_path, monkeypatch):
        import sqlite3
        db_file = tmp_path / "legacy.sqlite3"

        # 1. Construct the Phase 1C schema by hand. This is the schema
        #    Riah's real dev DB had before Phase 2A landed.
        con = sqlite3.connect(db_file)
        con.executescript("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                name VARCHAR(120) NOT NULL,
                created_at DATETIME NOT NULL
            );
            CREATE TABLE pantry_items (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                name VARCHAR(120) NOT NULL,
                quantity FLOAT,
                unit VARCHAR(40),
                notes VARCHAR(280),
                added_at DATETIME NOT NULL
            );
            CREATE TABLE shopping_items (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                name VARCHAR(120) NOT NULL,
                quantity FLOAT,
                unit VARCHAR(40),
                notes VARCHAR(280),
                checked BOOLEAN NOT NULL DEFAULT 0,
                added_at DATETIME NOT NULL
            );
            INSERT INTO users (id, email, password_hash, name, created_at)
                VALUES (1, 'legacy@example.com', 'placeholder', 'Legacy User', '2026-01-01');
            INSERT INTO pantry_items (id, user_id, name, added_at)
                VALUES (1, 1, 'Legacy pantry', '2026-01-01');
            INSERT INTO shopping_items (id, user_id, name, checked, added_at)
                VALUES (1, 1, 'Legacy shopping', 0, '2026-01-01');
        """)
        con.commit()
        con.close()

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
        monkeypatch.setenv("FLASK_SECRET_KEY", "smoke-test-secret")

        # 2. Boot create_app() — this should ALTER-TABLE in the new
        #    columns, create the households table, and backfill.
        from app import create_app, _run_phase_2a_migration
        app1 = create_app()
        with app1.app_context():
            from extensions import db
            from models import PantryItem, ShoppingItem, User

            legacy = db.session.get(User, 1)
            assert legacy is not None, "migration shouldn't lose users"
            assert legacy.household_id is not None, (
                "user.household_id column should have been added AND backfilled"
            )
            assert legacy.household.name == "Legacy's home"

            p = PantryItem.query.filter_by(name="Legacy pantry").one()
            s = ShoppingItem.query.filter_by(name="Legacy shopping").one()
            assert p.household_id == legacy.household_id
            assert s.household_id == legacy.household_id
            assert p.added_by_user_id == 1
            assert s.added_by_user_id == 1

            saved_household_id = legacy.household_id

        # 3. Idempotence: a second boot does nothing destructive.
        app2 = create_app()
        with app2.app_context():
            from models import User
            legacy = db.session.get(User, 1)
            assert legacy.household_id == saved_household_id
            _run_phase_2a_migration()  # call directly too, just to be sure
            assert db.session.get(User, 1).household_id == saved_household_id
