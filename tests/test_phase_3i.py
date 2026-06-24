"""
Phase 3I regression suite — "Add again" smart-recall chips.

Chunk D of Theme 3 (shopping UX polish) surfaces a chip strip at
the top of /shopping with the 5 most-frequently-added shopping item
names for the household. Tapping a chip instantly creates a name-only
shopping row.

Architectural discovery from the implementation: shopping_items rows
are hard-deleted on cleanup (Clear checked, "I'm home", explicit
Delete), so the table carries zero historical signal. We track adds
in a separate append-only ShoppingNameFrequency counter, bumped from
every ShoppingItem-creating route. These tests guard:

  1. Bump behavior — counter is updated correctly on each of the
     four add paths (shopping_add, pantry→shopping cross-link, and
     both meal-plan-need cross-links). Case-folding works; display
     name follows the most-recent casing.
  2. Aggregation — top-N ranking, tie-breaking, min-distinct
     suppression, current-list exclusion, household scoping.
  3. UI — chip strip renders when suggestions exist, hidden when
     they don't, and chip tap end-to-end creates the right row.
"""
from __future__ import annotations

import json
import re
from unittest.mock import patch

from tests.conftest import Client, sign_up


# ---------------------------------------------------------------------------
# Helpers — kept local to avoid coupling other phase suites to 3I shapes
# ---------------------------------------------------------------------------

def _add_shopping(c: Client, name: str, qty: str = "", unit: str = "",
                  notes: str = ""):
    """POST a shopping item via the same form path the browser uses.
    Returns the response. Helpful when a test cares about the response
    body (e.g. asserting the re-rendered list contains a chip)."""
    return c.post("/shopping", htmx=True, data={
        "name": name, "quantity": qty, "unit": unit, "notes": notes,
        "submit": "Add",
    })


def _freq_count(app, household_id: int, name: str) -> int:
    """Read the ShoppingNameFrequency counter for a (household, name)
    pair directly out of the DB. Tests assert on this rather than
    derived chip ordering when the chip ordering itself isn't the SUT."""
    with app.app_context():
        from app import db
        from models import ShoppingNameFrequency

        row = ShoppingNameFrequency.query.filter_by(
            household_id=household_id,
            name_lower=name.strip().lower(),
        ).first()
        return row.count if row else 0


def _freq_display(app, household_id: int, name: str) -> str | None:
    with app.app_context():
        from app import db
        from models import ShoppingNameFrequency

        row = ShoppingNameFrequency.query.filter_by(
            household_id=household_id,
            name_lower=name.strip().lower(),
        ).first()
        return row.display_name if row else None


def _household_id_for(app, email: str) -> int:
    with app.app_context():
        from models import User
        u = User.query.filter_by(email=email).first()
        assert u is not None
        return u.household_id


def _chip_names_in(html: str) -> list[str]:
    """Pull out the visible chip labels (in DOM order) from a rendered
    shopping page. Anchors on the `aria-label="Add ... to shopping list"`
    that only the chip buttons carry — the quick-add submit uses
    `aria-label="Add to shopping list"` (no item name), so this regex
    won't pick it up."""
    return re.findall(
        r'aria-label="Add ([^"]+) to shopping list"', html,
    )


def _add_pantry(c: Client, name: str):
    return c.post("/pantry", htmx=True, data={
        "name": name, "quantity": "", "unit": "", "notes": "",
        "submit": "Add",
    })


# ---------------------------------------------------------------------------
# 1. Bump behavior on each ShoppingItem-creation path
# ---------------------------------------------------------------------------

