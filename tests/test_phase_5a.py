"""
Phase 5A regression suite — pantry empty-state overhaul.

Chunk A of Theme 5 introduces onboarding gating for a brand-new
household. Two mechanics working in tandem:

  1. Add-item hero — when `pantry_item_count == 0`, the add-item form
     is wrapped in a larger card with an icon, headline ("Let's stock
     your pantry."), and subcopy. The redundant "Your pantry is empty"
     dashed card below the search bar is suppressed in this state
     because the hero card is a bigger, more prominent version of the
     same signal. The submit button reads "Add your first item"
     instead of "Add to pantry" so the CTA matches the moment.

  2. Meal-planner gate — while `pantry_item_count < PANTRY_ONBOARDING_
     THRESHOLD` (3), the chips + input + spinner are hidden and replaced
     by a small progress panel ("Add N more items to unlock the AI
     planner") with dot-based visual progress. The heading, cost pill,
     and `latest_meal_plan` result slot remain visible regardless —
     the gate hides the LIVE planner UI, not the user's history.

These tests guard both behaviors, plus the boundary transitions
(0 → 1 items, 2 → 3 items) since those are where UX bugs typically
hide.
"""
from __future__ import annotations

import re

from tests.conftest import Client, sign_up

from app import PANTRY_ONBOARDING_THRESHOLD


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_pantry(c: Client, name: str, qty: str = ""):
    return c.post("/pantry", htmx=True, data={
        "name": name, "quantity": qty, "unit": "", "notes": "",
        "submit": "Add",
    })


def _pantry_body(c: Client) -> str:
    return c.get("/pantry").get_data(as_text=True)


def _seed(c: Client, count: int, prefix: str = "Item"):
    for i in range(count):
        _add_pantry(c, f"{prefix}{i}")


def _hero_present(html: str) -> bool:
    return (
        "Let's stock your pantry." in html
        and 'id="pantry-add-hero"' in html
    )


def _gate_panel_present(html: str) -> bool:
    return 'id="meal-plan-onboarding-gate"' in html


def _planner_form_present(html: str) -> bool:
    return 'id="meal-plan-prompt"' in html


# ---------------------------------------------------------------------------
# 1. Threshold constant + basic default behavior
# ---------------------------------------------------------------------------

class TestThresholdConstant:
    def test_threshold_is_three(self):
        """The design decision (3 items) is captured as a module-level
        constant. If a future tuning changes this, the whole suite
        below reads from the constant so the tests keep tracking."""
        assert PANTRY_ONBOARDING_THRESHOLD == 3


# ---------------------------------------------------------------------------
# 2. Empty pantry — hero card + gated planner
# ---------------------------------------------------------------------------

