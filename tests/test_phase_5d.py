"""
Phase 5D regression suite — progressive first-run nudges.

Chunk D of Theme 5 adds three empty-state signposts — one per teach-
moment in the post-cold-start journey — rendered as small green-accent
banners via the shared `nudge_banner()` macro:

  1. #nudge-planner    — pantry cleared the onboarding gate, household
                         has 0 meal plans. Fires INSIDE the unlocked
                         planner section, pointing at the Ask AI input.
                         Auto-retires when meal_plans_count > 0.

  2. #nudge-plan-shop  — household has ≥1 meal plan, shopping is empty.
                         Fires above `#meal-plan-result` on /pantry,
                         pointing at the +Shop buttons in the card
                         below. Auto-retires when shopping_items_count
                         > 0.

  3. #nudge-crossoff   — shopping has ≥1 item, none of them checked.
                         Fires at the top of `#shopping-list`, pointing
                         at the checkboxes and the "I'm home →" bar.
                         Phase 6U makes this first-run session help:
                         it fires once on the first qualifying render,
                         then stays retired for that browser session.

The planner and +Shop nudges remain pure-derived from data — no schema
changes, no manual dismiss. The crossoff nudge is now intentionally
session-scoped first-run help so it doesn't become repeat-visit chrome.
A user who deletes all their plans WILL see nudge #1 again; that's correct.

Tests cover:

  A. Visibility gates — each nudge fires on exactly its trigger state
     and disappears the moment the state resolves.
  B. Copy anchors — the recognizable text is present so the nudge
     isn't rendering empty.
  C. Auto-retirement — after the taught action, the nudge is gone on
     the next page load.
  D. Household scoping — Alice's plan retires Bob's planner nudge
     (household-scoped counts, not per-user).
  E. Cross-household isolation — Alice's plans don't retire Carol's
     nudges in a separate household.
  F. Interaction with prior chunks — the ghost-row / seed / hero
     scenery from A/B/C still renders correctly alongside nudges.

Tier-1 dev loop:

    pytest tests/test_phase_5d.py -q

per the BUGS.md convention. Tier-2 adds 5A + 5B + 5C + adjacent
phases 3A/3B/3F/1C; Tier-3 is the full regression.
"""
from __future__ import annotations

import json

from tests.conftest import Client, sign_up

from app import PANTRY_STARTER_STAPLES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pantry_body(c: Client) -> str:
    return c.get("/pantry").get_data(as_text=True)


def _shopping_body(c: Client) -> str:
    return c.get("/shopping").get_data(as_text=True)


def _seed_starter(c: Client):
    """POST /pantry/seed-starter (Chunk C route). Fastest way to
    populate a stocked pantry that clears the onboarding gate — 6
    inserts in one call, no fixture wiring."""
    return c.post("/pantry/seed-starter", htmx=True, data={})


def _insert_meal_plan(app, email: str, meal_name: str = "Spaghetti carbonara"):
    """Insert a MealPlan directly against the DB — bypasses the OpenAI
    call for a focused test on the nudge gates. Mirrors the pattern
    from tests/test_phase_5a.py.

    Uses only `have` / `need` / `steps` since that's what the renderer
    consumes today; a future schema addition (`prep_time`, etc.) would
    still be backward-compatible with these fixtures.
    """
    from models import MealPlan, User
    from extensions import db
    with app.app_context():
        user = User.query.filter_by(email=email).one()
        plan = MealPlan(
            household_id=user.household_id,
            created_by_user_id=user.id,
            prompt="pasta night",
            meal_name=meal_name,
            response_json=json.dumps({
                "meal_name": meal_name,
                "have": ["pasta"],
                "need": ["eggs", "pancetta"],
                "steps": ["Boil pasta.", "Mix eggs.", "Combine."],
            }),
        )
        db.session.add(plan)
        db.session.commit()


