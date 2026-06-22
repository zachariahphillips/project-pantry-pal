"""
Phase 3G regression suite — shopping-list sort + checked_at lifecycle.

Chunk B of Theme 3 (UX polish) introduces:
  - `ShoppingItem.checked_at` (nullable DateTime, set on every False→True
    toggle and cleared on True→False)
  - A sort change: unchecked items still appear first (preserving Phase 1C
    behavior), but within the CHECKED section items now sort by
    `checked_at DESC` — most-recently-crossed-off at the top of the
    checked group, so the most-likely "undo this" target is the most
    visible one.
  - A "Checked off (N)" label divider between the unchecked and checked
    sections in `_shopping_list.html`.
  - A lazy ALTER-TABLE migration with backfill for legacy DBs that
    pre-date the `checked_at` column (legacy checked rows get
    `checked_at = added_at` so they keep their pre-3G sort position).

Each test seeds via the public route surface (HTML form posts) rather
than touching the ORM directly, so the tests double as documentation
of how the toggle endpoint behaves.
"""
from __future__ import annotations

import re
import time

from tests.conftest import Client, sign_up


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def _shopping_dom_order(body: str) -> list[int]:
    """Return the list of shopping-item IDs in render order. Each item's
    outer div carries `id="shopping-item-<id>"`, so a regex over the
    response body recovers the order Jinja actually emitted."""
    return [int(m) for m in re.findall(r'id="shopping-item-(\d+)"', body)]


def _add_shopping(c: Client, name: str) -> int:
    """Add an item via the POST /shopping route and return its DB id.
    We scrape the id out of the htmx response (a fresh _shopping_list
    partial), looking for the row whose name matches."""
    resp = c.post("/shopping", data={"name": name}, htmx=True)
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_data(as_text=True)
    # Find the LAST occurrence of the name (latest row) — re-renders
    # show oldest-to-newest within the unchecked section, but the
    # most-recently added is the new one we want.
    matches = list(re.finditer(
        r'id="shopping-item-(\d+)"[^>]*>.*?' + re.escape(name),
        body, re.DOTALL,
    ))
    assert matches, f"Couldn't find new shopping item {name!r} in response"
    return int(matches[-1].group(1))


def _toggle(c: Client, item_id: int) -> str:
    """Toggle the item via POST /shopping/<id>/toggle. Returns body."""
    resp = c.post(f"/shopping/{item_id}/toggle", htmx=True)
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Sort order
# ---------------------------------------------------------------------------