class TestBrandNewPantry:
    def test_hero_shows_on_empty_pantry(self, client):
        sign_up(client, "fresh@example.com", "Fresh")
        html = _pantry_body(client)
        assert _hero_present(html), (
            "Empty pantry must show the onboarding hero card with the "
            "'Let's stock your pantry.' headline. If missing, either "
            "the pantry_item_count isn't being passed to the template "
            "or the is_empty_pantry conditional broke."
        )

    def test_hero_wraps_the_add_form(self, client):
        """The hero card IS the add form (icon+headline+subcopy inside
        the same <form> element). Verify by capturing the full form
        tag+body and checking both the POST endpoint (attribute on
        the opening tag) and the name field (inside the tag)."""
        sign_up(client, "fresh@example.com", "Fresh")
        html = _pantry_body(client)
        # Capture the entire <form ... id="pantry-add-hero" ...>...</form>
        # block — needs to include the opening tag so hx-post (which
        # sits BEFORE the id attribute in the template) is captured.
        hero_form = re.search(
            r'<form\b[^>]*id="pantry-add-hero"[^>]*>(.*?)</form>',
            html, re.DOTALL,
        )
        assert hero_form, "Hero form region not found"
        full_match = hero_form.group(0)
        assert 'hx-post="/pantry"' in full_match, (
            "Hero card must contain the /pantry POST endpoint — the "
            "hero IS the add form, not just decoration above it"
        )
        assert 'name="name"' in full_match, (
            "Hero card must contain the name input field — the add "
            "form's core control"
        )
        # Sanity: also the icon + headline live inside the form body
        body = hero_form.group(1)
        assert "Let's stock your pantry." in body

    def test_submit_button_reads_add_your_first_item(self, client):
        """Empty state changes the CTA copy from 'Add to pantry' to
        'Add your first item'. Micro but important — the button label
        should match the moment."""
        sign_up(client, "fresh@example.com", "Fresh")
        html = _pantry_body(client)
        assert "Add your first item" in html
        # The generic label must NOT appear (it's the ONLY submit
        # button on this page, so exact-match on the "Add to pantry"
        # string is a clean signal).
        assert ">Add to pantry<" not in html, (
            "Empty pantry should not show the 'Add to pantry' label; "
            "that label is only for the non-onboarding compact form."
        )

    def test_default_empty_state_card_suppressed_when_hero_shows(
            self, client):
        """The old dashed 'Your pantry is empty. Add your first item
        using the form above.' card is redundant when the hero card
        is present. The wrapper's copy must not double-signal the
        empty state.

        Phase 5B note: `border-dashed border-stone-300` now legitimately
        appears on the page as part of the ghost-row preview (Phase 5B),
        so we no longer assert its absence. What matters for THIS test
        is the specific empty-state COPY ('Your pantry is empty.' +
        'Add your first item using the form above.') — the ghost rows
        don't carry that copy."""
        sign_up(client, "fresh@example.com", "Fresh")
        html = _pantry_body(client)
        assert "Your pantry is empty." not in html, (
            "The redundant '/pantry list' empty-state message should "
            "be suppressed when the hero is active. If this shows, "
            "we're double-signaling."
        )
        assert "Add your first item using the form above." not in html, (
            "The subcopy of the suppressed empty-state card leaked "
            "onto the page. The whole <div> should be skipped, not "
            "just its heading."
        )

    def test_gate_replaces_planner_form_on_empty_pantry(self, client):
        sign_up(client, "fresh@example.com", "Fresh")
        html = _pantry_body(client)
        assert _gate_panel_present(html), (
            "Empty pantry must render the meal-plan gate panel"
        )
        assert not _planner_form_present(html), (
            "The live planner form must not be present below the "
            "threshold — the whole point of the gate is to prevent "
            "the AI from being called with an empty pantry."
        )

    def test_gate_shows_correct_remaining_count(self, client):
        """Freshly signed up = 0 items. Copy should read 'Add 3 more
        items'. The pluralization on 'item(s)' is handled by the
        template; we check both the number and the noun form."""
        sign_up(client, "fresh@example.com", "Fresh")
        html = _pantry_body(client)
        # Grab the whole gate panel so we're not fooled by the number
        # 3 appearing elsewhere on the page (e.g. inside pill counts).
        panel = re.search(
            r'id="meal-plan-onboarding-gate"[^>]*>(.*?)</div>\s*</section>',
            html, re.DOTALL,
        )
        assert panel, "Could not locate the gate panel body"
        body = panel.group(1)
        # 3 items remain (0 of 3 added)
        assert ">3</span>" in body, (
            f"Gate should announce 3 items remaining; panel: {body[:400]}"
        )
        assert "items" in body, "Plural noun form for >1 remaining"
        assert "1 item " not in body, (
            "Singular noun form should not appear at 3 remaining"
        )

    def test_meal_plan_heading_still_visible_when_gated(self, client):
        """The Plan a meal heading STAYS visible so users know the
        feature exists — the gate just replaces the form area, it
        doesn't hide the whole section."""
        sign_up(client, "fresh@example.com", "Fresh")
        html = _pantry_body(client)
        assert 'id="meal-plan-heading"' in html
        assert ">\n        Plan a meal\n      <" in html or \
               ">Plan a meal<" in html

    def test_prompt_chips_hidden_when_gated(self, client):
        """Chips would be confusing if visible under the gate — tap
        would do nothing since the input they prefill is gone. Suppress
        them along with the form.

        Assertion uses `data-prompt-chip="` (with equals sign) to match
        only the HTML attribute form of the marker. The bare token
        `data-prompt-chip` also appears in JS (as an attribute
        selector `[data-prompt-chip]`) that stays in the DOM
        regardless — the JS is harmless when no matching buttons
        exist.
        """
        sign_up(client, "fresh@example.com", "Fresh")
        html = _pantry_body(client)
        assert 'data-prompt-chip="' not in html, (
            "Meal-planner chip BUTTONS must be hidden when the gate "
            "is active. If they're visible, taps prefill an input "
            "that doesn't exist — dead affordance."
        )
        # Belt-and-suspenders: no live planner input either
        assert 'id="meal-plan-prompt"' not in html


# ---------------------------------------------------------------------------
# 3. Boundary transition: 0 → 1 → 2 items (still gated)
# ---------------------------------------------------------------------------