def _add_shopping(c: Client, name: str = "tortillas"):
    """POST /shopping via the real form path. Uses htmx=True so we
    exercise the same code path the browser does."""
    return c.post("/shopping", htmx=True, data={
        "name": name, "quantity": "", "unit": "", "notes": "",
        "submit": "Add",
    })


def _toggle_shopping_item(c: Client, item_id: int):
    return c.post(f"/shopping/{item_id}/toggle", htmx=True, data={})


def _first_shopping_id(c: Client) -> int:
    """Scrape the first `shopping-item-N` id out of the rendered
    shopping page. The Chunk D nudge appears above the row list, so
    the id we return here is guaranteed to be a REAL row, not a
    Chunk B ghost-row molecule (those don't have `shopping-item-N`
    ids)."""
    import re
    body = _shopping_body(c)
    m = re.search(r'id="shopping-item-(\d+)"', body)
    assert m, "expected at least one shopping row"
    return int(m.group(1))


def _stitch_household(app, primary_email: str, secondary_email: str):
    """Move `secondary_email` into `primary_email`'s household. Mirrors
    the Phase 2A shared-household fixture pattern — DB-level stitch,
    no invite-flow round-trip needed for these tests."""
    from models import User
    from extensions import db
    with app.app_context():
        primary = User.query.filter_by(email=primary_email).one()
        secondary = User.query.filter_by(email=secondary_email).one()
        secondary.household_id = primary.household_id
        db.session.commit()


# ---------------------------------------------------------------------------
# 1. Planner nudge (#nudge-planner)
# ---------------------------------------------------------------------------

class TestPlannerNudge:
    """The planner nudge fires when the pantry has cleared the
    onboarding threshold AND the household has never made a plan. It
    lives INSIDE the unlocked planner branch of pantry.html, so if
    the branch doesn't render (still gated) the nudge can't fire —
    that gives us "gated → no nudge" for free.
    """

    def test_gated_no_nudge(self, client):
        """Fresh signup → 0 items → planner is gated (Phase 5A) →
        even if the DB had 0 plans, the unlocked branch never renders,
        so no planner nudge. Guards against a hypothetical future
        refactor that renders the nudge outside the branch."""
        sign_up(client, "alice@example.com", "Alice")

        body = _pantry_body(client)

        assert 'id="nudge-planner"' not in body

    def test_unlocked_no_plans_shows_nudge(self, client):
        """Once we cross the gate (seed does it in one tap), the
        planner unlocks AND the household has 0 plans → nudge fires."""
        sign_up(client, "alice@example.com", "Alice")
        _seed_starter(client)

        body = _pantry_body(client)

        assert 'id="nudge-planner"' in body
        # Copy anchor — "stocked" is the recognizable word in the
        # planner-nudge copy, and it doesn't appear elsewhere on the
        # page (unlike "pantry" which is everywhere).
        assert "stocked" in body

    def test_unlocked_after_first_plan_no_nudge(self, app, client):
        """Household has a plan → nudge auto-retires. This is the
        auto-dismiss guarantee for nudge #1."""
        sign_up(client, "alice@example.com", "Alice")
        _seed_starter(client)
        _insert_meal_plan(app, "alice@example.com")

        body = _pantry_body(client)

        assert 'id="nudge-planner"' not in body
        # Sanity: the planner is still unlocked (the whole reason we
        # can see the nudge slot at all).
        assert 'id="meal-plan-prompt"' in body

    def test_deleting_the_last_plan_re_shows_nudge(self, app, client):
        """Pure-derived nudge, pure-derived retirement: if the
        household loses its plans (e.g. plan cleanup, DB manipulation),
        the nudge comes back. Documents the intentional trade-off —
        this is contextual help, not a one-time tutorial."""
        sign_up(client, "alice@example.com", "Alice")
        _seed_starter(client)
        _insert_meal_plan(app, "alice@example.com")
        # Nudge is gone at this point (previous test proves it).

        from models import MealPlan
        from extensions import db
        with app.app_context():
            MealPlan.query.delete()
            db.session.commit()

        body = _pantry_body(client)
        assert 'id="nudge-planner"' in body


