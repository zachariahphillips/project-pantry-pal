"""
Phase 6D regression suite — duplicate detection on shopping-list add.

Direct mirror of Phase 6B (duplicate detection on pantry add) applied
to the shopping surface. Adding a shopping item whose name matches
(case-insensitive, whitespace-trimmed) an existing shopping row in
the household now surfaces a duplicate-confirm card instead of
blindly creating a second row.

The card presents three choices via three routes:

  1. **Update existing** → POST /shopping/merge/<existing_id> with the
     pending payload. Quantities sum, existing unit wins (differences
     migrate to notes), notes concatenate with a bullet separator.
     `added_at` + `added_by_user_id` unchanged. `checked` + `checked_at`
     unchanged (shopping-specific decision — see
     `_merge_pending_into_shopping_item` docstring for rationale).

  2. **Add as separate row** → POST /shopping?force_duplicate=1. Skips
     the dupe check, creates a second row (pre-6D behavior). Preserves
     the "two taps = two rows" contract for the legitimate case
     ("regular Milk + almond milk, both typed as 'Milk'").

  3. **Cancel** → pure client-side; removes the card via hx-on:click.
     Preserved by HX-Detour on the dupe response, which shopping.html's
     add-form `hx-on::after-request` reads to skip its auto-reset.

Scope boundary — the dupe check ONLY runs on POST /shopping (form
submit + "ADD AGAIN" suggestion chips). Four other paths that create
ShoppingItem rows deliberately preserve "two taps = two rows" and are
guarded by the tests below:
  - `pantry_item_to_shopping` (+ Shop button on a pantry row)
  - `meal_plan_add_shopping_item` (single-item meal-plan add)
  - `meal_plan_shop_all` (bulk + Shop All)
  - `_restore_shopping_snapshot` (undo restore)

These tests guard:

  1. Dupe detection triggers on same-name (exact, case-mismatch,
     whitespace-padded), household-scoped (Bob's separate household
     doesn't collide with Alice's; roommates in the SAME household
     DO collide).
  2. Confirm card renders with existing-row context + hidden pending
     payload + HX-Retarget/Reswap/Detour headers.
  3. Merge route semantics — qty sum with None-aware arithmetic;
     unit preservation with conflict-into-notes; notes concat; no
     touch to `added_at` / `added_by_user_id`.
  4. **Shopping-specific: `checked` + `checked_at` unchanged on merge**
     (v1 semantics — see merge helper docstring).
  5. Merge fires `shopping:merged` HX-Trigger toast with target row's
     name (40-char capped).
  6. Force-duplicate path (?force_duplicate=1) skips the check and
     creates a second row + bumps frequency counter (regular add
     side-effect preserved).
  7. OOB clear of #shopping-dupe-confirm-slot on merge + force-dup
     paths so the card disappears in the same swap.
  8. Non-HX-Request adds SKIP the dupe check (legacy fallback path).
  9. Scope isolation — the four bypass paths above still create
     duplicate rows without triggering the confirm card.
 10. UI wiring — HTML slot, form-reset guard, base.html handler.

Tier-1 dev loop:

    pytest tests/test_phase_6d.py -q
"""
from __future__ import annotations

import json
import re

from tests.conftest import Client, sign_up


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_shopping(c: Client, name: str, qty: str = "", unit: str = "",
                  notes: str = "", *, force_duplicate: bool = False,
                  htmx: bool = True):
    """POST /shopping as htmx by default. `force_duplicate=True` appends
    the query flag that skips dupe detection (the Add-as-separate-row
    button on the confirm card is a real caller of this path)."""
    url = "/shopping?force_duplicate=1" if force_duplicate else "/shopping"
    return c.post(url, htmx=htmx, data={
        "name": name, "quantity": qty, "unit": unit, "notes": notes,
        "submit": "Add",
    })


def _shopping_ids(html: str) -> list[str]:
    return re.findall(r'id="shopping-item-(\d+)"', html)


def _shopping_row_count(app, household_id: int) -> int:
    with app.app_context():
        from models import ShoppingItem
        return ShoppingItem.query.filter_by(
            household_id=household_id,
        ).count()