class TestBelowThresholdWithSomeItems:
    def test_one_item_still_gated_but_hero_gone(self, client):
        """After adding the first item, the hero should retreat (its
        job is done — the user has proved they know how to add) but
        the meal-planner should stay gated until the threshold."""
        sign_up(client, "fresh@example.com", "Fresh")
        _add_pantry(client, "Milk")
        html = _pantry_body(client)
        assert not _hero_present(html), (
            "Hero must retreat after the first item is added. If it "
            "sticks around, we're nagging users past the point of "
            "usefulness."
        )
        assert _gate_panel_present(html), (
            "Meal-planner should still be gated at 1 item"
        )
        # 'Add to pantry' is the compact-form CTA — this literal
        # string doesn't appear anywhere else in the app (checked:
        # no JS comments, no other templates), so a plain substring
        # search is fine here.
        assert "Add to pantry" in html, (
            "Submit label should snap back to 'Add to pantry' once "
            "the pantry has any items"
        )
        assert "Add your first item" not in html, (
            "The hero-mode CTA must not linger past the empty state"
        )

    def test_one_item_shows_two_remaining_singular_pluralization(self, client):
        """1 of 3 items → 2 remaining. This tests both the count math
        AND the plural form (2 → 'items' plural)."""
        sign_up(client, "fresh@example.com", "Fresh")
        _add_pantry(client, "Milk")
        html = _pantry_body(client)
        panel = re.search(
            r'id="meal-plan-onboarding-gate"[^>]*>(.*?)</div>\s*</section>',
            html, re.DOTALL,
        )
        assert panel
        body = panel.group(1)
        assert ">2</span>" in body, "Should show 2 remaining at 1 item"
        assert "items" in body, "Plural form for 2 remaining"

    def test_two_items_shows_one_remaining_singular(self, client):
        """2 of 3 items → 1 remaining. Singular noun 'item' (not
        'items') — micro but a common wording bug."""
        sign_up(client, "fresh@example.com", "Fresh")
        _add_pantry(client, "Milk")
        _add_pantry(client, "Eggs")
        html = _pantry_body(client)
        panel = re.search(
            r'id="meal-plan-onboarding-gate"[^>]*>(.*?)</div>\s*</section>',
            html, re.DOTALL,
        )
        assert panel
        body = panel.group(1)
        assert ">1</span>" in body, "Should show 1 remaining at 2 items"
        # 'more item ' (singular) should be present; 'more items' shouldn't
        assert "more item " in body, (
            f"Should use singular 'item' at 1 remaining; got: {body[:400]}"
        )
        assert "more items" not in body, (
            "Plural noun leaked into the singular-remaining copy"
        )

    def test_progress_dots_track_item_count(self, client):
        """Dots visualize progress. Filled = green, pending = stone-300.
        The count of filled dots must match the item count."""
        sign_up(client, "fresh@example.com", "Fresh")
        _add_pantry(client, "Milk")
        _add_pantry(client, "Eggs")
        html = _pantry_body(client)
        panel = re.search(
            r'aria-label="Pantry progress"[^>]*>(.*?)</div>',
            html, re.DOTALL,
        )
        assert panel
        dots = panel.group(1)
        filled = dots.count("bg-green-600")
        pending = dots.count("bg-stone-300")
        assert filled == 2 and pending == 1, (
            f"At 2 items with a threshold of 3, expect 2 filled + 1 "
            f"pending dot; got filled={filled} pending={pending}"
        )


# ---------------------------------------------------------------------------
# 4. Threshold reached: planner unlocks
# ---------------------------------------------------------------------------

