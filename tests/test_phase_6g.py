"""
Phase 6G regression suite — hide search + household cards on empty pantry.

Small chunk from `PLANS/ux-improvements-plan.md` sec 1.2. Pre-6G, a
fresh signed-up user landed on /pantry seeing four things:

  1. Onboarding hero card (Phase 5A)
  2. "Start with 6 staples" seed button (Phase 5C)
  3. Pantry search input (nothing to search)
  4. Household share card ("Just you for now — invite a roommate")

The last two were chrome noise. The search field had nothing to
match against; the household card promoted roommate-invite before
the user had put a single thing in the pantry to share. Both wedged
between the hero card and the seed button and away from the user's
actual first-run job (add an item).

6G gates both. The search input hides when `is_empty_pantry`. The
household card hides UNLESS one of three "there's substance here"
signals is true:

  - `pantry_item_count > 0` (something worth sharing)
  - `members|length > 1` (a roommate has already joined; card is
    the roster, not just an invite widget)
  - `invites` truthy (an invite is minted and pending — hiding
    would strand the user with no way to see/copy/revoke it)

These tests guard:

  1. Fresh solo pantry hides BOTH.
  2. First pantry item unlocks BOTH.
  3. Deleting the last item hides BOTH again (symmetric with #2).
  4. A minted invite keeps the household card visible even on an
     empty pantry, because the invite is only manageable from
     inside the card.
  5. The search input DOESN'T come back just because there's an
     invite pending — search is a pantry function, not a household
     function.
  6. A joined roommate keeps the household card visible on an
     empty pantry, because the card is the roster / member roll
     at that point.

Tier-1 dev loop:

    pytest tests/test_phase_6g.py -q
"""
from __future__ import annotations

from tests.conftest import Client, sign_up


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_pantry(c: Client, name: str = "Olive oil"):
    return c.post("/pantry", htmx=True, data={
        "name": name, "quantity": "", "unit": "", "notes": "",
        "submit": "Add",
    })


def _pantry_body(c: Client) -> str:
    return c.get("/pantry").get_data(as_text=True)


def _search_input_present(html: str) -> bool:
    """The pantry search input has a stable id we key the gate off.
    Testing on the id (not the placeholder text) means a future
    placeholder edit doesn't accidentally pass this check."""
    return 'id="search"' in html and 'name="q"' in html


def _household_share_present(html: str) -> bool:
    """`id="household-share"` is the aside wrapper of the card. The
    partial always renders that id on the outer <aside> — its
    presence or absence is a clean signal of whether the include
    fired at all."""
    return 'id="household-share"' in html


def _add_pantry_item_direct(app, email: str, name: str = "Olive oil"):
    """Add a pantry item directly via the ORM. Used when a test
    needs to set up state that the HTTP path already covered
    elsewhere — we don't want to re-exercise POST /pantry every
    time, and the direct write is faster and clearer about intent.

    Both `added_by_user_id` and `household_id` are required on
    PantryItem — the former records who added it (DB column is
    named `user_id` for migration reasons), the latter scopes
    visibility. We pull the anchor user and populate both via the
    Python attribute name, not the DB column name."""
    with app.app_context():
        from extensions import db
        from models import User, PantryItem
        u = User.query.filter_by(email=email).first()
        item = PantryItem(
            added_by_user_id=u.id,
            household_id=u.household_id,
            name=name,
        )
        db.session.add(item)
        db.session.commit()
        return item.id


def _delete_pantry_item_direct(app, item_id: int):
    with app.app_context():
        from extensions import db
        from models import PantryItem
        it = db.session.get(PantryItem, item_id)
        assert it is not None, f"pantry item {item_id} not found"
        db.session.delete(it)
        db.session.commit()


def _add_second_household_member(app, email: str, name: str = "Bob"):
    """Simulate a joined roommate without exercising the full
    /join/<token> flow — we just insert a second User into the same
    household. Enough to satisfy `members|length > 1` at render time,
    which is what the gate keys on. The invite/join flow itself has
    its own coverage in test_phase_2b."""
    with app.app_context():
        from extensions import db
        from models import User
        anchor = User.query.filter_by(email=email).first()
        roommate = User(
            email=f"roommate-{email}",
            name=name,
            household_id=anchor.household_id,
        )
        roommate.set_password("testpass123")
        db.session.add(roommate)
        db.session.commit()


# ---------------------------------------------------------------------------
# 1. Fresh solo pantry — BOTH hidden
# ---------------------------------------------------------------------------

class TestFreshSoloPantryHidesBoth:
    def test_search_input_absent_on_empty_pantry(self, client):
        """A pantry with zero items has nothing to search. Rendering
        the input anyway means the user's eye is drawn to a field
        that literally cannot help them on this visit — 6G hides
        it until there's something to filter."""
        sign_up(client, "fresh@example.com", "Fresh")
        html = _pantry_body(client)
        assert not _search_input_present(html), (
            "Empty pantry must not render the search input. Users "
            "have nothing to search yet; the field is pure chrome "
            "and wedges between the hero card and the seed button."
        )

    def test_household_share_card_absent_on_empty_pantry(self, client):
        """Roommate-invite pitched before the user has added a
        single item is misaligned with the moment. The hero card
        owns this screen; the invite card can wait."""
        sign_up(client, "fresh@example.com", "Fresh")
        html = _pantry_body(client)
        assert not _household_share_present(html), (
            "Empty pantry must not render the household share card. "
            "The card promotes roommate-invite; on a first-run empty "
            "state the user hasn't stocked anything to share yet."
        )

    def test_hero_card_still_present(self, client):
        """Sanity: 6G hides the SECONDARY empty-state chrome. The
        primary onboarding hero (Phase 5A) must remain — that's
        the whole point of the empty state's UI."""
        sign_up(client, "fresh@example.com", "Fresh")
        html = _pantry_body(client)
        assert "Let's stock your pantry." in html
        assert 'id="pantry-add-hero"' in html


