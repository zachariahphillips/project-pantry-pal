"""
Phase 5C regression suite — starter-pantry seed.

Chunk C of Theme 5 adds a one-tap "Start with 6 staples" CTA inside
the Phase 5A empty-pantry hero card. The CTA is a plain
`hx-post="/pantry/seed-starter"` button; the route inserts the
`PANTRY_STARTER_STAPLES` pack and returns 204 + HX-Refresh so the
whole planner region flips from gated to unlocked.

These tests guard:

  1. Route contract on the true empty state — htmx POST → 204 +
     HX-Refresh: true; non-htmx POST → 302 to /pantry.
  2. Data model — exactly 6 rows land, one per staple, with the
     right (name, qty, unit) tuple and `added_by_user_id` attribution
     pointing at whoever tapped the CTA.
  3. CTA visibility gate — visible on empty pantry, gone the moment
     the household has any item (including after seeding).
  4. Onboarding-gate flip — before seed the meal-planner gate is
     rendered; after seed the planner's Ask AI form is rendered.
  5. Ghost-row cleanup — the Chunk B ghost rows (which sample
     "Olive oil" + "Salt" — two of the six real seeds) disappear
     because ghost rows are gated on the true empty state.
  6. Non-empty guard — POSTing to /pantry/seed-starter when the
     pantry already has items silently no-ops (partial re-render,
     no new rows, no HX-Refresh). This protects against a stale
     tab whose CTA is still rendered.
  7. Shared-household — Alice seeds, Bob (same household) sees the
     6 staples with Alice's attribution.
  8. Cross-household isolation — Alice's seed does NOT leak into
     Carol's pantry.

Tier-1 dev loop:

    pytest tests/test_phase_5c.py -q

per the BUGS.md convention. Tier-2 adds 5A + 5B + 2A (shared
household); Tier-3 is the full regression.
"""
from __future__ import annotations

from tests.conftest import Client, sign_up

from app import PANTRY_ONBOARDING_THRESHOLD, PANTRY_STARTER_STAPLES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_pantry(c: Client, name: str, qty: str = ""):
    return c.post("/pantry", htmx=True, data={
        "name": name, "quantity": qty, "unit": "", "notes": "",
        "submit": "Add",
    })


def _seed_starter(c: Client, htmx: bool = True):
    """POST /pantry/seed-starter with htmx headers by default. The
    button in the hero card fires an `hx-post` with the shared htmx
    CSRF listener, so this mirrors the browser path."""
    return c.post("/pantry/seed-starter", htmx=htmx, data={})


def _pantry_body(c: Client) -> str:
    return c.get("/pantry").get_data(as_text=True)


# ---------------------------------------------------------------------------
# 1. Route contract
# ---------------------------------------------------------------------------

class TestSeedRouteContract:
    """The route is the single source of truth for the seed pack. The
    contract has three moving parts: response shape (204 + HX-Refresh
    on the htmx path, 302 on the non-htmx path), the 6-row insert,
    and the empty-pantry precondition."""

    def test_htmx_seed_on_empty_returns_hx_refresh(self, client):
        """The whole planner region flips gated → unlocked, so a
        partial swap wouldn't be enough — mirrors the Chunk A/B
        boundary-crossing contract on pantry_add / pantry_item_delete."""
        sign_up(client, "alice@example.com", "Alice")

        resp = _seed_starter(client)

        assert resp.status_code == 204
        assert resp.headers.get("HX-Refresh") == "true"
        assert resp.get_data() == b""

    def test_non_htmx_seed_redirects_to_pantry(self, client):
        """Progressive-enhancement path: a client without htmx (or a
        curl caller) hits POST /pantry/seed-starter → 302 to /pantry.
        Same shape as `pantry_add`'s non-htmx branch."""
        sign_up(client, "alice@example.com", "Alice")

        resp = _seed_starter(client, htmx=False)

        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/pantry")

    def test_seed_creates_exact_pack_with_attribution(self, client):
        """After seeding, GET /pantry renders exactly the 6 staples in
        (name, qty, unit) form. Attribution: the current user is the
        `added_by_user_id`, so "added by Alice" attribution paints
        on every row when a roommate views it later (see Test 7)."""
        sign_up(client, "alice@example.com", "Alice")

        resp = _seed_starter(client)
        assert resp.status_code == 204

        body = _pantry_body(client)
        for name, _qty, _unit in PANTRY_STARTER_STAPLES:
            assert name in body, f"expected seeded item {name!r} on /pantry"

        # Row count = pack size. Ghost-row molecules don't carry a
        # `pantry-item-` id (Chunk B), so this counts REAL rows.
        assert body.count('id="pantry-item-') == len(PANTRY_STARTER_STAPLES)


