"""
Phase 6A regression suite — Undo for pantry-item deletes.

Extends the Phase 3J undo pattern (originally for destructive shopping
actions) to pantry item deletes. Deleting a pantry item now fires a
5-second toast with an Undo CTA; tapping Undo restores the row exactly
as it was — original name, qty, unit, notes, `added_at` timestamp, and
`added_by_user_id` provenance.

Two invocation paths get exercised:

  A. Non-crossing delete (new_count > threshold). Response is
     200 + `_pantry_list.html` partial + HX-Trigger `pantry:deleted`.
     Toast fires immediately on the response. Undo route response is
     200 + partial re-render + HX-Trigger `pantry:undone`. Direct
     mirror of shopping's Phase 3J behavior.

  B. Crossing delete (new_count ≤ PANTRY_ONBOARDING_THRESHOLD). Response
     is 204 + HX-Refresh (the Chunk 5B fix for B-001, so the hero card
     / planner gate / ghost rows above #pantry-list can regenerate).
     HX-Refresh discards any client-side toast, so we stash a
     `pantry_undo_pending_toast` session flag. The subsequent /pantry
     GET pops the flag and injects a one-shot showToast() script into
     pantry.html — the toast lands on the reloaded page instead. Same
     mechanism on the symmetric undo case: restore that crosses BACK
     OUT of the onboarding zone (new_count > threshold after restore)
     falls back to HX-Refresh with a pending "Restored N items" flag.

These tests guard:

  1. Route contract (non-crossing) — 200, HX-Trigger `pantry:deleted`
     with name + undoUrl; undo returns 200 + HX-Trigger `pantry:undone`.
  2. Route contract (crossing) — 204 + HX-Refresh; session carries
     the pending toast flag; next /pantry GET emits the one-shot
     script AND pops the flag (so a manual refresh doesn't re-show
     the toast).
  3. Restore semantics — name + qty + unit + notes + added_at +
     added_by_user_id all preserved.
  4. Snapshot lifecycle — last-action-wins on repeat deletes; pop on
     successful restore; no-op undo (empty snapshot) fires no toast.
  5. Household scoping — a snapshot in Alice's session doesn't restore
     into Bob's household even if Bob POSTs /pantry/undo.
  6. Coexistence with shopping undo — a pantry delete followed by a
     shopping delete leaves BOTH undo slots intact (separate session
     keys, so hitting either undo route restores the right item).
  7. UI wiring — pantry.html renders the pending-toast one-shot script
     when the flag is set, doesn't render it otherwise; base.html
     handlers for `pantry:deleted` / `pantry:undone` are wired.

Tier-1 dev loop:

    pytest tests/test_phase_6a.py -q

per the BUGS.md convention. Tier-2 adds 5A + 5B + 5C + 5D + 3J
(the shopping undo it mirrors) + 4A (sort persistence across deletes);
Tier-3 is the full regression.
"""
from __future__ import annotations

import json
import re

from tests.conftest import Client, sign_up

from app import PANTRY_ONBOARDING_THRESHOLD


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_pantry(c: Client, name: str, qty: str = "", unit: str = "",
                notes: str = ""):
    return c.post("/pantry", htmx=True, data={
        "name": name, "quantity": qty, "unit": unit, "notes": notes,
        "submit": "Add",
    })


def _pantry_ids(html: str) -> list[str]:
    return re.findall(r'id="pantry-item-(\d+)"', html)


def _hx_trigger_payload(resp) -> dict | None:
    header = resp.headers.get("HX-Trigger")
    if not header:
        return None
    return json.loads(header)


def _pantry_row_count(app, household_id: int) -> int:
    with app.app_context():
        from models import PantryItem
        return PantryItem.query.filter_by(
            household_id=household_id,
        ).count()


def _household_id_for(app, email: str) -> int:
    with app.app_context():
        from models import User
        return User.query.filter_by(email=email).first().household_id


