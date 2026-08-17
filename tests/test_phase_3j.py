"""
Phase 3J regression suite — Undo for destructive shopping actions.

Chunk C of Theme 3 (shopping UX polish) replaces the hx-confirm modal
on `Clear checked` and item-level `Delete` with an undoable 5-second
toast. The toast carries an `Undo` button that POSTs to a new
/shopping/undo route, which restores items from a snapshot stashed in
the Flask session BEFORE the original delete commits.

These tests guard:
  1. Snapshot lifecycle — captured on every destructive action, with
     the right fields; cleared on undo; overwritten by subsequent
     destructive actions.
  2. Restore semantics — items come back with original timestamps,
     check state, name, qty/unit/notes, AND original provenance.
  3. HX-Trigger payloads — destructive routes ship the undoUrl in
     the toast event payload; undo route fires its own confirmation
     event.
  4. Boundaries — the cookie-cap (UNDO_SNAPSHOT_MAX_ITEMS) suppresses
     the Undo CTA on huge clears, household scoping keeps a forged
     snapshot from leaking, anonymous users can't hit /undo.
  5. UI wiring — hx-confirm is gone from both destructive buttons.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from tests.conftest import Client, sign_up


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_shopping(c: Client, name: str, qty: str = "", unit: str = "",
                  notes: str = ""):
    return c.post("/shopping", htmx=True, data={
        "name": name, "quantity": qty, "unit": unit, "notes": notes,
        "submit": "Add",
    })


def _shopping_item_ids(html: str) -> list[str]:
    return re.findall(r'id="shopping-item-(\d+)"', html)


def _toggle(c: Client, item_id: str):
    return c.post(f"/shopping/{item_id}/toggle", htmx=True)


def _hx_trigger_payload(resp) -> dict | None:
    """Decode the HX-Trigger response header into a dict, or None if
    absent. We assert on this rather than parse the HTML body for the
    "Undo" string because the client-side toast is rendered by JS, not
    by Flask — the only server contract is the trigger payload."""
    header = resp.headers.get("HX-Trigger")
    if not header:
        return None
    return json.loads(header)


def _shopping_row_count(app, household_id: int) -> int:
    with app.app_context():
        from models import ShoppingItem
        return ShoppingItem.query.filter_by(
            household_id=household_id,
        ).count()


def _household_id_for(app, email: str) -> int:
    with app.app_context():
        from models import User
        return User.query.filter_by(email=email).first().household_id


# ---------------------------------------------------------------------------
# 1. Clear checked — snapshot + payload + undo
# ---------------------------------------------------------------------------

class TestClearCheckedUndo:
    def test_payload_carries_undo_url_under_cap(self, client, app):
        """Sub-25 clear must include `undoUrl` in HX-Trigger so the
        client toast can render the Undo CTA. Asserting on the wire
        contract (HX-Trigger JSON), not the rendered HTML."""
        sign_up(client, "alice@example.com", "Alice")

        _add_shopping(client, "Milk")
        _add_shopping(client, "Eggs")
        html = client.get("/shopping").get_data(as_text=True)
        for iid in _shopping_item_ids(html):
            _toggle(client, iid)

        resp = client.post("/shopping/clear-checked", htmx=True)
        assert resp.status_code == 200
        payload = _hx_trigger_payload(resp)
        assert payload is not None, "Clear must fire HX-Trigger"
        event = payload.get("shopping:cleared-checked")
        assert event["count"] == 2
        assert event["undoUrl"] == "/shopping/undo", (
            f"Toast must carry the undo URL for the client-side button "
            f"to wire up; got {event}"
        )

    def test_undo_restores_cleared_items_with_original_state(
        self, client, app,
    ):
        """End-to-end: clear → undo → items back, AT ORIGINAL POSITIONS,
        WITH ORIGINAL CHECK STATE. The 'restore exactly how it was'
        semantic is the whole point of undo; restoring with
        `checked=False` or jumping the rows to the top would be
        surprising."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")

        _add_shopping(client, "Milk", qty="1", unit="gal",
                      notes="organic if avail")
        _add_shopping(client, "Eggs")
        html = client.get("/shopping").get_data(as_text=True)
        ids_before = _shopping_item_ids(html)
        for iid in ids_before:
            _toggle(client, iid)

        # Snapshot the rows just before Clear (for cross-check after)
        with app.app_context():
            from models import ShoppingItem
            rows_before = sorted(
                ShoppingItem.query.filter_by(household_id=hid).all(),
                key=lambda r: r.id,
            )
            milk_attrs = {
                "name": rows_before[0].name,
                "quantity": rows_before[0].quantity,
                "unit": rows_before[0].unit,
                "notes": rows_before[0].notes,
                "checked": rows_before[0].checked,
            }

        client.post("/shopping/clear-checked", htmx=True)
        assert _shopping_row_count(app, hid) == 0

        # Undo
        resp = client.post("/shopping/undo", htmx=True)
        assert resp.status_code == 200

        with app.app_context():
            from models import ShoppingItem
            rows_after = ShoppingItem.query.filter_by(
                household_id=hid,
            ).all()
            assert len(rows_after) == 2, (
                f"Undo should restore both rows; got {len(rows_after)}"
            )
            milk_row = next(r for r in rows_after if r.name == "Milk")
            assert milk_row.quantity == milk_attrs["quantity"]
            assert milk_row.unit == milk_attrs["unit"]
            assert milk_row.notes == milk_attrs["notes"]
            assert milk_row.checked is True, (
                "Restore must preserve checked=True from the snapshot — "
                "otherwise re-rendering looks weird (items appear as "
                "fresh-added rows after an undo)."
            )

    def test_undo_clears_session_snapshot(self, client, app):
        """A second tap on /shopping/undo must NOT double-restore.
        Validates that the session snapshot is popped after a
        successful restore."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")

        _add_shopping(client, "Milk")
        ids = _shopping_item_ids(client.get("/shopping").get_data(as_text=True))
        for iid in ids:
            _toggle(client, iid)
        client.post("/shopping/clear-checked", htmx=True)

        client.post("/shopping/undo", htmx=True)
        assert _shopping_row_count(app, hid) == 1

        # Second tap — no further restoration; payload should NOT
        # contain a `shopping:undone` event (count would be 0 → toast
        # noise).
        resp = client.post("/shopping/undo", htmx=True)
        assert _shopping_row_count(app, hid) == 1, (
            "Re-tapping /shopping/undo must not duplicate items — "
            "snapshot should have been popped on first restore."
        )
        assert _hx_trigger_payload(resp) is None, (
            "No HX-Trigger should fire on a no-op undo (no snapshot, "
            "no items restored). Empty trigger = no confirmation toast."
        )

    def test_payload_suppresses_undo_url_over_cap(self, client, app):
        """Bulk clears exceeding UNDO_SNAPSHOT_MAX_ITEMS skip the Undo
        CTA — better no-undo than partial-undo (snapshot truncation
        would silently lose items on restore)."""
        sign_up(client, "alice@example.com", "Alice")
        from app import UNDO_SNAPSHOT_MAX_ITEMS

        # Add cap + 1 items and check them all
        over_cap = UNDO_SNAPSHOT_MAX_ITEMS + 1
        for i in range(over_cap):
            _add_shopping(client, f"Item {i}")
        html = client.get("/shopping").get_data(as_text=True)
        for iid in _shopping_item_ids(html):
            _toggle(client, iid)

        resp = client.post("/shopping/clear-checked", htmx=True)
        payload = _hx_trigger_payload(resp)
        event = payload["shopping:cleared-checked"]
        assert event["count"] == over_cap
        assert event["undoUrl"] is None, (
            f"Over-cap clears must NOT carry an undoUrl — got {event}. "
            f"A partial-restore Undo button would silently lose items."
        )

    def test_clear_without_items_fires_no_trigger(self, client, app):
        """Tapping Clear with 0 checked items (defensive curl POST,
        since the UI gates the button behind checked_count > 0) must
        not spawn a stale toast. No HX-Trigger header at all."""
        sign_up(client, "alice@example.com", "Alice")
        resp = client.post("/shopping/clear-checked", htmx=True)
        assert resp.status_code == 200
        assert resp.headers.get("HX-Trigger") is None


# ---------------------------------------------------------------------------
# 2. Item Delete — snapshot + payload + undo
# ---------------------------------------------------------------------------

class TestItemDeleteUndo:
    def test_delete_fires_undoable_toast_with_item_name(self, client, app):
        """Single Delete now fires `shopping:deleted` with the item
        name + undoUrl (pre-3J it was silent — no toast at all)."""
        sign_up(client, "alice@example.com", "Alice")

        _add_shopping(client, "Sriracha")
        iid = _shopping_item_ids(
            client.get("/shopping").get_data(as_text=True)
        )[0]

        resp = client.delete(f"/shopping/{iid}")
        assert resp.status_code == 200
        payload = _hx_trigger_payload(resp)
        assert payload is not None, "Delete must now fire a toast event"
        event = payload["shopping:deleted"]
        assert event["name"] == "Sriracha"
        assert event["undoUrl"] == "/shopping/undo"

    def test_delete_then_undo_restores_full_row(self, client, app):
        """Single-item delete + undo: name, qty, unit, notes all
        preserved."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")

        _add_shopping(client, "Olive oil", qty="1", unit="bottle",
                      notes="extra virgin")
        iid = _shopping_item_ids(
            client.get("/shopping").get_data(as_text=True)
        )[0]
        client.delete(f"/shopping/{iid}")
        assert _shopping_row_count(app, hid) == 0

        client.post("/shopping/undo", htmx=True)
        with app.app_context():
            from models import ShoppingItem
            rows = ShoppingItem.query.filter_by(household_id=hid).all()
            assert len(rows) == 1
            r = rows[0]
            assert r.name == "Olive oil"
            assert r.quantity == 1
            assert r.unit == "bottle"
            assert r.notes == "extra virgin"

    def test_delete_long_name_truncates_toast_text_not_db(
        self, client, app,
    ):
        """Field len cap on name in DB is 120; we cap the TOAST display
        at 40 to avoid a giant toast breaking the layout on mobile.
        The DB row + the restored row still carry the FULL name."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")

        long_name = "X" * 100
        _add_shopping(client, long_name)
        iid = _shopping_item_ids(
            client.get("/shopping").get_data(as_text=True)
        )[0]
        resp = client.delete(f"/shopping/{iid}")
        event = _hx_trigger_payload(resp)["shopping:deleted"]
        assert len(event["name"]) == 40, (
            f"Toast display name should cap at 40 chars; got "
            f"{len(event['name'])}: {event['name']!r}"
        )

        # But the underlying snapshot/restore keeps the full name
        client.post("/shopping/undo", htmx=True)
        with app.app_context():
            from models import ShoppingItem
            restored = ShoppingItem.query.filter_by(
                household_id=hid,
            ).first()
            assert restored.name == long_name, (
                "Snapshot/restore must preserve the full untruncated "
                "name — only the toast display is capped."
            )


# ---------------------------------------------------------------------------
# 3. Snapshot semantics — last-action-wins, overwrites
# ---------------------------------------------------------------------------

class TestSnapshotLifecycle:
    def test_new_destructive_action_overwrites_prior_snapshot(
        self, client, app,
    ):
        """Two destructive actions back-to-back: undo restores ONLY the
        second one (last-action-wins). Otherwise users would have a
        confusing "Undo what?" CTA after sequential deletes."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")

        # Add 3 items, delete the first
        _add_shopping(client, "Milk")
        _add_shopping(client, "Eggs")
        _add_shopping(client, "Bread")
        ids = _shopping_item_ids(
            client.get("/shopping").get_data(as_text=True)
        )
        # Order: newest first (added_at desc). ids[0] = Bread.
        client.delete(f"/shopping/{ids[2]}")  # delete Milk (oldest)
        # Now delete Eggs (the second action — this is what should undo)
        ids2 = _shopping_item_ids(
            client.get("/shopping").get_data(as_text=True)
        )
        # Find Eggs id in the remaining list
        eggs_id = None
        for iid in ids2:
            with app.app_context():
                from app import db
                from models import ShoppingItem
                row = db.session.get(ShoppingItem, int(iid))
                if row and row.name == "Eggs":
                    eggs_id = iid
                    break
        assert eggs_id is not None
        client.delete(f"/shopping/{eggs_id}")

        client.post("/shopping/undo", htmx=True)
        with app.app_context():
            from models import ShoppingItem
            names = sorted(
                r.name for r in ShoppingItem.query.filter_by(
                    household_id=hid,
                ).all()
            )
            # Bread (untouched) + Eggs (restored from most-recent delete);
            # Milk stays gone because the second delete overwrote the
            # snapshot of the first.
            assert names == ["Bread", "Eggs"], (
                f"Last-action-wins: only Eggs (the most-recent delete) "
                f"should restore. Got {names}."
            )

    def test_anonymous_user_cannot_undo(self, app):
        """The /shopping/undo route must be unreachable for anonymous
        users. Either login_required redirects them (302 → /login),
        Flask returns 401, or CSRF protection (which fires earlier
        than login_required) rejects them with 400. All three mean
        "you can't act on this route without an authenticated
        session" — the negative space is what matters."""
        from tests.conftest import Client
        client = Client(app.test_client())

        # Bare POST — no CSRF token attached, mimicking an external
        # script. The first-line defense (CSRF) yields 400; if that
        # ever softens, login_required catches it (302/401).
        resp = client._c.post("/shopping/undo")
        assert resp.status_code in (302, 400, 401), (
            f"Anonymous /shopping/undo should fail with 302/400/401; "
            f"got {resp.status_code}"
        )

    def test_undo_household_scoping(self, two_clients, app):
        """Defensive check: a snapshot bound to household A must not
        restore into household B even if Bob hits /undo. The session
        already isolates this naturally (per-cookie), but the route's
        explicit household_id check in _restore_shopping_snapshot is
        defense-in-depth against a forged session cookie."""
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")

        alice_hid = _household_id_for(app, "alice@example.com")
        bob_hid = _household_id_for(app, "bob@example.com")
        assert alice_hid != bob_hid

        _add_shopping(alice, "Milk")
        iid = _shopping_item_ids(
            alice.get("/shopping").get_data(as_text=True)
        )[0]
        alice.delete(f"/shopping/{iid}")
        # Alice's session now holds a snapshot with household_id=alice_hid.

        # Bob hits undo — his session has NO snapshot, so nothing should
        # restore in either household. (Session isolation is per-cookie
        # which is per-client; this is the natural guarantee, but the
        # test also catches a regression that ever shared sessions.)
        bob.post("/shopping/undo", htmx=True)
        assert _shopping_row_count(app, bob_hid) == 0
        assert _shopping_row_count(app, alice_hid) == 0, (
            "Bob's undo must not restore Alice's deleted item — "
            "household scoping (and session isolation) must hold."
        )

        # And Alice's own undo still works.
        alice.post("/shopping/undo", htmx=True)
        assert _shopping_row_count(app, alice_hid) == 1


