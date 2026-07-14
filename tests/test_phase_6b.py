"""
Phase 6B regression suite — duplicate detection on pantry add.

Adding a pantry item whose name matches (case-insensitive, whitespace-
trimmed) an existing pantry row in the household now surfaces a
duplicate-confirm card instead of blindly creating a second row.

The card presents three choices via three routes:

  1. **Update existing** → POST /pantry/merge/<existing_id> with the
     pending payload. Quantities sum, existing unit wins (differences
     migrate to notes), notes concatenate with a bullet separator.
     Preserves `added_at` + `added_by_user_id` on the target row.

  2. **Add as separate row** → POST /pantry?force_duplicate=1 with
     the pending payload. Skips the dupe check, creates a second row
     (same as the pre-6B behavior). This intentionally allows the
     "I do want two Milks" case (e.g., regular + almond, spelled
     the same for legacy reasons).

  3. **Cancel** → pure client-side; removes the card from the DOM
     via hx-on:click. Preserved by an HX-Detour response header on
     the dupe response, which the pantry add form's
     `hx-on::after-request` reads to skip its auto-reset. So the
     user's typed values still sit in the input fields after Cancel.

These tests guard:

  1. Dupe detection triggers on same-name (exact, case-mismatch,
     whitespace-padded) and household-scoped (a match in Alice's
     household doesn't collide with Bob's separate household);
     roommates in the SAME household DO collide (shared pantry).
  2. Confirm card renders with existing-row context + hidden pending
     payload + HX-Retarget/Reswap/Detour response headers.
  3. Merge route semantics — qty sum with None-aware arithmetic;
     unit preservation with conflict-into-notes; notes concat; no
     touch to `added_at` / `added_by_user_id`.
  4. Merge fires `pantry:merged` HX-Trigger toast with the target
     row's name (40-char capped for mobile).
  5. Force-duplicate path (?force_duplicate=1) skips the check and
     creates a second row; onboarding-zone crossing still triggers
     HX-Refresh on that path.
  6. OOB clear of #pantry-dupe-confirm-slot is emitted on merge +
     force-duplicate paths so the confirm card disappears in the
     same swap that updates the list.
  7. Non-HX-Request adds (legacy fallback path) SKIP the dupe check
     entirely — validation for that flow is intentionally lax so
     the rare non-htmx submitter isn't served an unusable partial.
  8. UI wiring — HTML slot, form-reset guard, base.html handler.

Tier-1 dev loop:

    pytest tests/test_phase_6b.py -q
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
                notes: str = "", *, force_duplicate: bool = False,
                htmx: bool = True):
    """POST /pantry as htmx by default. `force_duplicate=True` appends
    the query flag that skips dupe detection (the Add-as-separate-row
    button on the confirm card is a real caller of this path)."""
    url = "/pantry?force_duplicate=1" if force_duplicate else "/pantry"
    return c.post(url, htmx=htmx, data={
        "name": name, "quantity": qty, "unit": unit, "notes": notes,
        "submit": "Add",
    })


def _pantry_ids(html: str) -> list[str]:
    return re.findall(r'id="pantry-item-(\d+)"', html)


def _pantry_row_count(app, household_id: int) -> int:
    with app.app_context():
        from models import PantryItem
        return PantryItem.query.filter_by(
            household_id=household_id,
        ).count()


def _pantry_rows_named(app, household_id: int, name: str) -> list:
    """Return every pantry row in the household with a specific name
    (exact match — case + whitespace-sensitive). Ordered by id asc so
    the first row is the earliest."""
    with app.app_context():
        from models import PantryItem
        return (
            PantryItem.query
            .filter_by(household_id=household_id, name=name)
            .order_by(PantryItem.id.asc())
            .all()
        )


def _household_id_for(app, email: str) -> int:
    with app.app_context():
        from models import User
        return User.query.filter_by(email=email).first().household_id


def _seed_past_threshold(c: Client) -> None:
    """Push the household past the onboarding threshold so subsequent
    adds take the fast partial-swap path (not HX-Refresh). Reuses the
    starter-pantry seed for speed — 6 items in one call."""
    c.post("/pantry/seed-starter", htmx=True, data={})


def _hx_trigger_payload(resp) -> dict | None:
    header = resp.headers.get("HX-Trigger")
    if not header:
        return None
    return json.loads(header)


# ---------------------------------------------------------------------------
# 1. Duplicate detection — match rule + confirm-card response contract
# ---------------------------------------------------------------------------

class TestDuplicateDetection:
    def test_exact_match_triggers_confirm_card(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        _seed_past_threshold(client)
        _add_pantry(client, "Sriracha")

        resp = _add_pantry(client, "Sriracha")
        assert resp.status_code == 200
        assert resp.headers.get("HX-Retarget") == "#pantry-dupe-confirm-slot"
        assert resp.headers.get("HX-Reswap") == "innerHTML"
        assert resp.headers.get("HX-Detour") == "dupe-confirm", (
            "Dupe response must set HX-Detour so the add form's "
            "auto-reset handler skips resetting the user's input."
        )
        body = resp.get_data(as_text=True)
        assert 'id="dupe-confirm-card"' in body, (
            "Response body must render the confirm card partial."
        )
        assert "Sriracha" in body

    def test_case_insensitive_match(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        _seed_past_threshold(client)
        _add_pantry(client, "Milk")

        # Different case → still a dupe.
        resp = _add_pantry(client, "milk")
        assert resp.headers.get("HX-Retarget") == "#pantry-dupe-confirm-slot"

    def test_whitespace_trimmed_match(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        _seed_past_threshold(client)
        _add_pantry(client, "Milk")

        # Padded whitespace → still a dupe.
        resp = _add_pantry(client, "  Milk  ")
        assert resp.headers.get("HX-Retarget") == "#pantry-dupe-confirm-slot"

    def test_different_name_no_confirm(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        _seed_past_threshold(client)
        _add_pantry(client, "Milk")

        # Different name → straight through to normal add path.
        resp = _add_pantry(client, "Bread")
        assert resp.status_code == 200
        assert resp.headers.get("HX-Retarget") is None
        assert resp.headers.get("HX-Detour") is None

    def test_household_scoped_no_cross_household_dupe(self, two_clients, app):
        """Bob's separate household should never collide with Alice's
        pantry items. Bob adding 'Milk' when Alice has 'Milk' in a
        different household is a fresh add, not a dupe."""
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")
        _seed_past_threshold(alice)
        _seed_past_threshold(bob)
        _add_pantry(alice, "Milk")

        resp = _add_pantry(bob, "Milk")
        assert resp.headers.get("HX-Detour") is None, (
            "Bob's Milk should NOT be a dupe of Alice's Milk — "
            "separate households."
        )

    def test_household_scoped_dupe_for_roommates(self, two_clients, app):
        """But roommates in the SAME household DO share a pantry, so
        Bob adding 'Milk' when Alice already added 'Milk' to the
        shared pantry IS a dupe."""
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")

        # Move Bob into Alice's household (same trick 6A used).
        from models import User
        from extensions import db
        with app.app_context():
            a = User.query.filter_by(email="alice@example.com").one()
            b = User.query.filter_by(email="bob@example.com").one()
            b.household_id = a.household_id
            db.session.commit()

        _seed_past_threshold(alice)
        _add_pantry(alice, "Milk")

        resp = _add_pantry(bob, "Milk")
        assert resp.headers.get("HX-Detour") == "dupe-confirm", (
            "Roommates share a pantry — a dupe on Alice's row should "
            "trigger a confirm when Bob tries to add the same name."
        )

    def test_non_htmx_add_skips_dupe_check(self, client, app):
        """Legacy fallback: non-htmx form submissions bypass the dupe
        check entirely. Rare in practice (the pantry form always
        posts via htmx from a real browser), but a plain POST from
        curl or a test that doesn't set HX-Request just creates the
        row. This keeps the fallback path simple — a confirm card
        rendered outside an htmx context has no way to resolve."""
        sign_up(client, "alice@example.com", "Alice")
        _seed_past_threshold(client)
        _add_pantry(client, "Milk", htmx=True)

        # No htmx=True → no HX-Request header → dupe check skipped.
        resp = _add_pantry(client, "Milk", htmx=False)
        # Legacy path redirects to /pantry on success.
        assert resp.status_code in (200, 302), (
            f"Non-htmx dupe add should complete via legacy path; "
            f"got {resp.status_code}."
        )
        hid = _household_id_for(app, "alice@example.com")
        milks = _pantry_rows_named(app, hid, "Milk")
        assert len(milks) == 2, (
            "Non-htmx path should NOT surface the confirm; it just "
            "creates a second row."
        )


# ---------------------------------------------------------------------------
# 2. Confirm-card contents — pending payload + existing snapshot
# ---------------------------------------------------------------------------

class TestConfirmCardContents:
    def test_card_carries_pending_payload_in_hidden_inputs(
        self, client, app,
    ):
        """The confirm card renders hidden inputs with the user's
        pending values so the Merge / Add-anyway buttons can re-post
        them without a session round-trip."""
        sign_up(client, "alice@example.com", "Alice")
        _seed_past_threshold(client)
        _add_pantry(client, "Milk", qty="1", unit="gal")

        resp = _add_pantry(
            client, "Milk", qty="2", unit="gal", notes="organic",
        )
        body = resp.get_data(as_text=True)
        # Hidden inputs live inside the `data-pending` wrapper.
        assert 'name="name" value="Milk"' in body
        assert 'name="quantity"' in body and 'value="2.0"' in body
        assert 'name="unit" value="gal"' in body
        assert 'name="notes" value="organic"' in body

    def test_card_shows_existing_row_snapshot(self, client, app):
        """The card should tell the user WHICH existing row we matched
        against — display name + display_quantity() so the user can
        recognize their own row and decide with context."""
        sign_up(client, "alice@example.com", "Alice")
        _seed_past_threshold(client)
        _add_pantry(client, "Milk", qty="1", unit="gal", notes="whole")

        resp = _add_pantry(client, "Milk", qty="2", unit="gal")
        body = resp.get_data(as_text=True)
        assert "Milk" in body
        # display_quantity() renders "1 gal" for qty=1, unit=gal
        assert "1 gal" in body
        assert "whole" in body, (
            "Existing row's notes should surface on the card so the "
            "user knows exactly which row they're merging into."
        )

    def test_card_targets_merge_and_force_duplicate_routes(
        self, client, app,
    ):
        """Merge button posts to /pantry/merge/<id>; Add-as-separate
        posts to /pantry?force_duplicate=1. Assert on the actual URLs
        so a route-rename regression doesn't ship silently."""
        sign_up(client, "alice@example.com", "Alice")
        _seed_past_threshold(client)
        _add_pantry(client, "Milk")

        resp = _add_pantry(client, "Milk", qty="2")
        body = resp.get_data(as_text=True)
        hid = _household_id_for(app, "alice@example.com")
        # Find the existing Milk id
        existing_id = _pantry_rows_named(app, hid, "Milk")[0].id
        assert f'hx-post="/pantry/merge/{existing_id}"' in body
        assert 'hx-post="/pantry?force_duplicate=1"' in body