class TestFrequencyBumpsOnAdd:
    def test_shopping_add_creates_first_frequency_row(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")

        _add_shopping(client, "Milk")

        assert _freq_count(app, hid, "Milk") == 1
        assert _freq_display(app, hid, "Milk") == "Milk"

    def test_repeat_add_same_name_increments_count(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")

        for _ in range(3):
            _add_shopping(client, "Milk")

        assert _freq_count(app, hid, "Milk") == 3, (
            "Three adds of 'Milk' must produce a single frequency row "
            "with count=3, not three rows."
        )

    def test_case_folding_collapses_to_one_row(self, client, app):
        """'Milk', 'milk', and 'MILK' must collapse to a single
        frequency counter — otherwise the chip strip would show the
        same product three different ways."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")

        _add_shopping(client, "Milk")
        _add_shopping(client, "milk")
        _add_shopping(client, "MILK")

        assert _freq_count(app, hid, "Milk") == 3
        # Only one row should exist for milk-anything
        with app.app_context():
            from models import ShoppingNameFrequency
            rows = ShoppingNameFrequency.query.filter_by(
                household_id=hid,
            ).all()
            assert len(rows) == 1, (
                f"Expected 1 distinct frequency row; got {len(rows)} "
                f"({[r.name_lower for r in rows]})"
            )

    def test_display_name_follows_most_recent_casing(self, client, app):
        """If the user types 'milk' twice then 'Milk' once, the chip
        should render 'Milk' (their most recent preference)."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")

        _add_shopping(client, "milk")
        _add_shopping(client, "milk")
        _add_shopping(client, "Milk")  # capitalized this time

        assert _freq_display(app, hid, "Milk") == "Milk"

    def test_pantry_to_shopping_crosslink_bumps_frequency(self, client, app):
        """The pantry's '+ Shop' button creates a ShoppingItem too —
        it must bump the frequency or items only added via that path
        would never become chip candidates."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")

        _add_pantry(client, "Sriracha")
        # Find the pantry row id
        pantry_html = client.get("/pantry").get_data(as_text=True)
        pid_match = re.search(r'id="pantry-item-(\d+)"', pantry_html)
        assert pid_match, "couldn't find pantry row id in /pantry HTML"
        pid = pid_match.group(1)

        # Tap '+ Shop' on the pantry row
        resp = client.post(f"/pantry/{pid}/add-to-shopping", htmx=True)
        assert resp.status_code == 200

        assert _freq_count(app, hid, "Sriracha") == 1, (
            "Pantry→shopping cross-link must bump the frequency counter, "
            "otherwise items only added through this path would never "
            "show up as chips."
        )

    def test_meal_plan_need_to_shopping_bumps_frequency(self, client, app):
        """Both meal-plan-need cross-links — '+ Shop' on a single
        ingredient and '+ Shop All' for every need — must bump too.
        Mock OpenAI so we don't need a real key for this test."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")

        fake_plan = {
            "meal_name": "Spaghetti aglio e olio",
            "have": ["spaghetti", "garlic", "olive oil"],
            "need": ["fresh parsley", "red pepper flakes"],
            "steps": ["boil pasta", "fry garlic", "toss"],
        }

        # Single-item cross-link
        with patch("app._ask_openai_for_meal", return_value=(fake_plan, None)):
            r = client.post("/meal-plan", htmx=True, data={"prompt": "easy pasta"})
            assert r.status_code == 200

        with app.app_context():
            from models import MealPlan
            plan_id = MealPlan.query.first().id

        client.post(
            f"/meal-plan/{plan_id}/need-to-shopping",
            htmx=True, data={"name": "fresh parsley"},
        )
        assert _freq_count(app, hid, "fresh parsley") == 1

        # Bulk +Shop All — both need items get bumped
        client.post(
            f"/meal-plan/{plan_id}/need-all-to-shopping", htmx=True,
        )
        # parsley now at 2 (one single-add + one bulk-add); red pepper at 1
        assert _freq_count(app, hid, "fresh parsley") == 2
        assert _freq_count(app, hid, "red pepper flakes") == 1


# ---------------------------------------------------------------------------
# 2. Aggregation — what _top_shopping_suggestions returns
# ---------------------------------------------------------------------------

class TestSuggestionsAggregation:
    def test_min_distinct_threshold_suppresses_chips(self, client, app):
        """A brand-new household with only 1-2 distinct historical items
        gets an empty chip strip — not enough signal to be useful."""
        sign_up(client, "alice@example.com", "Alice")

        _add_shopping(client, "Milk")
        _add_shopping(client, "Eggs")  # only 2 distinct — under threshold

        html = client.get("/shopping").get_data(as_text=True)
        chips = _chip_names_in(html)
        assert chips == [], (
            f"Chips should be hidden until 3+ distinct historical names "
            f"(SHOPPING_SUGGESTION_MIN_DISTINCT); got {chips}"
        )

    def test_threshold_crossed_lights_up_chips(self, client, app):
        """Adding a 3rd distinct name lights up the strip. Subsequent
        renders show all three (clearing each first so they're not on
        the current list and therefore eligible for chips)."""
        sign_up(client, "alice@example.com", "Alice")

        # Build history of 3 distinct items, then clear so they're not
        # on the list. Easiest: add, then delete each.
        for name in ["Milk", "Eggs", "Bread"]:
            _add_shopping(client, name)

        # Items are still on the list, so they're excluded from chips.
        # Clear them to make them eligible suggestions.
        html = client.get("/shopping").get_data(as_text=True)
        for iid in re.findall(r'id="shopping-item-(\d+)"', html):
            client.delete(f"/shopping/{iid}")

        # NOW the chips should show all 3
        html = client.get("/shopping").get_data(as_text=True)
        chips = _chip_names_in(html)
        assert set(chips) == {"Milk", "Eggs", "Bread"}, (
            f"Once distinct count >= 3 and items aren't currently on "
            f"the list, all three should appear as chips. Got {chips}."
        )

    def test_ranked_by_count_desc(self, client, app):
        """The chip strip is ordered most-frequent-first. Tie-breaking
        is most-recently-added (covered separately)."""
        sign_up(client, "alice@example.com", "Alice")

        # Build history with clear ordering
        for _ in range(5): _add_shopping(client, "Milk")    # count=5
        for _ in range(3): _add_shopping(client, "Eggs")    # count=3
        for _ in range(2): _add_shopping(client, "Bread")   # count=2
        _add_shopping(client, "Butter")                     # count=1

        # Clear current list so all are eligible
        html = client.get("/shopping").get_data(as_text=True)
        for iid in re.findall(r'id="shopping-item-(\d+)"', html):
            client.delete(f"/shopping/{iid}")

        html = client.get("/shopping").get_data(as_text=True)
        chips = _chip_names_in(html)
        # The first three are unambiguously ordered (5 > 3 > 2 > 1).
        # We don't lock in Butter's position because anything <=4 chips
        # would include it; just verify the leading order.
        assert chips[0] == "Milk", f"Most-added should lead; got {chips}"
        assert chips[1] == "Eggs", f"Second most-added next; got {chips}"
        assert chips[2] == "Bread", f"Third most-added next; got {chips}"

    def test_caps_at_five_chips(self, client, app):
        """SHOPPING_SUGGESTION_LIMIT is 5 — even with 8 distinct items
        in history, the strip shows only the top 5."""
        sign_up(client, "alice@example.com", "Alice")

        for i, name in enumerate(
            ["A", "B", "C", "D", "E", "F", "G", "H"]
        ):
            # decreasing counts so ordering is deterministic
            for _ in range(8 - i):
                _add_shopping(client, name)

        # Clear so all eligible
        html = client.get("/shopping").get_data(as_text=True)
        for iid in re.findall(r'id="shopping-item-(\d+)"', html):
            client.delete(f"/shopping/{iid}")

        html = client.get("/shopping").get_data(as_text=True)
        chips = _chip_names_in(html)
        assert len(chips) == 5, (
            f"Strip must cap at SHOPPING_SUGGESTION_LIMIT (5); "
            f"got {len(chips)}: {chips}"
        )
        assert chips == ["A", "B", "C", "D", "E"], (
            f"Top 5 by count should be A-E (counts 8-4); got {chips}"
        )

    def test_current_list_items_are_excluded(self, client, app):
        """Items currently on the shopping list (any state — checked
        or unchecked) shouldn't appear as chips. The chips are
        forward-looking suggestions, not duplicators."""
        sign_up(client, "alice@example.com", "Alice")

        # Build 3+ distinct history to clear the min_distinct threshold
        for name in ["Milk", "Eggs", "Bread", "Butter"]:
            for _ in range(2):
                _add_shopping(client, name)

        # Clear all so they're all eligible chip candidates
        html = client.get("/shopping").get_data(as_text=True)
        for iid in re.findall(r'id="shopping-item-(\d+)"', html):
            client.delete(f"/shopping/{iid}")

        # Re-add Milk; it should disappear from chips
        _add_shopping(client, "Milk")

        html = client.get("/shopping").get_data(as_text=True)
        chips = _chip_names_in(html)
        assert "Milk" not in chips, (
            f"Item currently on the list must not appear as a chip "
            f"(would just duplicate). Got chips: {chips}"
        )
        assert "Eggs" in chips, "Other historical items should still be chips"

    def test_current_list_exclusion_is_case_insensitive(self, client, app):
        """Excluding 'Milk' from chips when 'milk' is on the list (and
        vice-versa). The chip name display is the most-recent casing
        but the EXCLUSION match is case-folded."""
        sign_up(client, "alice@example.com", "Alice")

        for name in ["Milk", "Eggs", "Bread"]:
            for _ in range(2):
                _add_shopping(client, name)

        html = client.get("/shopping").get_data(as_text=True)
        for iid in re.findall(r'id="shopping-item-(\d+)"', html):
            client.delete(f"/shopping/{iid}")

        # Add it back with DIFFERENT casing than the historical "Milk"
        _add_shopping(client, "milk")

        html = client.get("/shopping").get_data(as_text=True)
        chips = _chip_names_in(html)
        # Neither "milk" nor "Milk" should appear (excluded by case-folded match)
        assert "Milk" not in chips and "milk" not in chips, (
            f"Case-folded exclusion must work both ways. Got: {chips}"
        )

    def test_chip_reappears_after_item_is_cleared(self, client, app):
        """Lifecycle: chip disappears when added → reappears after item
        is removed (delete, clear-checked, or "I'm home"). Tests the
        delete path here; the partial re-render on other routes is
        structurally identical."""
        sign_up(client, "alice@example.com", "Alice")

        for name in ["Milk", "Eggs", "Bread"]:
            for _ in range(2):
                _add_shopping(client, name)

        # Wipe to make all eligible
        html = client.get("/shopping").get_data(as_text=True)
        for iid in re.findall(r'id="shopping-item-(\d+)"', html):
            client.delete(f"/shopping/{iid}")

        # Add Milk (should no longer be in chips)
        _add_shopping(client, "Milk")
        html = client.get("/shopping").get_data(as_text=True)
        assert "Milk" not in _chip_names_in(html)

        # Delete Milk (should reappear in chips)
        mid = re.search(r'id="shopping-item-(\d+)"', html).group(1)
        client.delete(f"/shopping/{mid}")

        html = client.get("/shopping").get_data(as_text=True)
        assert "Milk" in _chip_names_in(html), (
            "Once an item is removed from the list, its chip should be "
            "eligible to surface again (chip = forward-looking suggestion, "
            "not durable preference)."
        )

    def test_household_scoped(self, two_clients, app):
        """Frequency counters live per-household. Bob's adds don't
        influence Alice's chip strip."""
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")

        # Bob aggressively logs Marmite — his frequency should not leak
        # into Alice's chip strip.
        for _ in range(10):
            _add_shopping(bob, "Marmite")

        # Alice needs 3+ distinct history to even RENDER chips
        for name in ["Milk", "Eggs", "Bread"]:
            _add_shopping(alice, name)

        html = alice.get("/shopping").get_data(as_text=True)
        chips = _chip_names_in(html)
        assert "Marmite" not in chips, (
            "Frequency rows must not leak across households. "
            f"Alice saw Bob's Marmite in chips: {chips}"
        )


# ---------------------------------------------------------------------------
# 3. UI — chip strip structure + chip tap end-to-end
# ---------------------------------------------------------------------------

class TestChipStripUI:
    def test_strip_renders_with_strip_label(self, client, app):
        """The chip strip is labeled 'Add again' so users understand
        what they're tapping. Verify the label text is present when
        chips render."""
        sign_up(client, "alice@example.com", "Alice")

        for name in ["Milk", "Eggs", "Bread"]:
            _add_shopping(client, name)
        html = client.get("/shopping").get_data(as_text=True)
        for iid in re.findall(r'id="shopping-item-(\d+)"', html):
            client.delete(f"/shopping/{iid}")

        html = client.get("/shopping").get_data(as_text=True)
        assert "Add again" in html, (
            "Chip strip must be labeled 'Add again' so users understand "
            "the affordance."
        )

    def test_strip_hidden_when_no_history(self, client, app):
        """Brand-new account: no chip strip, no 'Add again' label,
        no false noise on first impression."""
        sign_up(client, "alice@example.com", "Alice")

        html = client.get("/shopping").get_data(as_text=True)
        assert _chip_names_in(html) == [], (
            "Empty-history households should see zero chips."
        )
        # And the label itself should also be absent
        assert "Add again" not in html, (
            "Chip strip label should not render when there are no "
            "suggestions to surface."
        )

    def test_chip_tap_creates_name_only_row(self, client, app):
        """End-to-end: tapping a chip POSTs to /shopping with just
        `name=` and the resulting row carries no qty/unit/notes
        (per the locked product decision — instant-add + name-only)."""
        sign_up(client, "alice@example.com", "Alice")
        hid = _household_id_for(app, "alice@example.com")

        # Build chip-eligible history
        for name in ["Milk", "Eggs", "Bread"]:
            for _ in range(2):
                _add_shopping(client, name)
        html = client.get("/shopping").get_data(as_text=True)
        for iid in re.findall(r'id="shopping-item-(\d+)"', html):
            client.delete(f"/shopping/{iid}")

        # Simulate the chip tap — POST with just `name` (this is exactly
        # what htmx sends from `hx-vals='{"name": "Milk"}'`).
        resp = client.post("/shopping", htmx=True, data={"name": "Milk"})
        assert resp.status_code == 200, (
            f"Chip tap should succeed; got {resp.status_code}. "
            f"Body: {resp.get_data(as_text=True)[:500]}"
        )

        # Verify the row was created with just the name
        with app.app_context():
            from models import ShoppingItem
            rows = ShoppingItem.query.filter_by(
                household_id=hid, name="Milk",
            ).all()
            assert len(rows) == 1, f"Expected 1 Milk row; got {len(rows)}"
            row = rows[0]
            assert row.quantity is None, (
                f"Chip-added rows must have NO quantity (locked decision: "
                f"name-only). Got quantity={row.quantity!r}"
            )
            assert row.unit is None, (
                f"Chip-added rows must have NO unit. Got unit={row.unit!r}"
            )
            assert row.notes is None, (
                f"Chip-added rows must have NO notes. Got notes={row.notes!r}"
            )

    def test_chip_tap_attributes_to_current_user(self, two_clients, app):
        """Provenance: a chip tap is an add by the CURRENT user, not
        whoever historically established the frequency. Matters in a
        roommate household — 'who put milk on the list' should be the
        person who tapped, not the most-recent typer.

        Setup short-circuits the invite UI by swapping Bob's
        household_id directly to Alice's; the invite handshake is
        covered by its own phase suite and isn't what we're testing
        here."""
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")

        alice_hid = _household_id_for(app, "alice@example.com")
        with app.app_context():
            from app import db
            from models import User
            bob_user = User.query.filter_by(email="bob@example.com").first()
            bob_user.household_id = alice_hid
            db.session.commit()
            bob_user_id = bob_user.id

        # Alice builds the chip-eligible history
        for name in ["Milk", "Eggs", "Bread"]:
            for _ in range(2):
                _add_shopping(alice, name)
        # Clear list so chips show (Bob can't see them otherwise)
        html = alice.get("/shopping").get_data(as_text=True)
        for iid in re.findall(r'id="shopping-item-(\d+)"', html):
            alice.delete(f"/shopping/{iid}")

        # Bob taps a chip — exact payload htmx sends from hx-vals
        resp = bob.post("/shopping", htmx=True, data={"name": "Milk"})
        assert resp.status_code == 200, (
            f"Bob's chip tap failed: {resp.status_code} "
            f"{resp.get_data(as_text=True)[:300]}"
        )

        with app.app_context():
            from models import ShoppingItem
            row = ShoppingItem.query.filter_by(
                household_id=alice_hid, name="Milk",
            ).first()
            assert row is not None, (
                "Bob's chip tap should have created a Milk row in "
                "Alice's household."
            )
            assert row.added_by_user_id == bob_user_id, (
                f"Chip tap by Bob should be attributed to Bob "
                f"(added_by={row.added_by_user_id}, bob_id={bob_user_id})"
            )

    def test_chip_button_has_post_to_shopping_endpoint(self, client, app):
        """Verify the chip button actually wires hx-post to /shopping
        with hx-vals containing the name — otherwise the chip is dead
        markup."""
        sign_up(client, "alice@example.com", "Alice")

        for name in ["Milk", "Eggs", "Bread"]:
            for _ in range(2):
                _add_shopping(client, name)
        html = client.get("/shopping").get_data(as_text=True)
        for iid in re.findall(r'id="shopping-item-(\d+)"', html):
            client.delete(f"/shopping/{iid}")

        html = client.get("/shopping").get_data(as_text=True)
        # At least one chip button should have hx-post="/shopping"
        # with hx-vals carrying a name
        chip_pattern = (
            r'hx-post="/shopping"[^>]*hx-vals=\'{"name": "(Milk|Eggs|Bread)"}\''
        )
        matches = re.findall(chip_pattern, html)
        assert matches, (
            "Chip buttons must POST to /shopping with hx-vals carrying "
            "the item name. Markup wiring regression."
        )