class TestThresholdReached:
    def test_three_items_unlocks_planner_form(self, client):
        sign_up(client, "fresh@example.com", "Fresh")
        _seed(client, 3)
        html = _pantry_body(client)
        assert not _gate_panel_present(html), (
            "Gate panel must disappear at the threshold"
        )
        assert _planner_form_present(html), (
            "Live planner input must appear at the threshold"
        )

    def test_three_items_restores_chips(self, client):
        sign_up(client, "fresh@example.com", "Fresh")
        _seed(client, 3)
        html = _pantry_body(client)
        # Match the HTML attribute (with `=`) — the bare token also
        # appears in JS `[data-prompt-chip]` selectors that stay in
        # the DOM regardless of the gate state.
        chip_buttons = re.findall(r'data-prompt-chip="[^"]+"', html)
        assert len(chip_buttons) >= 5, (
            f"Expected all 5 chip buttons to render at threshold; "
            f"found {len(chip_buttons)}"
        )
        # Sanity: the first chip's label is visible on the page
        assert "Tonight" in html

    def test_three_items_restores_ask_ai_button(self, client):
        sign_up(client, "fresh@example.com", "Fresh")
        _seed(client, 3)
        html = _pantry_body(client)
        assert ">\n          Ask AI\n        <" in html or ">Ask AI<" in html

    def test_three_items_restores_spinner_slot(self, client):
        """The hx-indicator target must exist once the form does —
        otherwise POST /meal-plan would fire with no visual feedback."""
        sign_up(client, "fresh@example.com", "Fresh")
        _seed(client, 3)
        html = _pantry_body(client)
        assert 'id="meal-plan-spinner"' in html

    def test_planner_subcopy_swaps_to_full_prompt(self, client):
        sign_up(client, "fresh@example.com", "Fresh")
        _seed(client, 3)
        html = _pantry_body(client)
        assert "Tell the AI what you want to make" in html
        assert "Add a few items first" not in html


# ---------------------------------------------------------------------------
# 5. Regression guards — hero doesn't leak into non-empty states
# ---------------------------------------------------------------------------

class TestHeroDoesNotLeak:
    def test_hero_absent_at_one_item(self, client):
        """The hero card must be scoped to the fully-empty case. At
        even 1 item it must disappear so the compact form takes over."""
        sign_up(client, "fresh@example.com", "Fresh")
        _add_pantry(client, "Milk")
        html = _pantry_body(client)
        assert "Let's stock your pantry." not in html
        assert 'id="pantry-add-hero"' not in html

    def test_hero_absent_after_threshold(self, client):
        sign_up(client, "fresh@example.com", "Fresh")
        _seed(client, 5)
        html = _pantry_body(client)
        assert "Let's stock your pantry." not in html

    def test_htmx_partial_response_omits_hero(self, client):
        """The hero is a full-page concern (pantry.html). htmx swaps of
        the pantry list partial (add/delete/density) should never
        include hero copy — they're just the list, not the wrapper.

        Practical failure mode this guards against: someone adds
        `pantry_item_count` to a partial context and accidentally
        pipes hero markup into the swap.
        """
        sign_up(client, "fresh@example.com", "Fresh")
        # Move past the onboarding zone so the tested add takes the
        # partial-swap fast path (not the full-page HX-Refresh path
        # that fires while ≤3 items).
        for name in ["Milk", "Eggs", "Rice"]:
            _add_pantry(client, name)
        resp = _add_pantry(client, "Pasta")  # 3 → 4, partial swap
        assert resp.status_code == 200
        partial = resp.get_data(as_text=True)
        assert "Let's stock your pantry." not in partial
        assert 'id="pantry-add-hero"' not in partial

    def test_deleting_all_items_returns_hx_refresh(
            self, client):
        """Phase 5B (closes B-001): deleting the last item now returns
        204 + HX-Refresh, symmetric to `pantry_add`'s onboarding-zone
        rule. The client's reload is what surfaces the hero + Phase 5B
        ghost preview together — a partial-swap alone can't repaint
        the hero because the hero lives ABOVE the pantry-list slot.

        Pre-5B this test asserted the partial contained 'Your pantry is
        empty' copy; that was documenting the B-001 bug as
        intentional-for-now. Chunk B inverts the contract."""
        sign_up(client, "fresh@example.com", "Fresh")
        _add_pantry(client, "Milk")
        html = _pantry_body(client)
        m = re.search(r'id="pantry-item-(\d+)"', html)
        assert m, "Newly added item should be visible"
        item_id = m.group(1)
        resp = client.delete(f"/pantry/{item_id}", htmx=True)
        assert resp.status_code == 204, (
            f"Delete-to-empty must return 204 (no body needed — the "
            f"client reloads the page). Got {resp.status_code}."
        )
        assert resp.headers.get("HX-Refresh") == "true", (
            "Delete-to-empty must set HX-Refresh:true. If missing, "
            "B-001 has regressed — the parent hero + ghost preview "
            "will stay stale until manual refresh."
        )


# ---------------------------------------------------------------------------
# 6. Boundary-crossing HX-Refresh on adds
# ---------------------------------------------------------------------------

# The partial-swap fast path is fine on non-boundary adds — the hero
# + gate blocks aren't part of the response, but nothing on those
# blocks needs to update between (e.g.) 3 items and 4 items. Only
# when a state boundary is crossed (0→1 retires the hero; below→above
# threshold unlocks the planner) do we need to force a full reload.


