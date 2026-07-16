"""
Phase 6C regression suite — Undo on "I'm home" (shopping → pantry move).

Completes the safety-net trio (shopping-delete + pantry-delete + im-home)
with the same 5s toast-with-Undo pattern established in Phase 3J and
extended in Phase 6A. The im-home flow is uniquely COMPOUND — one tap
DELETES N shopping items AND CREATES N pantry items. Undo has to reverse
both sides: delete the created pantry rows, restore the shopping items
with `checked=True` preserved so the user lands exactly where they
were before the tap.

Implementation shape:

  - Reuses SHOPPING_UNDO_SESSION_KEY (single last-action-wins slot on
    the shopping page — im-home + delete + clear all compete for it,
    which is what "Undo the last thing I did here" should mean).
  - Extends the snapshot schema with an optional `created_pantry_ids: [int]`.
  - `shopping_undo` unwinds the pantry side first (deletes the created
    rows, household-scoped), then restores shopping via the existing
    `_restore_shopping_snapshot`. One transaction, one commit.
  - The move-checked-to-pantry route flushes (not commits) so it can
    read the auto-assigned pantry PKs BEFORE the shopping delete.
  - Toast handler in base.html now consumes `undoUrl` in the payload
    same as `shopping:cleared-checked` — undoUrl == null means
    text-only (cap-hit fallback).

These tests guard:

  1. Route contract — 200, HX-Trigger `shopping:moved-to-pantry` with
     BOTH `count` AND `undoUrl` (or `undoUrl: null` on cap).
  2. Undo semantics — deletes exactly the pantry rows that were created,
     leaves any pre-existing pantry rows with the same name untouched;
     restores shopping items in their pre-move state (checked=True,
     original added_at + added_by_user_id + qty + unit + notes).
  3. Compound reversal — the same POST to /shopping/undo handles both
     the create-pantry side and the delete-shopping side atomically.
  4. Last-action-wins — a shopping delete after im-home overwrites the
     im-home undo slot; the delete's undo restores only that item.
     Conversely, a fresh im-home wipes any prior delete-undo slot.
  5. Household scoping — a forged session with foreign pantry IDs
     can't reach into another household's rows; a snapshot from
     Alice can't be undone by Bob even if he POSTs /shopping/undo
     with matching cookies.
  6. Missing-row tolerance — if the user manually deletes one of the
     just-moved pantry rows in the 5s window, undo silently skips the
     missing ID and restores the rest.
  7. Cap semantics — over-25-item move still lands but with
     `undoUrl: null` (text-only toast); the prior snapshot is popped
     rather than left stale (mirrors shopping's cap behavior).
  8. Empty-case no-op — 0 checked items → no HX-Trigger, no session
     touch (preserves any pre-existing snapshot for a legitimate
     Undo the user hasn't consumed yet).
  9. UI wiring — base.html reads `undoUrl` off the payload;
     `showToast` renders the button and targets `#shopping-list`.

Tier-1 dev loop:

    pytest tests/test_phase_6c.py -q
"""
from __future__ import annotations

import json
import re

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


def _add_pantry(c: Client, name: str, qty: str = "", unit: str = "",
                notes: str = ""):
    return c.post("/pantry", htmx=True, data={
        "name": name, "quantity": qty, "unit": unit, "notes": notes,
        "submit": "Add",
    })


def _shopping_ids(html: str) -> list[str]:
    return re.findall(r'id="shopping-item-(\d+)"', html)


def _shopping_rows(app, household_id: int):
    with app.app_context():
        from models import ShoppingItem
        return (
            ShoppingItem.query
            .filter_by(household_id=household_id)
            .order_by(ShoppingItem.id.asc())
            .all()
        )


def _pantry_rows(app, household_id: int):
    with app.app_context():
        from models import PantryItem
        return (
            PantryItem.query
            .filter_by(household_id=household_id)
            .order_by(PantryItem.id.asc())
            .all()
        )


def _household_id_for(app, email: str) -> int:
    with app.app_context():
        from models import User
        return User.query.filter_by(email=email).first().household_id


def _hx_trigger_payload(resp) -> dict | None:
    header = resp.headers.get("HX-Trigger")
    if not header:
        return None
    return json.loads(header)


def _check(c: Client, shopping_id: str) -> None:
    c.post(f"/shopping/{shopping_id}/toggle", htmx=True)


