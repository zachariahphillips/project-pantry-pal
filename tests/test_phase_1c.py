"""
Phase 1C regression suite.

Mirrors the 38-check end-to-end smoke test that gated the Phase 1C
commit (see PLAN.md for the full ledger). Where the original test
hit a live server with `urllib`, this version uses Flask's test
client via `Client` in `conftest.py` — same code paths, no port.

Test groupings (intentionally many small tests rather than one
mega-test, so a future regression points at the exact failure):

- TestShoppingPageBasics    — bare /shopping renders, tab bar, toast slot
- TestShoppingCRUD          — add, edit, delete, validation, search
- TestCheckOffBehavior      — toggle, reorder, strikethrough, clear-checked
- TestPantryToShoppingLink  — the +Shop button cross-link semantics
- TestUserIsolation         — alice can't touch bob's items, on either list
- TestAnonymousAccess       — tab bar / toast hidden on login & signup
"""
from __future__ import annotations

import re

import pytest

from tests.conftest import Client, id_for, sign_up


# ---------------------------------------------------------------------------
# Shopping page basics
# ---------------------------------------------------------------------------

class TestShoppingPageBasics:
    def test_signup_lands_on_pantry_with_tab_bar(self, client: Client):
        body = sign_up(client, "alice@example.com", "Alice")
        assert 'aria-label="Main navigation"' in body
        assert ">Pantry<" in body and ">Shopping<" in body
        assert 'href="/pantry"' in body
        assert 'aria-current="page"' in body
        assert 'id="toast"' in body

    def test_shopping_renders_empty_state(self, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        resp = client.get("/shopping")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Shopping list" in body
        assert "Nothing on your shopping list" in body

    def test_shopping_tab_is_active_on_shopping_page(self, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        body = client.get("/shopping").get_data(as_text=True)
        assert re.search(r'href="/shopping"[^>]*aria-current="page"', body)

    def test_pantry_tab_stays_active_after_visiting_shopping(self, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        client.get("/shopping")
        body = client.get("/pantry").get_data(as_text=True)
        assert re.search(r'href="/pantry"[^>]*aria-current="page"', body)


# ---------------------------------------------------------------------------
# Shopping CRUD
# ---------------------------------------------------------------------------

class TestShoppingCRUD:
    def _add(self, client: Client, **fields):
        defaults = {"quantity": "", "unit": "", "notes": "", "submit": "Add"}
        defaults.update(fields)
        return client.post("/shopping", data=defaults, htmx=True)

    def test_htmx_add_returns_list_partial(self, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        resp = self._add(client, name="Tortillas", quantity="2",
                         unit="bags", notes="corn")
        body = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert 'id="shopping-list"' in body
        assert "Tortillas" in body
        assert "2 bags" in body
        assert "corn" in body

    def test_items_render_newest_first(self, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        self._add(client, name="Tortillas", quantity="2", unit="bags")
        self._add(client, name="Milk", quantity="1", unit="gal")
        body = client.get("/shopping").get_data(as_text=True)
        ids = re.findall(r'id="shopping-item-(\d+)"', body)
        milk = id_for(body, "Milk", "shopping-item")
        tort = id_for(body, "Tortillas", "shopping-item")
        assert ids == [milk, tort], "expected newest (Milk) on top"

    def test_blank_name_returns_422_with_retarget(self, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        resp = self._add(client, name="")
        assert resp.status_code == 422
        assert resp.headers.get("HX-Retarget") == "#shopping-add-form-errors"

    def test_edit_form_round_trip(self, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        self._add(client, name="Tortillas", quantity="2", unit="bags",
                  notes="corn")
        body = client.get("/shopping").get_data(as_text=True)
        item_id = id_for(body, "Tortillas", "shopping-item")

        edit_html = client.get(f"/shopping/{item_id}/edit", htmx=True).get_data(as_text=True)
        assert f'hx-put="/shopping/{item_id}"' in edit_html
        assert 'value="Tortillas"' in edit_html

        resp = client.put(f"/shopping/{item_id}", data={
            "name": "Tortillas", "quantity": "3", "unit": "bags",
            "notes": "flour", "submit": "Save",
        })
        body = resp.get_data(as_text=True)
        assert resp.status_code == 200
        assert "3 bags" in body and "flour" in body
        # PUT response is the static row, not another edit form.
        assert "hx-put" not in body

    def test_delete_renders_empty_state_when_last_row_removed(self, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        self._add(client, name="Tortillas")
        body = client.get("/shopping").get_data(as_text=True)
        item_id = id_for(body, "Tortillas", "shopping-item")
        body = client.delete(f"/shopping/{item_id}").get_data(as_text=True)
        assert "Nothing on your shopping list" in body

    def test_search_filters_list(self, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        self._add(client, name="Olive oil")
        self._add(client, name="Pasta")
        body = client.get("/shopping?q=olive", htmx=True).get_data(as_text=True)
        assert "Olive oil" in body and "Pasta" not in body

    def test_search_with_no_matches_shows_no_matches_state(self, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        self._add(client, name="Olive oil")
        body = client.get("/shopping?q=zzz_nope", htmx=True).get_data(as_text=True)
        assert "No matches for" in body


# ---------------------------------------------------------------------------
# Check-off (toggle) behavior
# ---------------------------------------------------------------------------

class TestCheckOffBehavior:
    @pytest.fixture
    def setup(self, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        client.post("/shopping", data={"name": "Tortillas", "submit": "Add"},
                    htmx=True)
        client.post("/shopping", data={"name": "Milk", "submit": "Add"},
                    htmx=True)
        body = client.get("/shopping").get_data(as_text=True)
        return {
            "client": client,
            "milk_id": id_for(body, "Milk", "shopping-item"),
            "tort_id": id_for(body, "Tortillas", "shopping-item"),
        }

    def test_toggling_moves_item_to_bottom_and_strikes_through(self, setup):
        c, milk, tort = setup["client"], setup["milk_id"], setup["tort_id"]
        body = c.post(f"/shopping/{milk}/toggle", htmx=True).get_data(as_text=True)
        ids_after = re.findall(r'id="shopping-item-(\d+)"', body)
        assert ids_after == [tort, milk], "checked item should sink"
        milk_block = re.search(
            rf'id="shopping-item-{milk}".*?(?=id="shopping-item-|$)',
            body, re.DOTALL).group(0)
        assert "line-through" in milk_block
        assert "checked" in milk_block

    def test_summary_bar_appears_with_clear_button(self, setup):
        c, milk = setup["client"], setup["milk_id"]
        body = c.post(f"/shopping/{milk}/toggle", htmx=True).get_data(as_text=True)
        assert "1 checked off" in body
        assert "Clear checked" in body

    def test_toggling_back_off_removes_strikethrough_and_summary(self, setup):
        c, milk = setup["client"], setup["milk_id"]
        c.post(f"/shopping/{milk}/toggle", htmx=True)
        body = c.post(f"/shopping/{milk}/toggle", htmx=True).get_data(as_text=True)
        milk_block = re.search(
            rf'id="shopping-item-{milk}".*?(?=id="shopping-item-|$)',
            body, re.DOTALL).group(0)
        assert "line-through" not in milk_block
        # Summary bar disappears when no items are checked.
        assert "Clear checked" not in body

    def test_clear_checked_only_removes_checked_items(self, setup):
        c, milk, tort = setup["client"], setup["milk_id"], setup["tort_id"]
        c.post(f"/shopping/{milk}/toggle", htmx=True)
        body = c.post("/shopping/clear-checked", htmx=True).get_data(as_text=True)
        assert "Tortillas" in body
        assert "Milk" not in body
        assert "Clear checked" not in body  # summary bar gone too

    def test_clear_checked_fires_toast_with_count(self, setup):
        """Phase 3F: clear-checked now fires HX-Trigger so the toast
        listener can confirm the action (pre-3F it silently re-rendered,
        which was ambiguous after the hx-confirm modal closed)."""
        c, milk, tort = setup["client"], setup["milk_id"], setup["tort_id"]
        c.post(f"/shopping/{milk}/toggle", htmx=True)
        c.post(f"/shopping/{tort}/toggle", htmx=True)
        resp = c.post("/shopping/clear-checked", htmx=True)
        assert resp.status_code == 200
        trigger = resp.headers.get("HX-Trigger", "")
        assert "shopping:cleared-checked" in trigger
        assert '"count": 2' in trigger

    def test_clear_checked_with_no_checked_items_does_not_fire_toast(
            self, setup):
        """Calling the route with nothing checked should not fire a
        spurious 'Cleared 0 items' toast. The list is unchanged."""
        c = setup["client"]
        resp = c.post("/shopping/clear-checked", htmx=True)
        assert resp.status_code == 200
        assert "HX-Trigger" not in resp.headers


# ---------------------------------------------------------------------------
# Phase 3F: "I'm home" — move checked shopping items into the pantry
# ---------------------------------------------------------------------------

class TestImHome:
    """The killer-feature flow. After a grocery run, the user taps
    "I'm home" on /shopping and every checked item becomes a new pantry
    row (always a new row — no dedupe; matches the codebase's
    "two taps = two rows" philosophy from `pantry_item_to_shopping`)."""

    @pytest.fixture
    def setup(self, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        # Two items, one with quantity/unit/notes so we can verify
        # those round-trip through the move.
        client.post("/shopping", data={
            "name": "Milk", "quantity": "1", "unit": "gal",
            "notes": "whole", "submit": "Add",
        }, htmx=True)
        client.post("/shopping", data={
            "name": "Tortillas", "submit": "Add",
        }, htmx=True)
        body = client.get("/shopping").get_data(as_text=True)
        return {
            "client": client,
            "milk_id": id_for(body, "Milk", "shopping-item"),
            "tort_id": id_for(body, "Tortillas", "shopping-item"),
        }

    def _check(self, c: Client, item_id: str) -> None:
        c.post(f"/shopping/{item_id}/toggle", htmx=True)

    def test_moves_checked_items_to_pantry(self, setup):
        c, milk, tort = setup["client"], setup["milk_id"], setup["tort_id"]
        self._check(c, milk)
        self._check(c, tort)
        # Move
        body = c.post(
            "/shopping/move-checked-to-pantry", htmx=True,
        ).get_data(as_text=True)
        # Shopping list is now empty
        assert "Milk" not in body
        assert "Tortillas" not in body
        assert "Nothing on your shopping list" in body
        # Pantry now has both items
        pantry = c.get("/pantry").get_data(as_text=True)
        assert "Milk" in pantry
        assert "Tortillas" in pantry

    def test_leaves_unchecked_items_in_shopping(self, setup):
        c, milk, tort = setup["client"], setup["milk_id"], setup["tort_id"]
        self._check(c, milk)
        # tort stays unchecked
        body = c.post(
            "/shopping/move-checked-to-pantry", htmx=True,
        ).get_data(as_text=True)
        assert "Tortillas" in body, "unchecked items must remain in shopping"
        assert "Milk" not in body, "the checked item should have moved out"

    def test_preserves_quantity_unit_notes_through_move(self, setup, app):
        """Milk was added with quantity=1, unit=gal, notes=whole. After
        the move those should be preserved on the new pantry row."""
        c, milk = setup["client"], setup["milk_id"]
        self._check(c, milk)
        c.post("/shopping/move-checked-to-pantry", htmx=True)

        with app.app_context():
            from models import PantryItem
            row = PantryItem.query.filter_by(name="Milk").one()
            assert row.quantity == 1
            assert row.unit == "gal"
            assert row.notes == "whole"

    def test_provenance_is_the_im_home_tapper_not_original_adder(
            self, setup, app):
        """Same pattern as `pantry_item_to_shopping`: the new row's
        added_by_user_id is whoever tapped "I'm home" (i.e. the person
        who actually brought the items home), NOT necessarily the
        roommate who originally put the item on the shopping list.

        In this single-user setup alice is both the original adder and
        the tapper, so we just verify the row has SOMEONE as added_by
        and that someone is alice (id=1)."""
        c, milk = setup["client"], setup["milk_id"]
        self._check(c, milk)
        c.post("/shopping/move-checked-to-pantry", htmx=True)

        with app.app_context():
            from models import PantryItem, User
            row = PantryItem.query.filter_by(name="Milk").one()
            alice = User.query.filter_by(email="alice@example.com").one()
            assert row.added_by_user_id == alice.id

    def test_two_moves_of_same_name_create_two_pantry_rows(self, setup, app):
        """Mirrors `test_two_taps_create_two_rows_no_dedupe` from the
        +Shop direction. The "I'm home" flow ALWAYS adds a new pantry
        row, even if the same item is already there. A future PR that
        adds silent merge logic will fail this test on purpose."""
        c, milk = setup["client"], setup["milk_id"]
        # First trip: check + move
        self._check(c, milk)
        c.post("/shopping/move-checked-to-pantry", htmx=True)
        # Buy more milk: add it again to shopping, check, move
        c.post("/shopping", data={
            "name": "Milk", "quantity": "1", "unit": "gal", "submit": "Add",
        }, htmx=True)
        body = c.get("/shopping").get_data(as_text=True)
        milk2 = id_for(body, "Milk", "shopping-item")
        self._check(c, milk2)
        c.post("/shopping/move-checked-to-pantry", htmx=True)

        with app.app_context():
            from models import PantryItem
            milk_rows = PantryItem.query.filter_by(name="Milk").all()
            assert len(milk_rows) == 2, (
                "no dedupe on 'I'm home' — two grocery trips for milk "
                "should yield two pantry rows"
            )

    def test_no_checked_items_is_safe_noop_with_no_toast(self, setup):
        """The action bar is gated behind {% if checked_count > 0 %},
        so the user shouldn't see the button when nothing's checked.
        Defensive: a curl POST should still return 200, no toast,
        nothing moves."""
        c = setup["client"]
        resp = c.post("/shopping/move-checked-to-pantry", htmx=True)
        assert resp.status_code == 200
        assert "HX-Trigger" not in resp.headers
        body = resp.get_data(as_text=True)
        # Both items still on the shopping list
        assert "Milk" in body
        assert "Tortillas" in body

    def test_fires_hx_trigger_toast_with_count(self, setup):
        c, milk, tort = setup["client"], setup["milk_id"], setup["tort_id"]
        self._check(c, milk)
        self._check(c, tort)
        resp = c.post("/shopping/move-checked-to-pantry", htmx=True)
        assert resp.status_code == 200
        trigger = resp.headers.get("HX-Trigger", "")
        assert "shopping:moved-to-pantry" in trigger
        assert '"count": 2' in trigger

    def test_im_home_button_appears_only_when_something_checked(self, setup):
        """No checked items → action bar hidden (Clear + I'm home both
        gone). After checking one item → both buttons appear. We assert
        on the route URLs the buttons POST to (rather than the visible
        text) because base.html has a JS comment containing the literal
        string "I'm home" that lands in every page body — making text
        matching brittle."""
        c, milk = setup["client"], setup["milk_id"]
        move_url = "/shopping/move-checked-to-pantry"
        clear_url = "/shopping/clear-checked"
        # Nothing checked yet — neither button rendered.
        body = c.get("/shopping").get_data(as_text=True)
        assert move_url not in body
        assert clear_url not in body
        # Check one item — bar appears with both buttons.
        self._check(c, milk)
        body = c.get("/shopping").get_data(as_text=True)
        assert move_url in body
        assert clear_url in body

    def test_other_households_items_are_invisible(self, two_clients):
        """Alice and Bob are in DIFFERENT households (each signup
        creates a household-of-one). Alice tapping "I'm home" must
        only see + move HER household's checked items — even though
        the filter happens server-side, this catches any future
        regression that swaps the household filter for a global query.

        Item names here are kept apostrophe-free because Jinja
        HTML-escapes apostrophes (e.g. "Bob's beer" -> "Bob&#39;s beer")
        and the substring assertions wouldn't match the escaped form."""
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")
        # Bob checks an item in HIS household
        bob.post("/shopping", data={"name": "Beer", "submit": "Add"},
                 htmx=True)
        bob_shop = bob.get("/shopping").get_data(as_text=True)
        bob_beer = id_for(bob_shop, "Beer", "shopping-item")
        assert bob_beer is not None, "setup: id_for couldn't locate Bob's row"
        bob.post(f"/shopping/{bob_beer}/toggle", htmx=True)
        # Alice taps "I'm home" in HER household (nothing checked there)
        resp = alice.post("/shopping/move-checked-to-pantry", htmx=True)
        assert resp.status_code == 200
        assert "HX-Trigger" not in resp.headers
        # Bob's beer is still in Bob's shopping list, still checked
        bob_shop_after = bob.get("/shopping").get_data(as_text=True)
        assert "Beer" in bob_shop_after
        # And NOT in alice's pantry
        alice_pantry = alice.get("/pantry").get_data(as_text=True)
        assert "Beer" not in alice_pantry


# ---------------------------------------------------------------------------
# Pantry -> Shopping cross-link (+Shop button)
# ---------------------------------------------------------------------------

class TestPantryToShoppingLink:
    @pytest.fixture
    def setup(self, client: Client):
        sign_up(client, "alice@example.com", "Alice")
        client.post("/pantry", data={
            "name": "Olive oil", "quantity": "1", "unit": "bottle",
            "notes": "EVOO", "submit": "Add",
        }, htmx=True)
        body = client.get("/pantry").get_data(as_text=True)
        return {
            "client": client,
            "olive_id": id_for(body, "Olive oil", "pantry-item"),
            "pantry_html": body,
        }

    def test_plus_shop_button_present_with_correct_hx_post(self, setup):
        body, olive = setup["pantry_html"], setup["olive_id"]
        assert "+ Shop" in body
        assert f'hx-post="/pantry/{olive}/add-to-shopping"' in body

    def test_plus_shop_returns_empty_body_with_hx_trigger(self, setup):
        c, olive = setup["client"], setup["olive_id"]
        resp = c.post(f"/pantry/{olive}/add-to-shopping", htmx=True)
        assert resp.status_code == 200
        assert resp.get_data(as_text=True) == ""
        assert resp.headers.get("HX-Trigger") == "shopping:added"

    def test_pantry_row_survives_plus_shop_unchanged(self, setup):
        c, olive = setup["client"], setup["olive_id"]
        c.post(f"/pantry/{olive}/add-to-shopping", htmx=True)
        body = c.get("/pantry").get_data(as_text=True)
        assert "Olive oil" in body
        assert "EVOO" in body  # pantry notes still there

    def test_shopping_gets_item_without_pantry_notes(self, setup):
        c, olive = setup["client"], setup["olive_id"]
        c.post(f"/pantry/{olive}/add-to-shopping", htmx=True)
        body = c.get("/shopping").get_data(as_text=True)
        assert "Olive oil" in body
        assert "1 bottle" in body
        # Notes are pantry-context; deliberately NOT copied.
        block = re.search(
            r'id="shopping-item-\d+".*?(?=id="shopping-item-|'
            r'<div class="rounded-2xl border border-dashed|$)',
            body, re.DOTALL).group(0)
        assert "EVOO" not in block

    def test_two_taps_create_two_rows_no_dedupe(self, setup):
        """Deliberate behavior: two taps = two rows. A future PR that
        silently de-dupes will fail this test on purpose."""
        c, olive = setup["client"], setup["olive_id"]
        c.post(f"/pantry/{olive}/add-to-shopping", htmx=True)
        c.post(f"/pantry/{olive}/add-to-shopping", htmx=True)
        body = c.get("/shopping").get_data(as_text=True)
        row_count = len(re.findall(r'id="shopping-item-(\d+)"', body))
        assert row_count == 2


# ---------------------------------------------------------------------------
# User isolation
# ---------------------------------------------------------------------------

class TestUserIsolation:
    @pytest.fixture
    def alice_and_bob(self, two_clients):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")
        # Alice plants a pantry + shopping row
        alice.post("/pantry", data={
            "name": "Olive oil", "quantity": "1", "unit": "bottle",
            "submit": "Add",
        }, htmx=True)
        alice.post("/shopping", data={
            "name": "Tortillas", "submit": "Add",
        }, htmx=True)
        a_pantry = alice.get("/pantry").get_data(as_text=True)
        a_shop = alice.get("/shopping").get_data(as_text=True)
        return {
            "alice": alice, "bob": bob,
            "alice_pantry_id": id_for(a_pantry, "Olive oil", "pantry-item"),
            "alice_shop_id": id_for(a_shop, "Tortillas", "shopping-item"),
        }

    def test_bobs_pantry_and_shopping_are_empty(self, alice_and_bob):
        bob = alice_and_bob["bob"]
        pantry = bob.get("/pantry").get_data(as_text=True)
        shop = bob.get("/shopping").get_data(as_text=True)
        assert "Your pantry is empty" in pantry
        assert "Olive oil" not in pantry
        assert "Nothing on your shopping list" in shop
        assert "Tortillas" not in shop

    def test_bob_cannot_read_alices_shopping_edit_form(self, alice_and_bob):
        bob, aid = alice_and_bob["bob"], alice_and_bob["alice_shop_id"]
        resp = bob.get(f"/shopping/{aid}/edit", htmx=True)
        assert resp.status_code == 404

    def test_bob_cannot_toggle_alices_shopping(self, alice_and_bob):
        bob, aid = alice_and_bob["bob"], alice_and_bob["alice_shop_id"]
        resp = bob.post(f"/shopping/{aid}/toggle", htmx=True)
        assert resp.status_code == 404

    def test_bob_cannot_delete_alices_shopping(self, alice_and_bob):
        bob, aid = alice_and_bob["bob"], alice_and_bob["alice_shop_id"]
        resp = bob.delete(f"/shopping/{aid}")
        assert resp.status_code == 404

    def test_bob_cannot_plus_shop_alices_pantry_item(self, alice_and_bob):
        bob, pid = alice_and_bob["bob"], alice_and_bob["alice_pantry_id"]
        resp = bob.post(f"/pantry/{pid}/add-to-shopping", htmx=True)
        assert resp.status_code == 404

    def test_alice_survives_bobs_probing(self, alice_and_bob):
        alice = alice_and_bob["alice"]
        # Bob does the worst things he can. (Resets are necessary because
        # pytest fixtures share state across asserts within a test only.)
        bob = alice_and_bob["bob"]
        bob.get(f"/shopping/{alice_and_bob['alice_shop_id']}/edit", htmx=True)
        bob.post(f"/shopping/{alice_and_bob['alice_shop_id']}/toggle", htmx=True)
        bob.delete(f"/shopping/{alice_and_bob['alice_shop_id']}")
        bob.post(f"/pantry/{alice_and_bob['alice_pantry_id']}/add-to-shopping",
                 htmx=True)

        assert "Olive oil" in alice.get("/pantry").get_data(as_text=True)
        assert "Tortillas" in alice.get("/shopping").get_data(as_text=True)


# ---------------------------------------------------------------------------
# Anonymous access — make sure the tab bar / toast don't leak before login
# ---------------------------------------------------------------------------

class TestAnonymousAccess:
    def test_login_page_hides_tab_bar_and_toast(self, client: Client):
        body = client.get("/login").get_data(as_text=True)
        assert "Main navigation" not in body
        assert 'id="toast"' not in body

    def test_signup_page_hides_tab_bar_and_toast(self, client: Client):
        body = client.get("/signup").get_data(as_text=True)
        assert "Main navigation" not in body
        assert 'id="toast"' not in body

    def test_pantry_redirects_to_login_when_anonymous(self, client: Client):
        resp = client.get("/pantry", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_shopping_redirects_to_login_when_anonymous(self, client: Client):
        resp = client.get("/shopping", follow_redirects=False)
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]