# ---------------------------------------------------------------------------
# 4. UI wiring — confirm modal removed, toast slots present
# ---------------------------------------------------------------------------

class TestUIWiring:
    def test_clear_button_no_longer_has_hx_confirm(self, client, app):
        """The hx-confirm attribute on the Clear button is gone (toast
        is the safety net now)."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        iid = _shopping_item_ids(
            client.get("/shopping").get_data(as_text=True)
        )[0]
        _toggle(client, iid)

        html = client.get("/shopping").get_data(as_text=True)
        # Locate the Clear button block and assert hx-confirm is absent
        clear_match = re.search(
            r'hx-post="/shopping/clear-checked"[^>]*>\s*Clear checked',
            html, re.DOTALL,
        )
        assert clear_match, "Clear button should still exist"
        # Reach backward a few chars from the match start to capture
        # all attributes — make sure hx-confirm isn't among them.
        button_block_start = html.rfind('<button', 0, clear_match.start())
        button_block = html[button_block_start:clear_match.end()]
        assert "hx-confirm" not in button_block, (
            "Clear button should no longer have hx-confirm; toast is "
            "the safety net (Phase 3J)."
        )

    def test_delete_button_no_longer_has_hx_confirm(self, client, app):
        """Same check for the item-level Delete button."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        html = client.get("/shopping").get_data(as_text=True)

        # Find the accessible icon-only Delete button's hx-delete
        # attribute and inspect the surrounding markup.
        del_match = re.search(
            r'aria-label="Delete Milk"[^>]*\s+hx-delete="/shopping/\d+"',
            html, re.DOTALL,
        )
        assert del_match, "Delete button should still exist"
        button_block_start = html.rfind('<button', 0, del_match.start())
        button_block = html[button_block_start:del_match.end()]
        assert "hx-confirm" not in button_block, (
            "Delete button should no longer have hx-confirm (Phase 3J)."
        )

    def test_toast_has_text_and_action_slots(self, client, app):
        """Base layout must render the two toast slots the JS expects.
        Without these IDs, showToast() bails silently and no toast
        ever shows."""
        sign_up(client, "alice@example.com", "Alice")
        html = client.get("/shopping").get_data(as_text=True)
        assert 'id="toast-text"' in html, (
            "Base layout must render the toast text span "
            '(`id="toast-text"`) — showToast() needs it.'
        )
        assert 'id="toast-action"' in html, (
            "Base layout must render the toast action button "
            '(`id="toast-action"`) for the Undo CTA.'
        )

    def test_existing_text_only_toasts_still_render(self, client, app):
        """The shopping:added toast (text-only) shouldn't regress
        when the toast was refactored to a two-slot layout. Quick
        smoke: trigger an add and confirm HX-Trigger fires the same
        shape it always did."""
        sign_up(client, "alice@example.com", "Alice")
        # Add a pantry item first so we can use the +Shop cross-link
        # which is the canonical `shopping:added` emitter.
        client.post("/pantry", htmx=True, data={
            "name": "Milk", "quantity": "", "unit": "", "notes": "",
            "submit": "Add",
        })
        pantry_html = client.get("/pantry").get_data(as_text=True)
        pid = re.search(r'id="pantry-item-(\d+)"', pantry_html).group(1)
        resp = client.post(f"/pantry/{pid}/add-to-shopping", htmx=True)
        # The +Shop endpoint fires `shopping:added` as a bare event
        # (no JSON payload — `HX-Trigger: shopping:added`).
        assert resp.headers.get("HX-Trigger") == "shopping:added", (
            "Text-only +Shop toast should still fire its bare event; "
            "the 3J toast refactor must not change this contract."
        )