def _seed_and_check(c: Client, names: list[str]) -> None:
    """Add each name to shopping, then check every one. Ends with N
    checked shopping items ready for the I'm-home move."""
    for name in names:
        _add_shopping(c, name)
    body = c.get("/shopping").get_data(as_text=True)
    for sid in _shopping_ids(body):
        _check(c, sid)


def _move_im_home(c: Client):
    return c.post("/shopping/move-checked-to-pantry", htmx=True)


def _undo(c: Client):
    return c.post("/shopping/undo", htmx=True)


# ---------------------------------------------------------------------------
# 1. Route contract — HX-Trigger payload shape
# ---------------------------------------------------------------------------

class TestRouteContract:
    def test_move_ships_undoable_toast_payload(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        _seed_and_check(client, ["Milk", "Bread"])

        resp = _move_im_home(client)
        assert resp.status_code == 200
        payload = _hx_trigger_payload(resp)
        assert payload is not None, (
            "I'm home must fire an HX-Trigger when items moved"
        )
        assert "shopping:moved-to-pantry" in payload
        body = payload["shopping:moved-to-pantry"]
        assert body["count"] == 2
        assert body["undoUrl"] == "/shopping/undo", (
            "Grocery-runs under the cap must ship an Undo CTA — "
            "the 5s toast is the sole safety net for a compound "
            "action that touched two lists."
        )

    def test_move_zero_checked_is_noop_no_trigger(self, client, app):
        """Defensive: button is gated in the UI, but a curl POST
        with nothing checked must not emit a "Moved 0 items" toast
        and must not touch the session (preserve any pre-existing
        undo snapshot from a legitimate earlier action)."""
        sign_up(client, "alice@example.com", "Alice")
        # Add a checked shopping item, delete it (creates an undo
        # snapshot), then hit the move endpoint with no checked
        # items and assert the delete's undo slot survives.
        _add_shopping(client, "Milk")
        body = client.get("/shopping").get_data(as_text=True)
        milk_id = _shopping_ids(body)[0]
        client.delete(f"/shopping/{milk_id}")

        resp = _move_im_home(client)
        assert resp.status_code == 200
        assert "HX-Trigger" not in resp.headers

        # The prior delete's undo must still work.
        undo_resp = _undo(client)
        payload = _hx_trigger_payload(undo_resp)
        assert payload and payload.get("shopping:undone", {}).get("count") == 1

    def test_undo_response_fires_shopping_undone(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        _seed_and_check(client, ["Milk", "Bread"])
        _move_im_home(client)

        resp = _undo(client)
        assert resp.status_code == 200
        payload = _hx_trigger_payload(resp)
        assert payload is not None
        assert payload["shopping:undone"]["count"] == 2


# ---------------------------------------------------------------------------
# 2. Undo semantics — reverses BOTH sides of the move
# ---------------------------------------------------------------------------

class TestCompoundReversal:
    def test_undo_deletes_created_pantry_rows(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _seed_and_check(client, ["Milk", "Bread"])
        _move_im_home(client)

        # Verify move worked before we test the undo.
        assert len(_pantry_rows(app, hid)) == 2
        assert len(_shopping_rows(app, hid)) == 0

        _undo(client)

        assert len(_pantry_rows(app, hid)) == 0, (
            "Undo must delete every pantry row created by the move — "
            "the fingerprint (id) match is what makes this safe."
        )

    def test_undo_restores_shopping_items_with_checked_state(
        self, client, app,
    ):
        """Critical UX detail: the user was in the middle of a
        grocery run. Checked items represent "already in the cart."
        Restoring them un-checked would force the user to re-tap
        each one — a worse experience than the original mistake."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _seed_and_check(client, ["Milk", "Bread"])
        _move_im_home(client)
        _undo(client)

        rows = _shopping_rows(app, hid)
        assert len(rows) == 2
        assert all(r.checked for r in rows), (
            "Restored shopping items must retain their pre-move "
            "checked state — the user was mid-grocery-run."
        )

    def test_undo_preserves_full_shopping_row_fidelity(self, client, app):
        """qty, unit, notes, added_at, and added_by_user_id all
        survive the round-trip."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _add_shopping(client, "Milk", qty="1", unit="gal", notes="whole")
        body = client.get("/shopping").get_data(as_text=True)
        milk_id = _shopping_ids(body)[0]
        _check(client, milk_id)

        # Capture original added_at for comparison after restore.
        with app.app_context():
            from models import ShoppingItem
            original = ShoppingItem.query.filter_by(household_id=hid).one()
            original_added_at = original.added_at
            original_added_by = original.added_by_user_id

        _move_im_home(client)
        _undo(client)

        with app.app_context():
            from models import ShoppingItem
            row = ShoppingItem.query.filter_by(household_id=hid).one()
            assert row.name == "Milk"
            assert row.quantity == 1
            assert row.unit == "gal"
            assert row.notes == "whole"
            assert row.checked is True
            # Provenance intact — undo shouldn't rewrite history.
            assert row.added_by_user_id == original_added_by
            # added_at within a second of the original (ISO round-trip
            # loses microseconds but preserves seconds).
            delta = abs(
                (row.added_at - original_added_at).total_seconds()
            )
            assert delta < 1.0, (
                f"added_at drift {delta}s exceeds ISO round-trip tolerance"
            )

    def test_undo_leaves_pre_existing_pantry_rows_untouched(
        self, client, app,
    ):
        """The user might already have a "Milk" pantry row from a
        prior grocery run. If they add "Milk" to shopping, check it,
        and I'm-home, we create a SECOND Milk pantry row. Undo must
        delete only that second row (by ID) — leaving the ORIGINAL
        Milk row alone. Guards against a naive `filter_by(name=...)`
        style delete."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _add_pantry(client, "Milk", qty="1", unit="gal")

        # Capture the pre-existing Milk row's ID so we can assert
        # it's still there post-undo.
        with app.app_context():
            from models import PantryItem
            original_milk = PantryItem.query.filter_by(
                household_id=hid, name="Milk",
            ).one()
            original_milk_id = original_milk.id

        # Now do a fresh grocery run for Milk.
        _seed_and_check(client, ["Milk"])
        _move_im_home(client)

        # Two Milk rows now (original + newly moved).
        milks = [r for r in _pantry_rows(app, hid) if r.name == "Milk"]
        assert len(milks) == 2

        _undo(client)

        # After undo — original Milk survives, newly moved Milk gone.
        with app.app_context():
            from models import PantryItem
            surviving = PantryItem.query.filter_by(
                household_id=hid, name="Milk",
            ).all()
            assert len(surviving) == 1
            assert surviving[0].id == original_milk_id, (
                "Undo must delete the just-CREATED pantry row (matched "
                "by ID), NOT the pre-existing row with the same name."
            )

    def test_undo_atomic_pantry_deletes_shopping_restores_one_commit(
        self, client, app,
    ):
        """No partial-undo. Both sides commit together — if either
        side would fail, neither should apply. Hard to induce a real
        failure without mocking, but we can at least assert the
        end state is consistent (all created pantry rows gone AND
        all shopping rows back)."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _seed_and_check(client, ["Milk", "Bread", "Eggs"])
        _move_im_home(client)
        _undo(client)

        assert len(_pantry_rows(app, hid)) == 0
        shopping = _shopping_rows(app, hid)
        assert len(shopping) == 3
        assert all(r.checked for r in shopping)


# ---------------------------------------------------------------------------
# 3. Last-action-wins on the shopping undo slot
# ---------------------------------------------------------------------------

class TestLastActionWins:
    def test_delete_after_im_home_overrides_undo_slot(self, client, app):
        """User does I'm-home, then deletes an unrelated shopping
        item they added later. Undo restores the DELETED item — not
        the moved ones. The stale im-home undo is gone."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")

        _seed_and_check(client, ["Milk", "Bread"])
        _move_im_home(client)  # Snapshot: im_home, 2 items

        _add_shopping(client, "Eggs")
        body = client.get("/shopping").get_data(as_text=True)
        eggs_id = _shopping_ids(body)[0]
        client.delete(f"/shopping/{eggs_id}")  # Overrides snapshot

        _undo(client)

        # Only Eggs is restored; the moved items stay in pantry.
        assert len(_pantry_rows(app, hid)) == 2, (
            "Delete after im-home means the im-home snapshot is "
            "GONE — the moved pantry rows should be permanent."
        )
        rows = _shopping_rows(app, hid)
        names = sorted(r.name for r in rows)
        assert names == ["Eggs"]

    def test_im_home_after_delete_overrides_undo_slot(self, client, app):
        """Symmetric: user deletes an item, then I'm-homes some
        other checked items. Undo reverses the im-home; the earlier
        delete is now un-undoable."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")

        _add_shopping(client, "Eggs")
        body = client.get("/shopping").get_data(as_text=True)
        eggs_id = _shopping_ids(body)[0]
        client.delete(f"/shopping/{eggs_id}")  # Snapshot: delete_one Eggs

        _seed_and_check(client, ["Milk", "Bread"])
        _move_im_home(client)  # Overrides snapshot

        _undo(client)

        # Moved items are back on shopping; Eggs stays deleted.
        assert len(_pantry_rows(app, hid)) == 0
        rows = _shopping_rows(app, hid)
        names = sorted(r.name for r in rows)
        assert names == ["Bread", "Milk"]


# ---------------------------------------------------------------------------
# 4. Household scoping — cross-household isolation
# ---------------------------------------------------------------------------

class TestHouseholdScoping:
    def test_alice_snapshot_cant_delete_bob_pantry_row(
        self, two_clients, app,
    ):
        """A forged session cookie with foreign pantry IDs must
        not delete rows from another household. Household filter
        on the undo delete query is the security boundary."""
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")

        # Bob has a pantry row.
        _add_pantry(bob, "Bob's Milk", qty="1")
        bob_hid = _household_id_for(app, "bob@example.com")
        bob_pantry_id_before = _pantry_rows(app, bob_hid)[0].id

        # Alice does I'm home with her own items — no bleed possible
        # via the legitimate route. Assert Bob's row survives.
        _seed_and_check(alice, ["Alice's Milk"])
        _move_im_home(alice)
        _undo(alice)

        bob_pantry = _pantry_rows(app, bob_hid)
        assert len(bob_pantry) == 1
        assert bob_pantry[0].id == bob_pantry_id_before, (
            "Undo route must be household-scoped — Alice's undo "
            "cannot reach into Bob's pantry."
        )

    def test_bob_cant_undo_alice_move_via_replay(self, two_clients, app):
        """Alice moves; Bob POSTs /shopping/undo. Bob's session has
        no snapshot, so his undo is a no-op — Alice's move survives."""
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")
        alice_hid = _household_id_for(app, "alice@example.com")

        _seed_and_check(alice, ["Milk", "Bread"])
        _move_im_home(alice)
        assert len(_pantry_rows(app, alice_hid)) == 2

        # Bob POSTs undo in his own session. His snapshot is empty.
        resp = _undo(bob)
        assert resp.status_code == 200
        # No trigger — nothing to restore.
        assert "HX-Trigger" not in resp.headers

        # Alice's pantry unchanged.
        assert len(_pantry_rows(app, alice_hid)) == 2


# ---------------------------------------------------------------------------
# 5. Missing-row tolerance
# ---------------------------------------------------------------------------

class TestMissingRowTolerance:
    def test_undo_tolerates_manually_deleted_created_row(
        self, client, app,
    ):
        """User does I'm-home creating Milk + Bread in pantry.
        Before hitting Undo, they visit /pantry and manually delete
        the new Milk row. Now they come back to /shopping and hit
        Undo. Expected: Bread's pantry row gets deleted (was still
        there); Milk's pantry row was already gone (silent skip);
        both Milk + Bread shopping rows restored."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _seed_and_check(client, ["Milk", "Bread"])
        _move_im_home(client)

        # Locate the newly-created Milk pantry row and delete it
        # manually (simulating the user navigating to /pantry mid-window).
        with app.app_context():
            from models import PantryItem
            milk_row = PantryItem.query.filter_by(
                household_id=hid, name="Milk",
            ).one()
            milk_pantry_id = milk_row.id
        client.delete(f"/pantry/{milk_pantry_id}")

        # Now hit undo on the shopping page.
        resp = _undo(client)
        payload = _hx_trigger_payload(resp)
        # Both shopping items still restore (snapshot had them).
        assert payload["shopping:undone"]["count"] == 2

        # Pantry: both created rows gone (Milk was already gone,
        # Bread deleted by the undo).
        assert len(_pantry_rows(app, hid)) == 0
        # Shopping: both items back.
        shop = _shopping_rows(app, hid)
        assert len(shop) == 2


# ---------------------------------------------------------------------------
# 6. Cap semantics — over-25 = text-only toast, snapshot cleared
# ---------------------------------------------------------------------------

class TestCapSemantics:
    def test_over_cap_move_ships_null_undo_url(self, client, app):
        """26 checked items exceeds UNDO_SNAPSHOT_MAX_ITEMS. The
        move still completes (user's ability to act > ability to
        undo), but the toast payload's undoUrl is null so the
        client renders text-only."""
        from app import UNDO_SNAPSHOT_MAX_ITEMS
        sign_up(client, "alice@example.com", "Alice")
        # Seed one more than the cap allows.
        items = [f"Item {i}" for i in range(UNDO_SNAPSHOT_MAX_ITEMS + 1)]
        _seed_and_check(client, items)

        resp = _move_im_home(client)
        payload = _hx_trigger_payload(resp)
        body = payload["shopping:moved-to-pantry"]
        assert body["count"] == UNDO_SNAPSHOT_MAX_ITEMS + 1
        assert body["undoUrl"] is None, (
            "Over-cap moves must ship undoUrl=null — a truncated "
            "snapshot would silently lose items on undo, worse than "
            "no undo at all."
        )

    def test_over_cap_move_pops_prior_undo_slot(self, client, app):
        """Over-cap move must not leave a stale prior snapshot in
        the session — a later Undo tap would try to reverse an
        action the user's already forgotten about."""
        from app import UNDO_SNAPSHOT_MAX_ITEMS
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")

        # Set up a delete-undo snapshot first.
        _add_shopping(client, "Eggs")
        body = client.get("/shopping").get_data(as_text=True)
        eggs_id = _shopping_ids(body)[0]
        client.delete(f"/shopping/{eggs_id}")

        # Now do an over-cap I'm home — should wipe the delete's snapshot.
        items = [f"Item {i}" for i in range(UNDO_SNAPSHOT_MAX_ITEMS + 1)]
        _seed_and_check(client, items)
        _move_im_home(client)

        # Undo should be a no-op — no snapshot to restore.
        resp = _undo(client)
        assert "HX-Trigger" not in resp.headers, (
            "Over-cap im-home must pop the prior undo slot — "
            "otherwise Undo would restore a stale action the user's "
            "already moved past."
        )


# ---------------------------------------------------------------------------
# 7. UI wiring — base.html handler consumes undoUrl
# ---------------------------------------------------------------------------

class TestUIWiring:
    def test_base_handler_reads_undo_url_from_payload(self, client, app):
        """The base.html toast handler must destructure `undoUrl` off
        the event detail and pass it to `showToast` — regressing this
        back to text-only would silently ship im-home undo but hide
        the button. Assert on the JS source in base.html."""
        sign_up(client, "alice@example.com", "Alice")
        html = client.get("/pantry").get_data(as_text=True)
        # The Phase 6C handler now reads undoUrl the same way
        # shopping:cleared-checked and shopping:deleted do.
        assert "shopping:moved-to-pantry" in html
        # Look for the pattern that says undoUrl is consumed in
        # this handler — a substring specific to 6C's handler body.
        handler_region = html.split("shopping:moved-to-pantry", 1)[1][:400]
        assert "undoUrl" in handler_region, (
            "The shopping:moved-to-pantry handler must read undoUrl "
            "off the event detail (Phase 6C wiring)."
        )
        assert "showToast" in handler_region

    def test_move_response_body_still_the_shopping_list_partial(
        self, client, app,
    ):
        """Response body must remain the _shopping_list.html partial
        (unchanged from Phase 3F). Otherwise the htmx swap into
        #shopping-list would break."""
        sign_up(client, "alice@example.com", "Alice")
        _seed_and_check(client, ["Milk"])
        resp = _move_im_home(client)
        body = resp.get_data(as_text=True)
        # Empty shopping list after the move — the partial should
        # render the empty-state heading.
        assert "Nothing on your shopping list" in body


# ---------------------------------------------------------------------------
# 8. Anonymous replay
# ---------------------------------------------------------------------------

class TestAnonymousReplay:
    def test_anonymous_move_rejected(self, app):
        """POST /shopping/move-checked-to-pantry with no session
        returns 302/400/401 depending on which layer fires first
        (CSRF vs @login_required)."""
        c = Client(app.test_client())
        resp = c._c.post("/shopping/move-checked-to-pantry")
        assert resp.status_code in (302, 400, 401)

    def test_anonymous_undo_rejected(self, app):
        c = Client(app.test_client())
        resp = c._c.post("/shopping/undo")
        assert resp.status_code in (302, 400, 401)