class TestSortOrder:
    def test_unchecked_items_appear_before_checked(
            self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        a = _add_shopping(client, "Apples")
        b = _add_shopping(client, "Bread")
        c = _add_shopping(client, "Cheese")

        _toggle(client, b)  # only B is checked

        body = client.get("/shopping").get_data(as_text=True)
        order = _shopping_dom_order(body)
        # All unchecked IDs must come before all checked IDs.
        unchecked = {a, c}
        checked = {b}
        for unc in unchecked:
            for chk in checked:
                assert order.index(unc) < order.index(chk), (
                    f"Item {unc} (unchecked) should appear before "
                    f"item {chk} (checked) in render order. Got: {order}"
                )

    def test_unchecked_sort_by_added_at_desc(
            self, client, app):
        """Within the unchecked section, the most-recently-added item
        appears at the top — preserving the Phase 1C "newest first"
        behavior for the unchecked group."""
        sign_up(client, "alice@example.com", "Alice")
        first = _add_shopping(client, "Apples")
        time.sleep(0.01)  # ensure distinct added_at timestamps
        second = _add_shopping(client, "Bread")
        time.sleep(0.01)
        third = _add_shopping(client, "Cheese")

        body = client.get("/shopping").get_data(as_text=True)
        order = _shopping_dom_order(body)
        assert order == [third, second, first], (
            "Unchecked items should appear newest-first (added_at DESC)."
        )

    def test_checked_sort_by_checked_at_desc_not_added_at(
            self, client, app):
        """The key new behavior. Add A, B, C in order (so added_at: A<B<C).
        Check A first, then C. The CHECKED section should be ordered
        [C, A] — most-recently-checked at top — NOT [C, A] by added_at
        coincidence and NOT [A, C] by added_at-of-checked-items.

        To distinguish: also check B (oldest added). If sort were by
        added_at, B would land at the bottom of the checked group. If
        sort is by checked_at, B (the most recently checked) lands at
        the TOP. We verify the latter."""
        sign_up(client, "alice@example.com", "Alice")
        a = _add_shopping(client, "Apples")
        b = _add_shopping(client, "Bread")
        c = _add_shopping(client, "Cheese")

        _toggle(client, a)            # checked_at(A) = t1
        time.sleep(0.01)
        _toggle(client, c)            # checked_at(C) = t2 > t1
        time.sleep(0.01)
        _toggle(client, b)            # checked_at(B) = t3 > t2

        body = client.get("/shopping").get_data(as_text=True)
        order = _shopping_dom_order(body)

        # All three are checked → checked section order should be
        # [B, C, A] (newest-checked-first), NOT [C, B, A] (added_at-
        # desc, which would be the pre-3G behavior).
        assert order == [b, c, a], (
            "Within the checked section, items must sort by checked_at "
            "DESC, not added_at DESC. If sort were still by added_at "
            f"we'd see [C={c}, B={b}, A={a}]. Got: {order}"
        )

    def test_unchecking_restores_item_to_unchecked_section(
            self, client, app):
        """Toggling a checked item back to unchecked moves it OUT of
        the checked group and INTO the unchecked group. The reverted
        item's checked_at is cleared so it sorts by added_at again."""
        sign_up(client, "alice@example.com", "Alice")
        a = _add_shopping(client, "Apples")
        b = _add_shopping(client, "Bread")

        _toggle(client, a)  # A checked → goes to checked section
        body = client.get("/shopping").get_data(as_text=True)
        assert _shopping_dom_order(body) == [b, a]

        _toggle(client, a)  # A unchecked → back to unchecked section
        body = client.get("/shopping").get_data(as_text=True)
        # Both unchecked. A's added_at is older than B's, so order is
        # [B, A] (newest-first within the unchecked group).
        assert _shopping_dom_order(body) == [b, a]


# ---------------------------------------------------------------------------
# checked_at lifecycle
# ---------------------------------------------------------------------------

class TestCheckedAtLifecycle:
    def test_checking_sets_checked_at(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        item_id = _add_shopping(client, "Apples")

        with app.app_context():
            from extensions import db
            from models import ShoppingItem
            assert db.session.get(ShoppingItem, item_id).checked_at is None, (
                "Fresh items should have NULL checked_at."
            )

        _toggle(client, item_id)

        with app.app_context():
            from extensions import db
            from models import ShoppingItem
            assert db.session.get(ShoppingItem, item_id).checked_at is not None, (
                "Checking an item must set checked_at to a timestamp."
            )

    def test_unchecking_clears_checked_at(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        item_id = _add_shopping(client, "Apples")
        _toggle(client, item_id)  # check

        with app.app_context():
            from extensions import db
            from models import ShoppingItem
            assert db.session.get(ShoppingItem, item_id).checked_at is not None

        _toggle(client, item_id)  # uncheck

        with app.app_context():
            from extensions import db
            from models import ShoppingItem
            assert db.session.get(ShoppingItem, item_id).checked_at is None, (
                "Unchecking must clear checked_at back to None so a "
                "later re-check resets the timestamp rather than "
                "sorting against the stale prior position."
            )

    def test_re_checking_resets_timestamp(self, client, app):
        """The whole reason we clear checked_at on uncheck: a user who
        un-checks (oops, didn't actually buy that) and re-checks (got
        it after all) expects the item to sit at the top of the
        checked group again, not at its stale prior position."""
        sign_up(client, "alice@example.com", "Alice")
        item_id = _add_shopping(client, "Apples")
        _toggle(client, item_id)  # check

        with app.app_context():
            from extensions import db
            from models import ShoppingItem
            first_check = db.session.get(ShoppingItem, item_id).checked_at

        time.sleep(0.01)
        _toggle(client, item_id)  # uncheck
        time.sleep(0.01)
        _toggle(client, item_id)  # re-check

        with app.app_context():
            from extensions import db
            from models import ShoppingItem
            second_check = db.session.get(ShoppingItem, item_id).checked_at
            assert second_check is not None
            assert second_check > first_check, (
                "Re-checking must set a fresh timestamp, not reuse the "
                f"original one. first={first_check}, second={second_check}"
            )


# ---------------------------------------------------------------------------
# "Checked off (N)" divider
# ---------------------------------------------------------------------------

class TestDivider:
    def test_divider_renders_when_checked_items_exist(
            self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        a = _add_shopping(client, "Apples")
        _add_shopping(client, "Bread")
        _toggle(client, a)

        body = client.get("/shopping").get_data(as_text=True)
        assert "Checked off (1)" in body, (
            "Divider with the correct count is missing — users won't "
            "see the visual separation between active and checked items."
        )

    def test_divider_count_matches_number_of_checked_items(
            self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        a = _add_shopping(client, "Apples")
        b = _add_shopping(client, "Bread")
        c = _add_shopping(client, "Cheese")
        _add_shopping(client, "Dates")  # leave one unchecked
        _toggle(client, a)
        _toggle(client, b)
        _toggle(client, c)

        body = client.get("/shopping").get_data(as_text=True)
        assert "Checked off (3)" in body
        # And the wrong counts shouldn't appear (defends against a
        # stale total-vs-checked-count bug).
        assert "Checked off (4)" not in body
        assert "Checked off (0)" not in body

    def test_divider_absent_when_nothing_checked(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Apples")
        _add_shopping(client, "Bread")

        body = client.get("/shopping").get_data(as_text=True)
        assert "Checked off (" not in body, (
            "Divider must NOT render when there are zero checked items "
            "— otherwise the list shows a phantom empty-section header."
        )

    def test_divider_absent_when_list_completely_empty(
            self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        body = client.get("/shopping").get_data(as_text=True)
        assert "Checked off (" not in body
        # And the empty-state copy should still show.
        assert "Nothing on your shopping list" in body

    def test_divider_appears_in_htmx_toggle_response(
            self, client, app):
        """The divider should appear in the htmx-swap response too,
        not just the full /shopping page. Toggling an item re-renders
        the whole _shopping_list partial — that partial is what carries
        the divider."""
        sign_up(client, "alice@example.com", "Alice")
        a = _add_shopping(client, "Apples")
        _add_shopping(client, "Bread")

        # The toggle response IS the new _shopping_list partial body.
        body = _toggle(client, a)
        assert "Checked off (1)" in body


# ---------------------------------------------------------------------------
# Lazy migration (legacy DB without the checked_at column)
# ---------------------------------------------------------------------------

class TestMigration:
    """Boot a hand-rolled DB that has the Phase 2A shape but NO
    checked_at column on shopping_items, then verify create_app() ALTERs
    in the column AND backfills legacy checked rows with added_at."""

    def test_legacy_db_gets_checked_at_column_added(
            self, tmp_path, monkeypatch):
        import sqlite3
        db_file = tmp_path / "legacy.sqlite3"

        # Hand-roll a Phase 2A schema (with household_id columns) but
        # WITHOUT checked_at. This is the schema Riah's real dev DB
        # had between Phase 2A and Phase 3G.
        con = sqlite3.connect(db_file)
        con.executescript("""
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
                added_at DATETIME NOT NULL
            );
            INSERT INTO households (id, name, created_at)
                VALUES (1, 'Legacy', '2026-01-01');
            INSERT INTO users (id, email, password_hash, name, household_id, created_at)
                VALUES (1, 'a@example.com', 'placeholder', 'A', 1, '2026-01-01');
            INSERT INTO shopping_items
                (id, user_id, household_id, name, checked, added_at)
                VALUES
                (1, 1, 1, 'Pre-3G unchecked', 0, '2026-01-05'),
                (2, 1, 1, 'Pre-3G checked',   1, '2026-01-06');
        """)
        con.commit()
        con.close()

        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
        monkeypatch.setenv("FLASK_SECRET_KEY", "smoke-test-secret")

        from app import create_app
        app1 = create_app()

        with app1.app_context():
            from extensions import db
            from models import ShoppingItem
            from sqlalchemy import inspect

            cols = {c["name"] for c in inspect(db.engine).get_columns("shopping_items")}
            assert "checked_at" in cols, (
                "Lazy ALTER TABLE did not add the checked_at column."
            )

            unchecked = db.session.get(ShoppingItem, 1)
            checked = db.session.get(ShoppingItem, 2)
            assert unchecked.checked is False
            assert unchecked.checked_at is None, (
                "Legacy UNCHECKED rows must keep checked_at = NULL."
            )

            assert checked.checked is True
            assert checked.checked_at is not None, (
                "Legacy CHECKED rows must be backfilled with a "
                "checked_at value so they sort correctly within the "
                "checked group."
            )
            # Specifically: backfilled to added_at (least-wrong stand-in)
            assert checked.checked_at == checked.added_at, (
                "Legacy checked rows should be backfilled with their "
                "added_at, not utcnow() (which would shuffle the "
                "checked-group sort order unpredictably on first boot)."
            )

    def test_second_boot_is_a_noop(self, tmp_path, monkeypatch):
        """Idempotency: booting the app twice in a row against a DB
        that's already at 3G doesn't re-run the ALTER, doesn't loop
        on the backfill, doesn't crash."""
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'fresh.sqlite3'}")
        monkeypatch.setenv("FLASK_SECRET_KEY", "smoke-test-secret")

        from app import create_app, _ensure_shopping_checked_at_column
        app = create_app()
        with app.app_context():
            _ensure_shopping_checked_at_column()  # call directly, no-op expected
            _ensure_shopping_checked_at_column()
            # No assertion needed — the test passes iff no exception.