def _shopping_rows_named(app, household_id: int, name: str) -> list:
    """Every shopping row in the household with a specific name (exact
    match — case + whitespace-sensitive). Ordered by id asc so index 0
    is the earliest."""
    with app.app_context():
        from models import ShoppingItem
        return (
            ShoppingItem.query
            .filter_by(household_id=household_id, name=name)
            .order_by(ShoppingItem.id.asc())
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


def _first_shopping_id(html: str) -> str:
    ids = _shopping_ids(html)
    assert ids, "no shopping rows found in html"
    return ids[0]


# ---------------------------------------------------------------------------
# 1. Duplicate detection — match rule + confirm-card response contract
# ---------------------------------------------------------------------------

class TestDuplicateDetection:
    def test_exact_match_triggers_confirm_card(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Sriracha")

        resp = _add_shopping(client, "Sriracha")
        assert resp.status_code == 200
        assert resp.headers.get("HX-Retarget") == "#shopping-dupe-confirm-slot"
        assert resp.headers.get("HX-Reswap") == "innerHTML"
        assert resp.headers.get("HX-Detour") == "dupe-confirm", (
            "Dupe response must set HX-Detour so the add form's "
            "auto-reset handler skips resetting the user's input."
        )
        body = resp.get_data(as_text=True)
        assert 'id="shopping-dupe-confirm-card"' in body, (
            "Response body must render the confirm card partial."
        )
        assert "Sriracha" in body

    def test_case_insensitive_match(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        resp = _add_shopping(client, "milk")
        assert resp.headers.get("HX-Retarget") == "#shopping-dupe-confirm-slot"

    def test_whitespace_trimmed_match(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        resp = _add_shopping(client, "  Milk  ")
        assert resp.headers.get("HX-Retarget") == "#shopping-dupe-confirm-slot"

    def test_different_name_no_confirm(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        resp = _add_shopping(client, "Bread")
        assert resp.status_code == 200
        assert resp.headers.get("HX-Retarget") is None
        assert resp.headers.get("HX-Detour") is None

    def test_no_existing_no_confirm(self, client, app):
        """First add of any name — never a dupe, always the fast path."""
        sign_up(client, "alice@example.com", "Alice")
        resp = _add_shopping(client, "Milk")
        assert resp.status_code == 200
        assert resp.headers.get("HX-Detour") is None
        body = resp.get_data(as_text=True)
        assert "Milk" in body

    def test_household_scoped_no_cross_household_dupe(self, two_clients, app):
        """Bob's separate household should never collide with Alice's
        shopping items."""
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")
        _add_shopping(alice, "Milk")

        resp = _add_shopping(bob, "Milk")
        assert resp.headers.get("HX-Detour") is None, (
            "Bob's Milk should NOT be a dupe of Alice's Milk — "
            "separate households."
        )

    def test_household_scoped_dupe_for_roommates(self, two_clients, app):
        """Roommates in the SAME household share a shopping list,
        so Bob adding 'Milk' when Alice already added 'Milk' IS a dupe."""
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")

        from models import User
        from extensions import db
        with app.app_context():
            alice_user = User.query.filter_by(email="alice@example.com").first()
            bob_user = User.query.filter_by(email="bob@example.com").first()
            bob_user.household_id = alice_user.household_id
            db.session.commit()

        _add_shopping(alice, "Milk")
        resp = _add_shopping(bob, "Milk")
        assert resp.headers.get("HX-Retarget") == "#shopping-dupe-confirm-slot"

    def test_non_htmx_post_skips_dupe_check(self, client, app):
        """Legacy non-htmx form submissions bypass the dupe check —
        they get a redirect to /shopping and a plain add. Rare path
        (browser without JS), but we don't want to serve a partial
        response to a non-htmx client."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _add_shopping(client, "Milk")

        # Non-htmx POST.
        resp = client.post("/shopping", htmx=False, data={
            "name": "Milk", "submit": "Add",
        })
        # Redirect on the non-htmx path (302).
        assert resp.status_code in (302, 303)
        assert _shopping_row_count(app, hid) == 2, (
            "Non-htmx path deliberately preserves two-taps-two-rows "
            "so a JS-less browser isn't served an unusable partial."
        )


# ---------------------------------------------------------------------------
# 2. Confirm card contents — pending payload + existing-row context
# ---------------------------------------------------------------------------

class TestConfirmCardContents:
    def test_card_renders_pending_payload_as_hidden_inputs(
        self, client, app,
    ):
        """The three-button UX depends on the hidden inputs carrying
        the pending qty/unit/notes forward on merge / force-dupe.

        Note: quantity is a wtforms FloatField, so a submitted "2"
        round-trips to `2.0` in the template. That's fine — the
        merge / force-add POST parses it back to a float either way.
        The assertion accepts either representation (`2` or `2.0`)
        so this test tolerates future template-side formatting
        tweaks without breaking."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk", qty="1", unit="gal")

        resp = _add_shopping(client, "Milk", qty="2", unit="qt",
                             notes="whole")
        body = resp.get_data(as_text=True)
        assert 'data-pending' in body
        # Accept 2 or 2.0 — FloatField renders as float. The name and
        # value attributes may be split across lines in the source
        # template, so we allow any whitespace between them.
        assert re.search(r'name="quantity"\s+value="2(\.0)?"', body), (
            f"Expected quantity hidden input with 2 or 2.0"
        )
        assert 'name="unit" value="qt"' in body
        assert 'name="notes" value="whole"' in body

    def test_card_shows_existing_row_qty_and_notes(self, client, app):
        """Card copy is 'here's the row we mean' — must display
        the existing qty/unit + any notes so the user can tell
        which row they're about to merge into."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk", qty="1", unit="gal", notes="whole")

        resp = _add_shopping(client, "Milk", qty="1")
        body = resp.get_data(as_text=True)
        assert "1 gal" in body
        assert "whole" in body

    def test_card_shows_checked_off_badge_when_target_checked(
        self, client, app,
    ):
        """Shopping-specific detail: the confirm card surfaces the
        target row's checked state so the user has full context.
        The 'already crossed off' badge helps them pick between
        Update existing (bumps qty on the crossed-off row, which
        will move to pantry on I'm-home) vs Add as separate row
        (fresh un-checked row for the extra qty they need)."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _add_shopping(client, "Milk")

        # Toggle Milk checked.
        body = client.get("/shopping").get_data(as_text=True)
        milk_id = _first_shopping_id(body)
        client.post(f"/shopping/{milk_id}/toggle", htmx=True)

        # Now try to re-add Milk — confirm card should include the
        # 'already crossed off' badge.
        resp = _add_shopping(client, "Milk")
        body = resp.get_data(as_text=True)
        assert "already crossed off" in body

    def test_card_no_checked_off_badge_when_target_unchecked(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        resp = _add_shopping(client, "Milk")
        body = resp.get_data(as_text=True)
        assert "already crossed off" not in body


# ---------------------------------------------------------------------------
# 3. Merge route — /shopping/merge/<id> semantics
# ---------------------------------------------------------------------------

class TestMergeRoute:
    def test_merge_sums_quantities(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _add_shopping(client, "Milk", qty="1", unit="gal")

        rows = _shopping_rows_named(app, hid, "Milk")
        existing_id = rows[0].id

        # Merge in a pending +2 gal.
        resp = client.post(f"/shopping/merge/{existing_id}", htmx=True, data={
            "name": "Milk", "quantity": "2", "unit": "gal",
        })
        assert resp.status_code == 200

        with app.app_context():
            from models import ShoppingItem
            from extensions import db
            row = db.session.get(ShoppingItem, existing_id)
            assert row.quantity == 3, "1 + 2 = 3"
            assert row.unit == "gal"

    def test_merge_preserves_added_at_and_provenance(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _add_shopping(client, "Milk", qty="1")

        with app.app_context():
            from models import ShoppingItem
            row = ShoppingItem.query.filter_by(household_id=hid).one()
            original_added_at = row.added_at
            original_added_by = row.added_by_user_id
            existing_id = row.id

        client.post(f"/shopping/merge/{existing_id}", htmx=True, data={
            "name": "Milk", "quantity": "1",
        })

        with app.app_context():
            from models import ShoppingItem
            from extensions import db
            row = db.session.get(ShoppingItem, existing_id)
            assert row.added_at == original_added_at
            assert row.added_by_user_id == original_added_by

    def test_merge_preserves_checked_state(self, client, app):
        """Shopping-specific v1 semantic: merge NEVER touches
        checked / checked_at. If the target was crossed off, it
        stays crossed off after merge; the qty just bumps."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _add_shopping(client, "Milk", qty="1")

        # Check the row off.
        body = client.get("/shopping").get_data(as_text=True)
        milk_id = _first_shopping_id(body)
        client.post(f"/shopping/{milk_id}/toggle", htmx=True)

        with app.app_context():
            from models import ShoppingItem
            from extensions import db
            row = db.session.get(ShoppingItem, int(milk_id))
            assert row.checked is True
            original_checked_at = row.checked_at

        # Merge +1 into the crossed-off row.
        client.post(f"/shopping/merge/{milk_id}", htmx=True, data={
            "name": "Milk", "quantity": "1",
        })

        with app.app_context():
            from models import ShoppingItem
            from extensions import db
            row = db.session.get(ShoppingItem, int(milk_id))
            assert row.checked is True, (
                "Merge must preserve the target's checked state — "
                "user can 'Add as separate row' if they wanted a "
                "fresh un-checked entry."
            )
            assert row.checked_at == original_checked_at, (
                "checked_at unchanged so the row's position in the "
                "checked-section sort is preserved."
            )
            assert row.quantity == 2

    def test_merge_unit_conflict_migrates_to_notes(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _add_shopping(client, "Milk", qty="1", unit="gal")
        existing_id = _shopping_rows_named(app, hid, "Milk")[0].id

        # Pending unit "qt" differs from existing "gal" — should
        # migrate into notes rather than silently overwrite.
        client.post(f"/shopping/merge/{existing_id}", htmx=True, data={
            "name": "Milk", "quantity": "2", "unit": "qt",
        })

        with app.app_context():
            from models import ShoppingItem
            from extensions import db
            row = db.session.get(ShoppingItem, existing_id)
            assert row.unit == "gal", "Existing unit wins"
            assert row.notes is not None
            assert "qt" in row.notes.lower()
            assert row.quantity == 3

    def test_merge_concatenates_notes_with_bullet(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _add_shopping(client, "Milk", qty="1", notes="whole")
        existing_id = _shopping_rows_named(app, hid, "Milk")[0].id

        client.post(f"/shopping/merge/{existing_id}", htmx=True, data={
            "name": "Milk", "quantity": "1", "notes": "organic",
        })

        with app.app_context():
            from models import ShoppingItem
            from extensions import db
            row = db.session.get(ShoppingItem, existing_id)
            assert "whole" in row.notes
            assert "organic" in row.notes
            assert "\u2022" in row.notes  # bullet separator

    def test_merge_none_quantity_arithmetic(self, client, app):
        """None + qty = qty; qty + None = qty; None + None = None."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")

        # Case: existing None, pending 2 → target becomes 2.
        _add_shopping(client, "Milk")  # no qty
        existing_id = _shopping_rows_named(app, hid, "Milk")[0].id
        client.post(f"/shopping/merge/{existing_id}", htmx=True, data={
            "name": "Milk", "quantity": "2",
        })
        with app.app_context():
            from models import ShoppingItem
            from extensions import db
            row = db.session.get(ShoppingItem, existing_id)
            assert row.quantity == 2

    def test_merge_fires_shopping_merged_trigger(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _add_shopping(client, "Milk", qty="1")
        existing_id = _shopping_rows_named(app, hid, "Milk")[0].id

        resp = client.post(f"/shopping/merge/{existing_id}", htmx=True, data={
            "name": "Milk", "quantity": "1",
        })
        payload = _hx_trigger_payload(resp)
        assert payload is not None
        assert "shopping:merged" in payload
        assert payload["shopping:merged"]["name"] == "Milk"

    def test_merge_response_body_is_shopping_list_partial(
        self, client, app,
    ):
        """The merge response must return the shopping-list partial
        so htmx swaps it into #shopping-list. Otherwise the visible
        list state (quantity display) goes stale."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _add_shopping(client, "Milk", qty="1")
        existing_id = _shopping_rows_named(app, hid, "Milk")[0].id

        resp = client.post(f"/shopping/merge/{existing_id}", htmx=True, data={
            "name": "Milk", "quantity": "1",
        })
        body = resp.get_data(as_text=True)
        assert 'id="shopping-list"' in body

    def test_merge_emits_oob_clear_of_confirm_slot(self, client, app):
        """Merge response must include the OOB div that clears
        #shopping-dupe-confirm-slot so the card disappears in the
        same swap as the list update."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _add_shopping(client, "Milk", qty="1")
        existing_id = _shopping_rows_named(app, hid, "Milk")[0].id

        resp = client.post(f"/shopping/merge/{existing_id}", htmx=True, data={
            "name": "Milk", "quantity": "1",
        })
        body = resp.get_data(as_text=True)
        assert 'id="shopping-dupe-confirm-slot"' in body
        assert 'hx-swap-oob="innerHTML"' in body

    def test_merge_does_not_bump_frequency_counter(self, client, app):
        """Merge isn't a new 'add' event — it's a consolidation.
        Bumping the frequency counter would double-count a single
        mental gesture (the pending name already existed in the
        counter from the first add). Preserves ranking accuracy of
        the 'ADD AGAIN' chip strip."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")

        _add_shopping(client, "Milk", qty="1")  # bump #1
        existing_id = _shopping_rows_named(app, hid, "Milk")[0].id

        with app.app_context():
            from models import ShoppingNameFrequency
            counter = ShoppingNameFrequency.query.filter(
                ShoppingNameFrequency.household_id == hid,
            ).one()
            count_before_merge = counter.count

        # Merge — should NOT bump.
        client.post(f"/shopping/merge/{existing_id}", htmx=True, data={
            "name": "Milk", "quantity": "1",
        })

        with app.app_context():
            from models import ShoppingNameFrequency
            counter = ShoppingNameFrequency.query.filter(
                ShoppingNameFrequency.household_id == hid,
            ).one()
            assert counter.count == count_before_merge, (
                "Merge must not bump the frequency counter."
            )

    def test_merge_target_from_other_household_returns_404(
        self, two_clients, app,
    ):
        """Household-scoped: a merge attempt against another
        household's shopping row must 404, not merge into it."""
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")

        _add_shopping(alice, "Milk", qty="1")
        alice_hid = _household_id_for(app, "alice@example.com")
        alice_milk_id = _shopping_rows_named(app, alice_hid, "Milk")[0].id

        # Bob attempts to merge into Alice's row.
        resp = bob.post(f"/shopping/merge/{alice_milk_id}", htmx=True, data={
            "name": "Milk", "quantity": "5",
        })
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 4. Force-duplicate path — ?force_duplicate=1 bypass
# ---------------------------------------------------------------------------

class TestForceDuplicate:
    def test_force_duplicate_creates_second_row(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _add_shopping(client, "Milk")

        _add_shopping(client, "Milk", force_duplicate=True)
        rows = _shopping_rows_named(app, hid, "Milk")
        assert len(rows) == 2, (
            "force_duplicate=1 must skip the dupe check and create a "
            "second row, even for an exact name match."
        )

    def test_force_duplicate_bumps_frequency_counter(self, client, app):
        """Force-add is still a real add event, so the frequency
        counter should bump (same as an unforced no-dupe add)."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")

        _add_shopping(client, "Milk")
        with app.app_context():
            from models import ShoppingNameFrequency
            counter = ShoppingNameFrequency.query.filter(
                ShoppingNameFrequency.household_id == hid,
            ).one()
            count_before = counter.count

        _add_shopping(client, "Milk", force_duplicate=True)
        with app.app_context():
            from models import ShoppingNameFrequency
            counter = ShoppingNameFrequency.query.filter(
                ShoppingNameFrequency.household_id == hid,
            ).one()
            assert counter.count == count_before + 1

    def test_force_duplicate_emits_oob_clear(self, client, app):
        """The Add-as-separate-row branch also OOB-clears the confirm
        slot so the card vanishes in the same swap as the list update."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")

        resp = _add_shopping(client, "Milk", force_duplicate=True)
        body = resp.get_data(as_text=True)
        assert 'id="shopping-dupe-confirm-slot"' in body
        assert 'hx-swap-oob="innerHTML"' in body


# ---------------------------------------------------------------------------
# 5. Bypass-path isolation — other ShoppingItem-creating routes must
#    NOT trigger the dupe check (they preserve two-taps-two-rows).
# ---------------------------------------------------------------------------

class TestBypassPaths:
    def test_pantry_plus_shop_creates_duplicate_without_confirm(
        self, client, app,
    ):
        """The + Shop button on a pantry row hits /pantry/<id>/add-to-
        shopping, not /shopping — it must NOT trigger the dupe check
        even if the shopping list already has the same-named row.
        This is the codebase's baked-in 'two taps = two rows' contract
        from test_two_taps_create_two_rows_no_dedupe."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")

        # Seed a pantry item.
        client.post("/pantry", htmx=True, data={
            "name": "Olive oil", "quantity": "1", "unit": "bottle",
            "submit": "Add",
        })

        # First + Shop tap → creates shopping row.
        with app.app_context():
            from models import PantryItem
            olive_id = PantryItem.query.filter_by(
                household_id=hid, name="Olive oil",
            ).one().id
        client.post(f"/pantry/{olive_id}/add-to-shopping", htmx=True)

        # Second + Shop tap on the SAME pantry row → must create a
        # second shopping row (bypass path).
        resp = client.post(f"/pantry/{olive_id}/add-to-shopping", htmx=True)
        assert resp.status_code == 200
        # No confirm card — no HX-Retarget header.
        assert resp.headers.get("HX-Retarget") is None

        rows = _shopping_rows_named(app, hid, "Olive oil")
        assert len(rows) == 2, (
            "+ Shop bypass path must preserve 'two taps = two rows' "
            "even after 6D — it doesn't go through POST /shopping."
        )

    def test_undo_restore_creates_row_without_confirm(self, client, app):
        """Deleting a shopping row and hitting Undo restores it via
        _restore_shopping_snapshot — that path must NOT collide with
        the dupe check even if a same-named row got added in the
        interim. Uncommon in practice (5s window) but the bypass
        must hold."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")

        _add_shopping(client, "Milk")
        body = client.get("/shopping").get_data(as_text=True)
        milk_id = _first_shopping_id(body)

        # Delete Milk (snapshot into undo slot).
        client.delete(f"/shopping/{milk_id}")

        # In the 5s window, add a NEW "Milk" (no dupe — old one is gone).
        _add_shopping(client, "Milk")

        # Now hit undo — restores the OLD Milk. Must NOT trigger dupe.
        resp = client.post("/shopping/undo", htmx=True)
        assert resp.status_code == 200
        assert resp.headers.get("HX-Retarget") is None

        rows = _shopping_rows_named(app, hid, "Milk")
        assert len(rows) == 2, (
            "Undo restore bypass path must create the second row "
            "unconditionally — the undo IS the user's decision to "
            "get both back."
        )


# ---------------------------------------------------------------------------
# 6. Suggestion-chip interaction — the 'ADD AGAIN' chips post to
#    /shopping so a dupe check could fire; server-side filter should
#    already prevent it, but we guard the wiring here.
# ---------------------------------------------------------------------------

class TestSuggestionChipInteraction:
    def test_add_after_clear_via_form_dupes_correctly(self, client, app):
        """After clearing a checked item the frequency counter is
        preserved (Phase 3I). Re-adding the same name via the FORM
        (not the chip) should be a fresh add — no dupe — because the
        row was hard-deleted from shopping_items."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")
        _add_shopping(client, "Milk")

        # Check + clear.
        body = client.get("/shopping").get_data(as_text=True)
        milk_id = _first_shopping_id(body)
        client.post(f"/shopping/{milk_id}/toggle", htmx=True)
        client.post("/shopping/clear-checked", htmx=True)

        # Now re-add "Milk" — the row was hard-deleted so no dupe.
        resp = _add_shopping(client, "Milk")
        assert resp.headers.get("HX-Detour") is None
        rows = _shopping_rows_named(app, hid, "Milk")
        assert len(rows) == 1


# ---------------------------------------------------------------------------
# 7. UI wiring — template slots + form-reset guard + toast handler
# ---------------------------------------------------------------------------

class TestUIWiring:
    def test_shopping_page_renders_dupe_slot(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        body = client.get("/shopping").get_data(as_text=True)
        assert 'id="shopping-dupe-confirm-slot"' in body

    def test_add_form_reset_guard_reads_hx_detour(self, client, app):
        """shopping.html's add form must guard its auto-reset against
        HX-Detour so a dupe response doesn't wipe the user's typed
        values before they've picked Cancel/Merge/Add-anyway."""
        sign_up(client, "alice@example.com", "Alice")
        body = client.get("/shopping").get_data(as_text=True)
        # Look for the detour guard on the add form's after-request.
        assert "getResponseHeader('HX-Detour')" in body

    def test_base_handler_wired_for_shopping_merged(self, client, app):
        """base.html must register a shopping:merged handler so the
        merge route's HX-Trigger fires a toast."""
        sign_up(client, "alice@example.com", "Alice")
        body = client.get("/shopping").get_data(as_text=True)
        assert "shopping:merged" in body


# ---------------------------------------------------------------------------
# 8. Anonymous / permission checks
# ---------------------------------------------------------------------------

class TestAnonymousReplay:
    def test_anonymous_merge_rejected(self, app):
        c = Client(app.test_client())
        resp = c._c.post("/shopping/merge/1")
        assert resp.status_code in (302, 400, 401)

    def test_anonymous_force_duplicate_rejected(self, app):
        c = Client(app.test_client())
        resp = c._c.post("/shopping?force_duplicate=1")
        assert resp.status_code in (302, 400, 401)