# ---------------------------------------------------------------------------
# 2. First item unlocks both
# ---------------------------------------------------------------------------

class TestFirstItemUnlocksBoth:
    def test_search_input_appears_after_first_item(self, client):
        sign_up(client, "fresh@example.com", "Fresh")
        _add_pantry(client, "Olive oil")
        html = _pantry_body(client)
        assert _search_input_present(html), (
            "The search input must snap back into place as soon as "
            "the pantry has any item. Same gate the hero card "
            "retires on (is_empty_pantry)."
        )

    def test_household_share_card_appears_after_first_item(self, client):
        sign_up(client, "fresh@example.com", "Fresh")
        _add_pantry(client, "Olive oil")
        html = _pantry_body(client)
        assert _household_share_present(html), (
            "The household share card must render once the pantry "
            "has substance to share (pantry_item_count > 0)."
        )


# ---------------------------------------------------------------------------
# 3. Symmetry — deleting the last item hides both again
# ---------------------------------------------------------------------------

class TestDeletingLastItemHidesBoth:
    def test_search_input_hides_when_pantry_empties_again(self, app, client):
        """Same gate applied at render-time both ways. If a user
        adds an item, then removes it, we're back to the same
        empty-state we started at — search should hide again.
        Guards against a "one-way" gate bug where the search
        input persists once shown."""
        sign_up(client, "fresh@example.com", "Fresh")
        item_id = _add_pantry_item_direct(app, "fresh@example.com")
        assert _search_input_present(_pantry_body(client))
        _delete_pantry_item_direct(app, item_id)
        html = _pantry_body(client)
        assert not _search_input_present(html)

    def test_household_share_hides_when_pantry_empties_again(self, app, client):
        """Same as above for the household card — with the caveat
        that if there's a pending invite or a joined roommate,
        the card stays. See TestPendingInviteKeepsCardVisible +
        TestJoinedRoommateKeepsCardVisible for those branches."""
        sign_up(client, "fresh@example.com", "Fresh")
        item_id = _add_pantry_item_direct(app, "fresh@example.com")
        assert _household_share_present(_pantry_body(client))
        _delete_pantry_item_direct(app, item_id)
        html = _pantry_body(client)
        assert not _household_share_present(html)


# ---------------------------------------------------------------------------
# 4. Pending invite keeps the household card visible on empty pantry
# ---------------------------------------------------------------------------

class TestPendingInviteKeepsCardVisible:
    def test_pending_invite_keeps_card_when_pantry_empty(self, app, client):
        """Once an invite is minted and pending, the household card
        is the ONLY surface to see it, copy the link, or revoke it.
        Hiding the card while an invite is live would strand the
        user with an invisible, un-revocable link — that's a
        security-adjacent bug, not just a UX quibble."""
        sign_up(client, "fresh@example.com", "Fresh")
        item_id = _add_pantry_item_direct(app, "fresh@example.com")
        # Mint an invite while there's an item (card is visible).
        client.post("/household/invite", htmx=True)
        # Now clear the pantry — the invite persists but there are
        # no items and no roommates.
        _delete_pantry_item_direct(app, item_id)

        html = _pantry_body(client)
        assert _household_share_present(html), (
            "A pending invite must keep the household card visible "
            "on an empty pantry — the card is the only surface to "
            "see/copy/revoke it."
        )
        # And the invite link itself must be readable inside the card.
        assert "/join/" in html, (
            "The pending invite's URL must still render so the "
            "user can copy it. Otherwise showing the card was "
            "cosmetic; the actual invite management surface would "
            "have gone dark."
        )

    def test_search_input_still_hidden_despite_pending_invite(
            self, app, client):
        """Search is a PANTRY function, not a household function.
        Having a pending invite doesn't give the pantry anything
        to search — the search input stays hidden. Guards against
        a lazy fix that gates both blocks on the same OR-chain."""
        sign_up(client, "fresh@example.com", "Fresh")
        item_id = _add_pantry_item_direct(app, "fresh@example.com")
        client.post("/household/invite", htmx=True)
        _delete_pantry_item_direct(app, item_id)

        html = _pantry_body(client)
        assert not _search_input_present(html), (
            "Search input must remain hidden on an empty pantry even "
            "when a household invite is pending — an invite doesn't "
            "put anything in the pantry to search."
        )


# ---------------------------------------------------------------------------
# 5. Joined roommate keeps the card visible on empty pantry
# ---------------------------------------------------------------------------

class TestJoinedRoommateKeepsCardVisible:
    def test_two_members_keeps_card_when_pantry_empty(self, app, client):
        """After a roommate joins, the household card is the
        roster — it shows both members' names. Hiding it because
        the pantry is briefly empty erases the "we're in this
        household together" signal that Phase 2B was designed to
        surface."""
        sign_up(client, "fresh@example.com", "Fresh")
        _add_second_household_member(app, "fresh@example.com", "Bob")
        html = _pantry_body(client)
        assert _household_share_present(html), (
            "Two-member household must keep the share card visible "
            "on an empty pantry — the card is the roster, not just "
            "an invite widget."
        )
        # Roster copy path renders — "2 members: Fresh, Bob" (or
        # whichever order the ORM returns them in). Substring-match
        # on the count to stay resilient to name order.
        assert "2 members" in html