# ---------------------------------------------------------------------------
# 2. +Shop nudge (#nudge-plan-shop)
# ---------------------------------------------------------------------------

class TestPlanShopNudge:
    """The +Shop nudge fires when there's a meal plan to point at AND
    shopping is empty. Placement is deliberately OUTSIDE #meal-plan-
    result so the fresh POST /meal-plan swap doesn't clobber it — the
    nudge persists across htmx swap-ins and only retires on the next
    full page load once shopping has items."""

    def test_no_plan_no_nudge(self, client):
        """No plan → no card to point at → no nudge. Even if shopping
        is empty."""
        sign_up(client, "alice@example.com", "Alice")
        _seed_starter(client)  # unlocks planner but doesn't create a plan

        body = _pantry_body(client)

        assert 'id="nudge-plan-shop"' not in body

    def test_plan_and_empty_shopping_shows_nudge(self, app, client):
        """The teach-moment: user has a plan (they saw the AI reply)
        but hasn't discovered +Shop yet. Nudge fires above the meal-
        plan slot."""
        sign_up(client, "alice@example.com", "Alice")
        _seed_starter(client)
        _insert_meal_plan(app, "alice@example.com")

        body = _pantry_body(client)

        assert 'id="nudge-plan-shop"' in body
        # Copy anchor — "+ Shop" is the button label we're teaching.
        assert "+ Shop" in body

    def test_nudge_hidden_after_shopping_add(self, app, client):
        """Any shopping item — added via /shopping directly, +Shop
        from a plan need, "Add all" bulk, or the smart-recall chip —
        retires the nudge on the next page load. Test the primary
        POST /shopping path; the others funnel to the same table."""
        sign_up(client, "alice@example.com", "Alice")
        _seed_starter(client)
        _insert_meal_plan(app, "alice@example.com")
        _add_shopping(client, "tortillas")

        body = _pantry_body(client)

        assert 'id="nudge-plan-shop"' not in body

    def test_nudge_placement_outside_result_slot(self, app, client):
        """Design commitment: the nudge lives OUTSIDE #meal-plan-result
        so an htmx swap into that container preserves the nudge. We
        verify the DOM ordering by checking the nudge id appears
        BEFORE #meal-plan-result in the rendered body.

        If this test breaks, either the nudge got moved inside the
        result slot (bad — fresh POST swap will delete it) or the
        result slot moved above the nudge (unusual layout change that
        deserves a design review)."""
        sign_up(client, "alice@example.com", "Alice")
        _seed_starter(client)
        _insert_meal_plan(app, "alice@example.com")

        body = _pantry_body(client)

        nudge_pos = body.find('id="nudge-plan-shop"')
        slot_pos = body.find('id="meal-plan-result"')
        assert nudge_pos != -1 and slot_pos != -1
        assert nudge_pos < slot_pos, (
            "nudge must appear before #meal-plan-result so the htmx "
            "swap into that container preserves it"
        )


# ---------------------------------------------------------------------------
# 3. Cross-off nudge (#nudge-crossoff)
# ---------------------------------------------------------------------------