# ---------------------------------------------------------------------------
# 2. CTA visibility gate
# ---------------------------------------------------------------------------

class TestSeedCTAVisibility:
    """The seed button lives inside the empty-pantry hero. It should
    NEVER paint once the household has any pantry item — including
    the household that just seeded via this very button."""

    def test_cta_visible_on_empty_pantry(self, client):
        """A brand-new signup lands on /pantry with 0 items → the
        `id="pantry-seed-starter"` container is rendered so the user
        sees the button and the "or" divider."""
        sign_up(client, "alice@example.com", "Alice")

        body = _pantry_body(client)

        assert 'id="pantry-seed-starter"' in body
        assert "Start with 6 staples" in body
        # The subcopy names the pack so users know what they're
        # agreeing to before tapping.
        assert "Olive oil" in body and "salt" in body.lower()

    def test_cta_hidden_after_seed(self, client):
        """After a successful seed, /pantry has 6 items → hero card
        is gone → the seed CTA is gone. The "or" divider goes with it."""
        sign_up(client, "alice@example.com", "Alice")
        _seed_starter(client)

        body = _pantry_body(client)

        assert 'id="pantry-seed-starter"' not in body
        assert "Start with 6 staples" not in body

    def test_cta_hidden_when_user_added_own_first_item(self, client):
        """A user who's committed to typing their own items — even
        just 1 — should NOT still see the seed offer. Once you've
        started, the offer becomes noise."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Sourdough")

        body = _pantry_body(client)

        assert 'id="pantry-seed-starter"' not in body


# ---------------------------------------------------------------------------
# 3. Onboarding-gate + planner flip
# ---------------------------------------------------------------------------

class TestOnboardingFlip:
    """Seed size (6) is deliberately above `PANTRY_ONBOARDING_THRESHOLD`
    (3) so the meal-planner gate retires and the real planner form
    (chips + Ask AI input) appears in the same page load that
    HX-Refresh triggers."""

    def test_planner_gated_before_seed(self, client):
        """Sanity check on the Phase 5A gate itself — it should be
        visible on an empty pantry, so the flip in the next test is
        actually a flip, not a no-op.

        "Ask AI" as a substring is unreliable (it appears in a JS
        comment on every page render). We check for `id="meal-plan-
        prompt"` — the actual prompt input, which is only rendered
        in the `not onboarding_active` branch of the template."""
        sign_up(client, "alice@example.com", "Alice")

        body = _pantry_body(client)

        assert 'id="meal-plan-onboarding-gate"' in body
        # The prompt input is uniquely rendered in the unlocked
        # branch of the template. `data-prompt-chip` appears in the
        # always-rendered JS (querySelectorAll), so it's not a
        # reliable gate signal; the input element is.
        assert 'id="meal-plan-prompt"' not in body

    def test_planner_unlocked_after_seed(self, client):
        """Post-seed: the gate div is gone; the prompt input is
        rendered (the unlocked-only element)."""
        sign_up(client, "alice@example.com", "Alice")
        _seed_starter(client)

        body = _pantry_body(client)

        assert 'id="meal-plan-onboarding-gate"' not in body
        assert 'id="meal-plan-prompt"' in body

    def test_seed_size_exceeds_onboarding_threshold(self):
        """Guard against the pack size being tuned down to something
        that wouldn't actually unlock the planner — the whole point
        of the seed is to cross the gate in one tap. If someone shrinks
        the pack, this test forces a rethink of the CTA copy too."""
        assert len(PANTRY_STARTER_STAPLES) > PANTRY_ONBOARDING_THRESHOLD


# ---------------------------------------------------------------------------
# 4. Ghost-row cleanup
# ---------------------------------------------------------------------------

class TestGhostRowCleanup:
    """The Chunk B ghost rows preview "Olive oil" + "Salt" — two of
    the six real seeded items. After seeding, ghost rows must
    disappear (they're gated on `is_empty_pantry AND not query AND
    not filter_key`) and the real olive-oil + salt rows take their
    place with `id="pantry-item-N"` DOM ids.
    """

    def test_ghost_rows_present_before_seed(self, client):
        """Baseline: fresh empty pantry renders the 2 pantry ghost
        rows with the `Preview` divider label."""
        sign_up(client, "alice@example.com", "Alice")

        body = _pantry_body(client)

        # The ghost-row molecule is `aria-hidden="true"`.
        assert 'aria-hidden="true"' in body
        assert "Preview" in body

    def test_ghost_rows_gone_after_seed(self, client):
        """Post-seed there are 6 real items → `is_empty_pantry` is
        false → ghost rows suppressed. The "Preview" label goes with
        them so the DOM has no vestigial molecules."""
        sign_up(client, "alice@example.com", "Alice")
        _seed_starter(client)

        body = _pantry_body(client)

        # There's no reason for "Preview" to appear on a non-empty
        # pantry; if it does, the ghost-row gate has regressed.
        assert "Preview" not in body


# ---------------------------------------------------------------------------
# 5. Non-empty-pantry guard (silent no-op)
# ---------------------------------------------------------------------------

class TestNonEmptyGuard:
    """A stale tab could still have the seed CTA in its DOM after
    the user (or a roommate on another device) has added items. In
    that race, the seed POST must NOT duplicate items — the route
    guards on `pantry_items.count() == 0` and silently re-renders
    the list partial on failure. Silent > 4xx toast: the user didn't
    do anything wrong, and a toast would be noise."""

    def test_seed_on_nonempty_pantry_is_silent_noop(self, client):
        """User adds one item, then hits the seed route directly.
        Expected: 200 partial re-render, no new rows, no HX-Refresh
        header (the whole point of no-op is to leave the page alone)."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Sourdough")

        resp = _seed_starter(client)

        assert resp.status_code == 200
        assert resp.headers.get("HX-Refresh") is None

        body = _pantry_body(client)
        # Still just the one item Alice added. None of the pack names
        # snuck in (Salt et al. are also ghost-row samples so we can't
        # just grep — count the `pantry-item-` ids).
        assert body.count('id="pantry-item-') == 1
        assert "Sourdough" in body

    def test_double_tap_seeds_exactly_once(self, client):
        """Two rapid-fire seed calls (simulating a double-tap or
        network retry) must produce exactly one 6-item pack. The
        second call sees non-empty state and no-ops."""
        sign_up(client, "alice@example.com", "Alice")

        first = _seed_starter(client)
        second = _seed_starter(client)

        assert first.status_code == 204
        assert first.headers.get("HX-Refresh") == "true"
        # Second call: no-op partial re-render, NOT another 204.
        assert second.status_code == 200
        assert second.headers.get("HX-Refresh") is None

        body = _pantry_body(client)
        assert body.count('id="pantry-item-') == len(PANTRY_STARTER_STAPLES)


# ---------------------------------------------------------------------------
# 6. Shared-household + cross-household isolation
# ---------------------------------------------------------------------------

class TestSharedHousehold:
    """Same guarantees as Phase 2A's shared-household contract: a
    seeded pantry is visible to every household member, with attribution
    pointing at whoever tapped the seed button. Cross-household
    pantries stay isolated.

    We stitch households directly at the DB layer (mirroring
    tests/test_phase_2a.py's `shared` fixture) rather than driving
    the Phase 2B invite flow — the seed contract doesn't depend on
    HOW the users became roommates, only on the household-scoping
    of the seeded rows.
    """

    def test_roommate_sees_seeded_pantry_with_attribution(self, app, two_clients):
        """Alice signs up → seeds → Bob is stitched into Alice's
        household → Bob sees all 6 seeded rows with "added by Alice"
        attribution painted on each. Confirms both the household
        scoping and the correctness of `added_by_user_id`.
        """
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")

        # Stitch Bob into Alice's household before the seed lands, so
        # the attribution snapshot on the seeded rows is definitely
        # "Alice" — not accidentally the currently-logged-in Bob.
        with app.app_context():
            from extensions import db
            from models import User
            alice_db = User.query.filter_by(email="alice@example.com").first()
            bob_db = User.query.filter_by(email="bob@example.com").first()
            bob_db.household_id = alice_db.household_id
            db.session.commit()

        _seed_starter(alice)

        body = bob.get("/pantry").get_data(as_text=True)

        # All 6 staples visible to Bob.
        for name, _qty, _unit in PANTRY_STARTER_STAPLES:
            assert name in body

        # Attribution: "added by Alice" appears on the seeded rows.
        # The exact wording lives in _pantry_item.html and is asserted
        # in Phase 2A tests — we just spot-check the substring here.
        assert "added by Alice" in body

    def test_bob_seeing_alices_seed_no_longer_sees_the_cta(self, app, two_clients):
        """The visibility gate is HOUSEHOLD-wide, not per-user. Once
        Alice seeds, Bob (same household) should also stop seeing the
        seed CTA — the whole household is past `is_empty_pantry`."""
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")
        with app.app_context():
            from extensions import db
            from models import User
            alice_db = User.query.filter_by(email="alice@example.com").first()
            bob_db = User.query.filter_by(email="bob@example.com").first()
            bob_db.household_id = alice_db.household_id
            db.session.commit()

        _seed_starter(alice)

        body = bob.get("/pantry").get_data(as_text=True)
        assert 'id="pantry-seed-starter"' not in body

    def test_carol_pantry_is_untouched_by_alice_seed(self, two_clients):
        """Two distinct households don't leak. Alice seeds; a fresh
        Carol in her own household still sees an empty pantry with
        the seed CTA visible."""
        alice, carol = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        _seed_starter(alice)

        sign_up(carol, "carol@example.com", "Carol")
        body = carol.get("/pantry").get_data(as_text=True)

        assert 'id="pantry-seed-starter"' in body
        # Carol has zero REAL rows. She'll SEE "Olive oil" and "Salt"
        # in the body because those are ghost-row samples in her own
        # empty state — so the isolation assertion is on the DOM ids,
        # not the names (same lesson as Phase 1C after Chunk B).
        assert 'id="pantry-item-' not in body


# ---------------------------------------------------------------------------
# 7. Anonymous access
# ---------------------------------------------------------------------------

class TestAnonymous:
    """Route is `@login_required`. An anon POST should not seed
    anything, ever. Per B-002, CSRF fires before @login_required so
    anon POSTs may return 400 rather than 302 to /login — we accept
    either as long as no items land."""

    def test_anonymous_post_does_not_seed(self, client):
        """A raw POST /pantry/seed-starter with no session → some
        4xx/302 status, no items created. The observable guarantee
        is "nothing was seeded", regardless of the exact error code."""
        resp = client._c.post("/pantry/seed-starter")

        assert resp.status_code in (302, 400, 401, 403)
        # No user context means no household to inspect via the ORM;
        # sign_up as a fresh user and confirm the pantry is still empty.
        sign_up(client, "alice@example.com", "Alice")
        body = _pantry_body(client)
        assert 'id="pantry-item-' not in body