class TestBoundaryRefreshOnAdd:
    """Any add while still IN the onboarding zone (item count ≤
    threshold after the add) sets HX-Refresh so the client does a
    full page reload. Rationale: the hero card, the gate progress
    dots, and the "N more items" copy all live ABOVE the pantry-list
    slot in the page layout — a partial-list swap would leave them
    stale. Reloading is worth the cost during onboarding (≤3 reloads
    per new household) because it makes progress feel live.

    Once past the threshold, adds return the fast partial-swap path
    — no reason to reload the page just because item #4 was added."""

    def test_first_add_returns_hx_refresh(self, client):
        """0 → 1: still in the onboarding zone, hero must retreat."""
        sign_up(client, "fresh@example.com", "Fresh")
        resp = _add_pantry(client, "Olive oil")
        assert resp.status_code == 204
        assert resp.headers.get("HX-Refresh") == "true"

    def test_second_add_returns_hx_refresh(self, client):
        """1 → 2: still below threshold. Gate dots + 'N more' copy
        need to advance. Refresh."""
        sign_up(client, "fresh@example.com", "Fresh")
        _add_pantry(client, "Olive oil")
        resp = _add_pantry(client, "Salt")
        assert resp.status_code == 204
        assert resp.headers.get("HX-Refresh") == "true", (
            "Below-threshold adds must reload so the gate progress "
            "indicator advances live. Without this the 'N more items' "
            "copy stays stuck at the pre-add number until manual "
            "refresh — a broken feel during onboarding."
        )

    def test_threshold_add_returns_hx_refresh(self, client):
        """2 → 3: the threshold-crossing add. Gate goes away, live
        planner form appears — the 'oh nice, unlocked' moment."""
        sign_up(client, "fresh@example.com", "Fresh")
        _add_pantry(client, "Olive oil")
        _add_pantry(client, "Salt")
        resp = _add_pantry(client, "Rice")
        assert resp.status_code == 204
        assert resp.headers.get("HX-Refresh") == "true"

    def test_past_threshold_partial_swap(self, client):
        """4th add is past the threshold — back to the fast htmx
        partial-swap path. Full reloads here would be needless drag."""
        sign_up(client, "fresh@example.com", "Fresh")
        _add_pantry(client, "Olive oil")
        _add_pantry(client, "Salt")
        _add_pantry(client, "Rice")  # hits threshold, refresh
        resp = _add_pantry(client, "Pasta")  # 3 → 4, partial
        assert resp.status_code == 200
        assert "HX-Refresh" not in resp.headers
        body = resp.get_data(as_text=True)
        assert 'id="pantry-list"' in body


# ---------------------------------------------------------------------------
# 7. Historical meal plan still visible when gated
# ---------------------------------------------------------------------------

class TestHistoryPreservedBelowThreshold:
    def test_result_slot_renders_even_when_gated(self, client, app):
        """A user who generated a meal plan when pantry was >= 3 then
        deleted items down to 1 should still see the 'Last meal'
        teaser. The gate hides the LIVE planner UI (chips + form +
        spinner) but not the user's history — losing plan history on
        temporary pantry dips would feel like data disappearing."""
        import json

        from models import MealPlan, User

        sign_up(client, "fresh@example.com", "Fresh")
        # Seed a plan directly against the DB — bypasses the AI call
        # for a focused test on the gate's behavior. MealPlan needs
        # `response_json` (verbatim OpenAI payload); we provide the
        # minimum shape the render pipeline expects.
        with app.app_context():
            from extensions import db
            user = User.query.filter_by(email="fresh@example.com").one()
            plan = MealPlan(
                household_id=user.household_id,
                created_by_user_id=user.id,
                prompt="pasta night",
                meal_name="Spaghetti carbonara",
                response_json=json.dumps({
                    "meal_name": "Spaghetti carbonara",
                    "have": ["pasta"],
                    "need": ["eggs", "pancetta"],
                    "steps": ["Boil pasta.", "Mix eggs.", "Combine."],
                }),
            )
            db.session.add(plan)
            db.session.commit()

        html = _pantry_body(client)
        # Gate is active (0 pantry items) but the historical plan is visible
        assert _gate_panel_present(html)
        assert "Spaghetti carbonara" in html, (
            "The Last-meal teaser must render even when the gate is "
            "active. If missing, we're hiding user history along with "
            "the live planner UI."
        )
        assert "Last meal" in html