# ---------------------------------------------------------------------------
# 3. Merge route semantics
# ---------------------------------------------------------------------------

class TestMergeSemantics:
    def _post_merge(self, c: Client, existing_id: int, name: str,
                    qty: str = "", unit: str = "", notes: str = ""):
        return c.post(
            f"/pantry/merge/{existing_id}", htmx=True, data={
                "name": name, "quantity": qty, "unit": unit,
                "notes": notes, "submit": "Add",
            },
        )

    def test_qty_sums(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _seed_past_threshold(client)
        _add_pantry(client, "Milk", qty="1", unit="gal")

        existing_id = _pantry_rows_named(app, hid, "Milk")[0].id
        self._post_merge(client, existing_id, "Milk", qty="2", unit="gal")

        with app.app_context():
            from models import PantryItem
            from extensions import db
            row = db.session.get(PantryItem, existing_id)
            assert row.quantity == 3.0, (
                f"1 + 2 should be 3; got {row.quantity}."
            )
            assert row.unit == "gal"

    def test_qty_none_plus_qty_becomes_qty(self, client, app):
        """Existing qty is None (unquantified — 'we have milk'), user
        adds 'Milk 2 gal'. Merge should set qty to 2, not leave it
        None or explode on None + 2."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _seed_past_threshold(client)
        _add_pantry(client, "Milk")  # no qty

        existing_id = _pantry_rows_named(app, hid, "Milk")[0].id
        self._post_merge(client, existing_id, "Milk", qty="2", unit="gal")

        with app.app_context():
            from models import PantryItem
            from extensions import db
            row = db.session.get(PantryItem, existing_id)
            assert row.quantity == 2.0
            assert row.unit == "gal"

    def test_qty_plus_none_stays_qty(self, client, app):
        """Existing qty is 1, user merges 'Milk' with no qty. Result
        stays at 1 (no-op qty addition)."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _seed_past_threshold(client)
        _add_pantry(client, "Milk", qty="1", unit="gal")

        existing_id = _pantry_rows_named(app, hid, "Milk")[0].id
        self._post_merge(client, existing_id, "Milk")

        with app.app_context():
            from models import PantryItem
            from extensions import db
            row = db.session.get(PantryItem, existing_id)
            assert row.quantity == 1.0

    def test_unit_conflict_preserved_in_notes(self, client, app):
        """Existing unit is 'gal', pending unit is 'ml'. Merge should
        keep 'gal' on the row (existing wins) but migrate the pending
        unit context into notes so the info isn't silently lost."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _seed_past_threshold(client)
        _add_pantry(client, "Milk", qty="1", unit="gal")

        existing_id = _pantry_rows_named(app, hid, "Milk")[0].id
        self._post_merge(client, existing_id, "Milk", qty="500", unit="ml")

        with app.app_context():
            from models import PantryItem
            from extensions import db
            row = db.session.get(PantryItem, existing_id)
            assert row.unit == "gal", "Existing unit must win"
            assert "ml" in (row.notes or ""), (
                f"Pending unit context should migrate to notes; "
                f"got {row.notes!r}."
            )

    def test_notes_concatenate(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _seed_past_threshold(client)
        _add_pantry(client, "Milk", qty="1", unit="gal", notes="organic")

        existing_id = _pantry_rows_named(app, hid, "Milk")[0].id
        self._post_merge(
            client, existing_id, "Milk", qty="1", unit="gal",
            notes="whole",
        )

        with app.app_context():
            from models import PantryItem
            from extensions import db
            row = db.session.get(PantryItem, existing_id)
            # Both notes preserved with a separator
            assert "organic" in row.notes
            assert "whole" in row.notes

    def test_notes_identical_not_duplicated(self, client, app):
        """If the pending notes match existing notes exactly (post-
        strip), don't concatenate — that'd give us 'organic • organic'
        which is user-hostile."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _seed_past_threshold(client)
        _add_pantry(client, "Milk", qty="1", notes="organic")

        existing_id = _pantry_rows_named(app, hid, "Milk")[0].id
        self._post_merge(
            client, existing_id, "Milk", qty="1", notes="organic",
        )

        with app.app_context():
            from models import PantryItem
            from extensions import db
            row = db.session.get(PantryItem, existing_id)
            assert row.notes.count("organic") == 1, (
                f"Identical note should not duplicate; got {row.notes!r}."
            )

    def test_merge_preserves_added_at_and_provenance(
        self, two_clients, app,
    ):
        """Merging a row credited to Alice with Bob's pending fields
        keeps Alice as the added_by_user_id — merge augments an
        existing add, it doesn't rewrite history."""
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")

        from models import User
        from extensions import db
        with app.app_context():
            a = User.query.filter_by(email="alice@example.com").one()
            b = User.query.filter_by(email="bob@example.com").one()
            b.household_id = a.household_id
            db.session.commit()
            alice_uid = a.id
            hid = a.household_id

        _seed_past_threshold(alice)
        _add_pantry(alice, "Milk", qty="1", unit="gal")

        with app.app_context():
            from models import PantryItem
            from extensions import db
            existing = PantryItem.query.filter_by(
                household_id=hid, name="Milk",
            ).first()
            existing_id = existing.id
            original_added_at = existing.added_at

        self._post_merge(bob, existing_id, "Milk", qty="2", unit="gal")

        with app.app_context():
            from models import PantryItem
            from extensions import db
            row = db.session.get(PantryItem, existing_id)
            assert row.added_by_user_id == alice_uid, (
                "added_by_user_id must stay pinned to the original "
                "adder (Alice), not the merger (Bob)."
            )
            assert row.added_at == original_added_at, (
                "added_at must be unchanged — merge is not a new event."
            )

    def test_merge_fires_pantry_merged_trigger(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _seed_past_threshold(client)
        _add_pantry(client, "Milk", qty="1")

        existing_id = _pantry_rows_named(app, hid, "Milk")[0].id
        resp = self._post_merge(client, existing_id, "Milk", qty="2")

        assert resp.status_code == 200
        payload = _hx_trigger_payload(resp)
        assert payload is not None
        assert payload["pantry:merged"]["name"] == "Milk"

    def test_merge_response_oob_clears_confirm_slot(self, client, app):
        """The merge response body must contain an OOB clear for
        #pantry-dupe-confirm-slot so the card vanishes in the same
        swap that updates #pantry-list. Without this, the card
        would linger on the page after a merge — a subtle-but-
        obvious ghost UI bug."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _seed_past_threshold(client)
        _add_pantry(client, "Milk", qty="1")

        existing_id = _pantry_rows_named(app, hid, "Milk")[0].id
        resp = self._post_merge(client, existing_id, "Milk", qty="2")
        body = resp.get_data(as_text=True)
        assert 'id="pantry-dupe-confirm-slot"' in body
        assert 'hx-swap-oob="innerHTML"' in body

    def test_merge_cross_household_returns_404(self, two_clients, app):
        """Bob attempting to merge into Alice's separate-household
        pantry row must 404 — the household-scoping check on the
        target row is the same defense pantry-item edit/delete uses."""
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")

        _seed_past_threshold(alice)
        _add_pantry(alice, "Milk", qty="1")
        alice_hid = _household_id_for(app, "alice@example.com")
        existing_id = _pantry_rows_named(app, alice_hid, "Milk")[0].id

        # Bob (separate household) tries to merge into Alice's row
        resp = self._post_merge(bob, existing_id, "Milk", qty="99")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 4. Force-duplicate (Add as separate row) path
# ---------------------------------------------------------------------------

class TestForceDuplicate:
    def test_force_duplicate_skips_check_and_creates_second_row(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _seed_past_threshold(client)
        _add_pantry(client, "Milk", qty="1")

        resp = _add_pantry(client, "Milk", qty="2", force_duplicate=True)
        # Force path is a regular successful add — no HX-Detour, no
        # confirm partial.
        assert resp.status_code == 200
        assert resp.headers.get("HX-Detour") is None
        milks = _pantry_rows_named(app, hid, "Milk")
        assert len(milks) == 2

    def test_force_duplicate_response_oob_clears_confirm_slot(
        self, client, app,
    ):
        """The successful-add response body must include an OOB clear
        of the confirm slot — same reason as the merge case (kill the
        card in the same swap that updates the list)."""
        sign_up(client, "alice@example.com", "Alice")
        _seed_past_threshold(client)
        _add_pantry(client, "Milk", qty="1")

        resp = _add_pantry(client, "Milk", qty="2", force_duplicate=True)
        body = resp.get_data(as_text=True)
        assert 'id="pantry-dupe-confirm-slot"' in body
        assert 'hx-swap-oob="innerHTML"' in body

    def test_force_duplicate_still_hx_refreshes_on_crossing(
        self, client, app,
    ):
        """If the household is in the onboarding zone (count ≤ threshold),
        even a force-duplicate add should trigger HX-Refresh so the
        hero card / gate / ghost rows regenerate. The Phase 5A gate
        cares about total count, not the path the add came in on."""
        sign_up(client, "alice@example.com", "Alice")
        # Add one item so the empty-state doesn't fire, but stay in zone
        _add_pantry(client, "Milk", qty="1")
        # Second add still in the zone (count → 2 ≤ 3 threshold)
        resp = _add_pantry(
            client, "Milk", qty="2", force_duplicate=True,
        )
        assert resp.status_code == 204
        assert resp.headers.get("HX-Refresh") == "true"


# ---------------------------------------------------------------------------
# 5. Onboarding-zone interaction on the dupe check itself
# ---------------------------------------------------------------------------

class TestOnboardingZoneInteraction:
    def test_dupe_check_in_zone_still_shows_confirm(self, client, app):
        """A dupe attempt while the household is in the onboarding
        zone should still show the confirm card, not fall through
        to the HX-Refresh path. Rationale: showing the card avoids
        an accidental double-add during ramp-up, and the confirm
        renders without touching pantry_items count (so the zone
        state is unchanged during the decision)."""
        sign_up(client, "alice@example.com", "Alice")
        # In the zone: just 2 items after these adds.
        _add_pantry(client, "Milk", qty="1")  # crossing? new_count=1
        # First add went through HX-Refresh path since we were empty.
        # Add Milk again → should surface confirm, not HX-Refresh.
        resp = _add_pantry(client, "Milk", qty="2")
        # Dupe response is 200 + HX-Retarget (NOT 204 + HX-Refresh).
        assert resp.status_code == 200
        assert resp.headers.get("HX-Refresh") is None
        assert resp.headers.get("HX-Detour") == "dupe-confirm"


# ---------------------------------------------------------------------------
# 6. UI wiring
# ---------------------------------------------------------------------------

class TestUIWiring:
    def test_pantry_html_has_confirm_slot(self, client, app):
        """The slot's ID must exist on every /pantry render — server-
        pushed dupe partials rely on this ID via HX-Retarget."""
        sign_up(client, "alice@example.com", "Alice")
        html = client.get("/pantry").get_data(as_text=True)
        assert 'id="pantry-dupe-confirm-slot"' in html

    def test_add_form_reset_guard_respects_hx_detour(self, client, app):
        """The pantry add form's hx-on::after-request must read
        HX-Detour off the response — if that gets regressed back to
        the old unconditional reset, the user's typed values will
        disappear the moment the dupe response lands, breaking the
        Cancel-and-tweak flow."""
        sign_up(client, "alice@example.com", "Alice")
        html = client.get("/pantry").get_data(as_text=True)
        # Look for the guarded reset expression
        assert "getResponseHeader('HX-Detour')" in html, (
            "Pantry add form must consult HX-Detour before resetting. "
            "Regressing back to `if (event.detail.successful) this.reset()` "
            "would wipe the user's input on every dupe response."
        )

    def test_pantry_merged_handler_in_base(self, client, app):
        """Base layout must wire up the pantry:merged event handler
        so the confirmation toast fires when the HX-Trigger event
        lands after a merge."""
        sign_up(client, "alice@example.com", "Alice")
        html = client.get("/pantry").get_data(as_text=True)
        assert "pantry:merged" in html, (
            "base.html should carry the pantry:merged event handler "
            "(added in Phase 6B)."
        )

    def test_anonymous_merge_fails(self, app):
        """POST /pantry/merge/<id> is @login_required + CSRF-guarded.
        Anon POST yields 302/400/401 depending on which layer fires
        first — same shape as the shopping/pantry undo negative test."""
        from tests.conftest import Client
        client = Client(app.test_client())
        resp = client._c.post("/pantry/merge/1")
        assert resp.status_code in (302, 400, 401)