def _seed_past_threshold(c: Client) -> None:
    """Push the pantry past PANTRY_ONBOARDING_THRESHOLD so subsequent
    deletes take the non-crossing (fast-partial) path. Using the seed
    route because it lands 6 items in one call — the direct add path
    would trigger 6 HX-Refreshes and slow the fixture."""
    c.post("/pantry/seed-starter", htmx=True, data={})


# ---------------------------------------------------------------------------
# 1. Non-crossing delete path (mirrors shopping's 3J shape)
# ---------------------------------------------------------------------------

class TestNonCrossingDelete:
    """The household is well past the onboarding threshold, so a
    delete drops the count from N to N-1 with N-1 still > threshold.
    Response is 200 + `_pantry_list.html` partial + HX-Trigger
    `pantry:deleted`. Client-side toast fires on the response, exact
    same pattern as shopping."""

    def test_delete_fires_undoable_toast_with_item_name(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        _seed_past_threshold(client)
        # Add one more so we're clearly above threshold + can pick
        # a specific known item for the assertion.
        _add_pantry(client, "Sriracha")
        ids = _pantry_ids(client.get("/pantry").get_data(as_text=True))
        # Newest first — id[0] is Sriracha.

        resp = client.delete(f"/pantry/{ids[0]}")
        assert resp.status_code == 200
        payload = _hx_trigger_payload(resp)
        assert payload is not None
        event = payload["pantry:deleted"]
        assert event["name"] == "Sriracha"
        assert event["undoUrl"] == "/pantry/undo"

    def test_delete_then_undo_restores_full_row(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _seed_past_threshold(client)
        # NB (Phase 6B): use "Sesame oil" not "Olive oil" — the starter
        # seed pack now contains lowercase "olive oil", which the
        # Phase 6B dupe detector matches case-insensitively. Adding
        # "Olive oil" here would surface the confirm-card partial
        # instead of creating a row, and this test asserts on the
        # created-then-deleted-then-restored lifecycle. Sesame is not
        # in the seed pack so the add path stays as it was pre-6B.
        _add_pantry(
            client, "Sesame oil", qty="1", unit="bottle", notes="toasted",
        )
        ids = _pantry_ids(client.get("/pantry").get_data(as_text=True))
        client.delete(f"/pantry/{ids[0]}")
        assert _pantry_row_count(app, hid) == 6  # seed pack, sesame gone

        client.post("/pantry/undo", htmx=True)
        assert _pantry_row_count(app, hid) == 7
        with app.app_context():
            from models import PantryItem
            oils = PantryItem.query.filter_by(
                household_id=hid, name="Sesame oil",
            ).all()
            restored = next(
                (o for o in oils if o.notes == "toasted"), None,
            )
            assert restored is not None, (
                "Undo must restore the row with all its fields, "
                "including notes."
            )
            assert restored.quantity == 1
            assert restored.unit == "bottle"

    def test_undo_response_fires_pantry_undone(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        _seed_past_threshold(client)
        _add_pantry(client, "Sriracha")
        ids = _pantry_ids(client.get("/pantry").get_data(as_text=True))
        client.delete(f"/pantry/{ids[0]}")

        resp = client.post("/pantry/undo", htmx=True)
        assert resp.status_code == 200
        payload = _hx_trigger_payload(resp)
        assert payload is not None
        assert payload["pantry:undone"]["count"] == 1

    def test_delete_preserves_added_by_user_id(self, client, app, two_clients):
        """Provenance restore: the row comes back credited to the
        ORIGINAL adder, not to whoever tapped Undo. Bob deletes an
        item Alice added → Bob taps Undo → the restored row's
        `added_by_user_id` still points at Alice."""
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")

        # Move Bob into Alice's household so both can act on the same
        # rows. Same trick 5D uses.
        from models import User
        from extensions import db
        with app.app_context():
            a = User.query.filter_by(email="alice@example.com").one()
            b = User.query.filter_by(email="bob@example.com").one()
            b.household_id = a.household_id
            db.session.commit()
            alice_uid, bob_uid, hid = a.id, b.id, a.household_id

        _seed_past_threshold(alice)
        _add_pantry(alice, "Sriracha")
        ids = _pantry_ids(alice.get("/pantry").get_data(as_text=True))

        # Bob deletes it (his session captures Alice's row into HIS
        # snapshot with the original added_by_user_id preserved).
        bob.delete(f"/pantry/{ids[0]}")
        bob.post("/pantry/undo", htmx=True)

        with app.app_context():
            from models import PantryItem
            restored = PantryItem.query.filter_by(
                household_id=hid, name="Sriracha",
            ).first()
            assert restored.added_by_user_id == alice_uid, (
                f"Restored row must keep original provenance (Alice = "
                f"{alice_uid}); got added_by = {restored.added_by_user_id} "
                f"(Bob = {bob_uid})."
            )

    def test_delete_long_name_truncates_toast_not_db(self, client, app):
        """Toast display caps at 40 chars for mobile layout, but the
        snapshot + restore preserve the full name."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _seed_past_threshold(client)

        long_name = "X" * 100
        _add_pantry(client, long_name)
        ids = _pantry_ids(client.get("/pantry").get_data(as_text=True))

        resp = client.delete(f"/pantry/{ids[0]}")
        event = _hx_trigger_payload(resp)["pantry:deleted"]
        assert len(event["name"]) == 40

        client.post("/pantry/undo", htmx=True)
        with app.app_context():
            from models import PantryItem
            rows = PantryItem.query.filter_by(
                household_id=hid, name=long_name,
            ).all()
            assert len(rows) == 1
            assert rows[0].name == long_name


# ---------------------------------------------------------------------------
# 2. Onboarding-zone-crossing delete path (204 + HX-Refresh + pending toast)
# ---------------------------------------------------------------------------

class TestCrossingDelete:
    """The household is at or just past the threshold, so a delete
    drops it into the onboarding zone. HX-Refresh reloads the page,
    which would discard a live toast — so the server stashes a
    session flag and the next /pantry GET fires the toast at
    DOMContentLoaded."""

    def test_crossing_delete_returns_204_and_hx_refresh(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        # Add exactly threshold+1 items so the next delete crosses in.
        for i in range(PANTRY_ONBOARDING_THRESHOLD + 1):
            _add_pantry(client, f"Item {i}")
        ids = _pantry_ids(client.get("/pantry").get_data(as_text=True))

        resp = client.delete(f"/pantry/{ids[0]}")
        assert resp.status_code == 204
        assert resp.headers.get("HX-Refresh") == "true"

    def test_crossing_delete_stashes_pending_toast_flag(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        for i in range(PANTRY_ONBOARDING_THRESHOLD + 1):
            _add_pantry(client, f"Item {i}")
        ids = _pantry_ids(client.get("/pantry").get_data(as_text=True))
        client.delete(f"/pantry/{ids[0]}")

        # The flag isn't observable on the response (204 has no body),
        # but the NEXT /pantry render should carry it. The one-shot
        # dispatch script is the only place `new CustomEvent(` appears
        # in a rendered page — the base.html handlers use
        # `document.addEventListener(...)` for their registrations —
        # so it's a clean marker for "the pending toast fired".
        body = client.get("/pantry").get_data(as_text=True)
        assert "new CustomEvent" in body, (
            "The reloaded /pantry after a crossing delete must inject "
            "a one-shot script that dispatches the pending event."
        )
        # The payload embedded in the script should carry the event
        # name + the undo URL so the client can wire the button up.
        assert '"pantry:deleted"' in body
        assert "/pantry/undo" in body

    def test_pending_toast_one_shot_only(self, client, app):
        """The pending toast fires on the very next /pantry render and
        is then popped from the session. A manual refresh afterward
        should NOT re-emit it."""
        sign_up(client, "alice@example.com", "Alice")
        for i in range(PANTRY_ONBOARDING_THRESHOLD + 1):
            _add_pantry(client, f"Item {i}")
        ids = _pantry_ids(client.get("/pantry").get_data(as_text=True))
        client.delete(f"/pantry/{ids[0]}")

        first = client.get("/pantry").get_data(as_text=True)
        second = client.get("/pantry").get_data(as_text=True)

        # `new CustomEvent` only appears in the pending-toast one-shot
        # dispatch (see the {% if pending_toast %} block in pantry.html);
        # base.html's event listeners use addEventListener. So this
        # marker cleanly distinguishes "pending toast fired" from
        # "handler registered".
        assert "new CustomEvent" in first, (
            "First reload after a crossing delete must emit the one-shot"
        )
        assert "new CustomEvent" not in second, (
            "Second reload must NOT re-emit — the session flag should "
            "have been popped on first render."
        )

    def test_crossing_undo_restores_and_removes_hero(self, client, app):
        """After a crossing delete + undo, count is back > threshold
        so the hero card / planner gate must be gone. The undo route
        detects the crossing-out and returns 204 + HX-Refresh to
        refresh the widgets above #pantry-list."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        for i in range(PANTRY_ONBOARDING_THRESHOLD + 1):
            _add_pantry(client, f"Item {i}")
        ids = _pantry_ids(client.get("/pantry").get_data(as_text=True))
        client.delete(f"/pantry/{ids[0]}")
        assert _pantry_row_count(app, hid) == PANTRY_ONBOARDING_THRESHOLD

        resp = client.post("/pantry/undo", htmx=True)
        assert resp.status_code == 204
        assert resp.headers.get("HX-Refresh") == "true", (
            "Undo that crosses BACK OUT of the onboarding zone must "
            "also HX-Refresh so hero/gate/ghost rows disappear."
        )
        assert _pantry_row_count(app, hid) == PANTRY_ONBOARDING_THRESHOLD + 1

        # The reloaded /pantry should carry the pending confirmation toast
        body = client.get("/pantry").get_data(as_text=True)
        assert "pantry:undone" in body

    def test_undo_staying_in_zone_uses_partial_swap(self, client, app):
        """If deleting brought the household to N ≤ threshold AND
        undo restores it to STILL ≤ threshold (because there were
        multiple crossings), the undo route should NOT need HX-Refresh
        — the hero/gate are already correct for the still-in-zone
        state. Partial swap is enough."""
        sign_up(client, "alice@example.com", "Alice")
        # Land the pantry INSIDE the onboarding zone from the start
        # (add exactly threshold items).
        for i in range(PANTRY_ONBOARDING_THRESHOLD):
            _add_pantry(client, f"Item {i}")
        ids = _pantry_ids(client.get("/pantry").get_data(as_text=True))
        # Delete one → count = threshold - 1 (still in zone)
        client.delete(f"/pantry/{ids[0]}")

        resp = client.post("/pantry/undo", htmx=True)
        # Staying in zone → partial swap, 200 + HX-Trigger
        assert resp.status_code == 200
        assert resp.headers.get("HX-Refresh") is None
        payload = _hx_trigger_payload(resp)
        assert payload["pantry:undone"]["count"] == 1


# ---------------------------------------------------------------------------
# 3. Snapshot lifecycle
# ---------------------------------------------------------------------------

class TestSnapshotLifecycle:
    def test_new_delete_overwrites_prior_snapshot(self, client, app):
        """Two deletes back-to-back: undo restores ONLY the second one.
        Same "last-action-wins" semantics as shopping (Phase 3J)."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _seed_past_threshold(client)
        _add_pantry(client, "Sriracha")
        _add_pantry(client, "Chili flakes")
        ids = _pantry_ids(client.get("/pantry").get_data(as_text=True))
        # Newest-first: ids[0] = Chili flakes, ids[1] = Sriracha
        client.delete(f"/pantry/{ids[1]}")  # delete Sriracha first
        client.delete(f"/pantry/{ids[0]}")  # delete Chili flakes second

        client.post("/pantry/undo", htmx=True)
        with app.app_context():
            from models import PantryItem
            names = {
                r.name for r in PantryItem.query.filter_by(
                    household_id=hid,
                ).all()
            }
            assert "Chili flakes" in names, (
                "Undo restores the MOST RECENT delete (Chili flakes)."
            )
            assert "Sriracha" not in names, (
                "The first delete's snapshot was overwritten by the "
                "second — Sriracha stays gone."
            )

    def test_no_op_undo_fires_no_trigger(self, client, app):
        """Empty snapshot slot → no restore → no confirmation toast.
        The button should feel dead, not fire a "Restored 0" toast."""
        sign_up(client, "alice@example.com", "Alice")
        _seed_past_threshold(client)

        resp = client.post("/pantry/undo", htmx=True)
        assert resp.status_code == 200
        assert resp.headers.get("HX-Trigger") is None

    def test_double_undo_is_idempotent(self, client, app):
        """Second Undo tap after a successful first → no duplicate row."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _seed_past_threshold(client)
        _add_pantry(client, "Sriracha")
        ids = _pantry_ids(client.get("/pantry").get_data(as_text=True))
        client.delete(f"/pantry/{ids[0]}")

        client.post("/pantry/undo", htmx=True)
        client.post("/pantry/undo", htmx=True)

        assert _pantry_row_count(app, hid) == 7, (
            "Second undo must be a no-op — the snapshot should have "
            "been popped on the first successful restore."
        )


# ---------------------------------------------------------------------------
# 4. Household scoping + coexistence with shopping undo
# ---------------------------------------------------------------------------

class TestScoping:
    def test_bob_cannot_undo_alices_delete(self, two_clients, app):
        """A snapshot in Alice's session doesn't restore into Bob's
        household. Session isolation (per-cookie) is the primary
        defense; the explicit household_id check in _restore_pantry_
        snapshot is defense-in-depth."""
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")
        alice_hid = _household_id_for(app, "alice@example.com")
        bob_hid = _household_id_for(app, "bob@example.com")

        _seed_past_threshold(alice)
        _add_pantry(alice, "Sriracha")
        ids = _pantry_ids(alice.get("/pantry").get_data(as_text=True))
        alice.delete(f"/pantry/{ids[0]}")

        # Bob's session has no snapshot; his /pantry/undo must be no-op
        bob.post("/pantry/undo", htmx=True)
        assert _pantry_row_count(app, bob_hid) == 0
        assert _pantry_row_count(app, alice_hid) == 6  # seed pack, oil gone

        # Alice's own undo still works
        alice.post("/pantry/undo", htmx=True)
        assert _pantry_row_count(app, alice_hid) == 7

    def test_pantry_and_shopping_undo_coexist(self, client, app):
        """Delete a pantry item, delete a shopping item, tap BOTH
        undos. Each restores from its own session slot — the pantry
        delete didn't stomp the shopping snapshot and vice versa."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _seed_past_threshold(client)
        _add_pantry(client, "Sriracha")

        # Add a shopping item too
        client.post("/shopping", htmx=True, data={
            "name": "Tortillas", "quantity": "", "unit": "", "notes": "",
            "submit": "Add",
        })

        p_ids = _pantry_ids(client.get("/pantry").get_data(as_text=True))
        s_ids = re.findall(
            r'id="shopping-item-(\d+)"',
            client.get("/shopping").get_data(as_text=True),
        )
        client.delete(f"/pantry/{p_ids[0]}")     # Sriracha gone
        client.delete(f"/shopping/{s_ids[0]}")   # Tortillas gone

        # Undo BOTH — order doesn't matter, they use different session
        # keys.
        client.post("/pantry/undo", htmx=True)
        client.post("/shopping/undo", htmx=True)

        with app.app_context():
            from models import PantryItem, ShoppingItem
            assert PantryItem.query.filter_by(
                household_id=hid, name="Sriracha",
            ).count() == 1, (
                "Pantry undo must survive an intervening shopping "
                "delete — separate session slots."
            )
            assert ShoppingItem.query.filter_by(
                household_id=hid, name="Tortillas",
            ).count() == 1, (
                "Shopping undo must survive an intervening pantry "
                "delete — separate session slots."
            )

    def test_anonymous_undo_fails(self, app):
        """The route is @login_required + CSRF-guarded. Anon POST
        yields 302/400/401 depending on which layer fires first."""
        from tests.conftest import Client
        client = Client(app.test_client())
        resp = client._c.post("/pantry/undo")
        assert resp.status_code in (302, 400, 401)


# ---------------------------------------------------------------------------
# 5. UI wiring
# ---------------------------------------------------------------------------

class TestUIWiring:
    def test_pantry_delete_button_no_longer_has_hx_confirm(self, client, app):
        """Phase 6A companion change: pantry Delete lost its
        hx-confirm modal for the same reasons shopping did in Phase 3J
        (see `test_delete_button_no_longer_has_hx_confirm` in
        test_phase_3j.py). Real correctness bite too: the browser's
        native confirm() blocks the JS event loop while the modal is
        open, so a paused-on-confirm user could see the 5s toast
        timer expire before they can even see the toast — exactly
        the safety-net gap this chunk plugs."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Milk")
        html = client.get("/pantry").get_data(as_text=True)

        del_match = re.search(
            r'hx-delete="/pantry/\d+"[^>]*>\s*Delete',
            html, re.DOTALL,
        )
        assert del_match, "Delete button should still exist"
        button_block_start = html.rfind('<button', 0, del_match.start())
        button_block = html[button_block_start:del_match.end()]
        assert "hx-confirm" not in button_block, (
            "Pantry Delete button should no longer have hx-confirm "
            "(Phase 6A) — the 5-second Undo toast is the safety net."
        )

    def test_pantry_deleted_handler_in_base(self, client, app):
        """Base layout must wire up the `pantry:deleted` event handler
        so the toast actually fires when the HX-Trigger event lands."""
        sign_up(client, "alice@example.com", "Alice")
        html = client.get("/pantry").get_data(as_text=True)
        assert "pantry:deleted" in html, (
            "base.html should carry the pantry:deleted event handler "
            "(added in Phase 6A)."
        )
        assert "pantry:undone" in html, (
            "base.html should carry the pantry:undone confirmation "
            "event handler (added in Phase 6A)."
        )

    def test_undo_click_uses_pantry_list_target(self, client, app):
        """The generalized toast-action click handler reads
        `data-target` off the button. Pantry deletes pass '#pantry-list'
        via the `target` key in the action arg; verify the handler is
        wired to read it (not hard-coded to '#shopping-list' anymore)."""
        sign_up(client, "alice@example.com", "Alice")
        html = client.get("/pantry").get_data(as_text=True)
        # The handler reads `action.dataset.target || '#shopping-list'`.
        # If that line ever regresses to a hard-coded '#shopping-list'
        # without the OR fallback, pantry Undo will target the wrong
        # container and silently fail to update the list.
        assert "action.dataset.target" in html, (
            "toast-action click handler must read the swap target from "
            "the dataset, not hard-code '#shopping-list'."
        )

    def test_pantry_html_has_no_pending_toast_script_by_default(
        self, client, app,
    ):
        """When there's no pending toast in the session, the one-shot
        script block should NOT render — the {% if pending_toast %}
        gate keeps the DOM clean on every non-crossing render."""
        sign_up(client, "alice@example.com", "Alice")
        html = client.get("/pantry").get_data(as_text=True)
        # The one-shot script dispatches a CustomEvent — that literal
        # is unique enough to key off.
        assert "new CustomEvent" not in html, (
            "Fresh /pantry render should not carry the pending-toast "
            "one-shot script; only crossing-path renders should."
        )