class TestCrossoffNudge:
    """The cross-off nudge fires on /shopping when items exist but
    nothing is checked. It sits at the top of #shopping-list (above
    the "Add again" chips) so it's the first thing the user sees
    when they land on a fresh unchecked list."""

    def test_empty_shopping_no_nudge(self, client):
        """No items → no nudge. Ghost rows handle the empty-list
        teaching (Chunk B); the nudge is for the "has items, none
        checked" state specifically."""
        sign_up(client, "alice@example.com", "Alice")

        body = _shopping_body(client)

        assert 'id="nudge-crossoff"' not in body

    def test_unchecked_items_show_nudge(self, client):
        """Add one item → still 0 checked → nudge fires. This is the
        primary teach-moment for the two-way shopping flow. Phase 6U
        makes this visible on the first qualifying response only, so
        assert against the POST response that created the list item."""
        sign_up(client, "alice@example.com", "Alice")

        body = _add_shopping(client, "tortillas").get_data(as_text=True)

        assert 'id="nudge-crossoff"' in body
        # Copy anchors — "I'm home" is the recognizable label we're
        # pointing at; "checkbox" describes the mechanic.
        assert "I&#39;m home" in body or "I'm home" in body
        assert "checkbox" in body

    def test_check_one_item_retires_nudge(self, client):
        """Checking the first item flips `checked_count` 0 → 1;
        nudge disappears; the "N checked off" action bar takes over.
        The two coordinate cleanly — one appears exactly as the other
        retires."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "tortillas")
        item_id = _first_shopping_id(client)
        _toggle_shopping_item(client, item_id)

        body = _shopping_body(client)

        assert 'id="nudge-crossoff"' not in body
        # The checked-actions bar has taken its place (Phase 3F).
        # "I'm home →" is the action-bar label; presence here confirms
        # the flow-over is clean, not just "both hidden".
        assert "I&#39;m home" in body or "I'm home" in body
        assert "1 checked off" in body

    def test_uncheck_last_item_does_not_re_show_seen_nudge(self, client):
        """Phase 6U turns the crossoff strip into once-per-session help.
        If the user checks then unchecks their only item, the state
        qualifies again but the session has already seen the hint."""
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "tortillas")
        item_id = _first_shopping_id(client)
        _toggle_shopping_item(client, item_id)  # check
        _toggle_shopping_item(client, item_id)  # uncheck

        body = _shopping_body(client)
        assert 'id="nudge-crossoff"' not in body


# ---------------------------------------------------------------------------
# 4. Household scoping (Alice's actions retire Bob's nudges)
# ---------------------------------------------------------------------------

class TestHouseholdScoping:
    """All three nudges gate on household-scoped counts (`.meal_plans`,
    `.shopping_items`), so a teach-moment retired by one roommate is
    retired for every roommate. Matches the household-scoped semantics
    of every other user-visible count in the app."""

    def test_alices_plan_retires_bobs_planner_nudge(self, app, two_clients):
        """Alice + Bob share a household. Alice seeds; both see the
        planner nudge. Alice makes a plan; Bob's planner nudge is
        also gone the next time he loads /pantry."""
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")
        _stitch_household(app, "alice@example.com", "bob@example.com")

        _seed_starter(alice)

        # Baseline: Bob sees the planner nudge because his household
        # has cleared the gate (via Alice's seed) and has 0 plans.
        assert 'id="nudge-planner"' in _pantry_body(bob)

        _insert_meal_plan(app, "alice@example.com")

        assert 'id="nudge-planner"' not in _pantry_body(bob)

    def test_alices_shopping_add_retires_bobs_plan_shop_nudge(self, app, two_clients):
        """Same scoping for nudge #2. Household-scoped `.shopping_items`
        count → Alice's add retires Bob's nudge."""
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")
        _stitch_household(app, "alice@example.com", "bob@example.com")
        _seed_starter(alice)
        _insert_meal_plan(app, "alice@example.com")

        assert 'id="nudge-plan-shop"' in _pantry_body(bob)

        _add_shopping(alice, "tortillas")

        assert 'id="nudge-plan-shop"' not in _pantry_body(bob)

    def test_alices_check_retires_bobs_crossoff_nudge(self, app, two_clients):
        """Nudge #3 lives on /shopping, same scoping."""
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")
        _stitch_household(app, "alice@example.com", "bob@example.com")
        _add_shopping(alice, "tortillas")

        assert 'id="nudge-crossoff"' in _shopping_body(bob)

        item_id = _first_shopping_id(alice)
        _toggle_shopping_item(alice, item_id)

        assert 'id="nudge-crossoff"' not in _shopping_body(bob)


# ---------------------------------------------------------------------------
# 5. Cross-household isolation
# ---------------------------------------------------------------------------

class TestCrossHouseholdIsolation:
    """Two independent households don't share nudge state. Alice's
    plan in her household doesn't retire Carol's nudge in Carol's own
    (separately-stocked) household."""

    def test_alices_plan_does_not_retire_carols_planner_nudge(self, app, two_clients):
        """Distinct households → each computes its own counts."""
        alice, carol = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        _seed_starter(alice)
        _insert_meal_plan(app, "alice@example.com")

        sign_up(carol, "carol@example.com", "Carol")
        _seed_starter(carol)

        body = _pantry_body(carol)
        assert 'id="nudge-planner"' in body


# ---------------------------------------------------------------------------
# 6. Interaction with prior Theme 5 chunks
# ---------------------------------------------------------------------------

class TestInteractionWithPriorChunks:
    """Chunk D nudges shouldn't clash with A/B/C scenery. Specifically:
    on a brand-new empty pantry, we still get the Phase 5A hero card
    + Phase 5B ghost rows + Phase 5C seed CTA, and none of the Chunk
    D nudges paint (because we're gated / no plan / no shopping)."""

    def test_fresh_signup_shows_prior_scenery_no_nudges(self, client):
        """Empty pantry: hero + ghost rows + seed CTA (from A/B/C)
        all visible; all three Chunk D nudges silent."""
        sign_up(client, "alice@example.com", "Alice")

        body = _pantry_body(client)

        # Phase 5A hero + 5C seed CTA + 5B ghost rows still there.
        assert 'id="pantry-add-hero"' in body
        assert 'id="pantry-seed-starter"' in body
        assert "Preview" in body

        # But none of the D nudges fire on a fresh empty pantry.
        assert 'id="nudge-planner"' not in body
        assert 'id="nudge-plan-shop"' not in body

    def test_seeded_pantry_shows_planner_nudge_and_no_prior_scenery(self, client):
        """Post-seed: A/B/C empty-state scenery all retires; the D
        planner nudge takes their place. Documents the hand-off."""
        sign_up(client, "alice@example.com", "Alice")
        _seed_starter(client)

        body = _pantry_body(client)

        # A/B/C scenery retired.
        assert 'id="pantry-add-hero"' not in body
        assert 'id="pantry-seed-starter"' not in body
        assert "Preview" not in body

        # D planner nudge takes over.
        assert 'id="nudge-planner"' in body

    def test_all_six_seeds_present_alongside_planner_nudge(self, client):
        """Sanity: seeded pack still lands (Chunk C contract) and
        the planner nudge is visible in the SAME render. Guards
        against a nudge accidentally consuming the seed items or
        the seed accidentally hiding the nudge slot."""
        sign_up(client, "alice@example.com", "Alice")
        _seed_starter(client)

        body = _pantry_body(client)

        for name, _qty, _unit in PANTRY_STARTER_STAPLES:
            assert name in body, f"expected seeded item {name!r}"
        assert 'id="nudge-planner"' in body


# ---------------------------------------------------------------------------
# 7. Anonymous access + partial re-render coverage
# ---------------------------------------------------------------------------

class TestAnonymous:
    """`/pantry` and `/shopping` are `@login_required` — anon can't
    reach them. This is documented already for prior phases; we spot-
    check here to prove the nudge helper doesn't accidentally leak on
    an unauth path."""

    def test_anon_get_pantry_redirects(self, client):
        resp = client._c.get("/pantry")
        assert resp.status_code in (302, 401)

    def test_anon_get_shopping_redirects(self, client):
        resp = client._c.get("/shopping")
        assert resp.status_code in (302, 401)
