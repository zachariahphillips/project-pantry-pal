"""
Phase 6F regression suite — empty-pantry planner subcopy de-duplication.

Small copy chunk from `PLANS/ux-improvements-plan.md` §1.1. Before 6F,
the empty pantry rendered TWO adjacent instructions that said the same
thing in slightly different words:

  Section H2 "Plan a meal"
    subcopy: "Add a few items first — the AI plans meals using what you have."
    ↓
  Dot-progress panel
    body:    "Add N more items to unlock the AI planner."

Two "Add … items" imperatives stacked one on top of the other. The
dot panel is the more actionable framing (it has the count, it has
the concrete "unlock" verb) — so 6F keeps the panel as-is and swaps
the H2 subcopy for a state descriptor:

    "Locked until your pantry has a few items."

This is a copy-only change on ONE line of `templates/pantry.html`.
No route changes, no partial changes, no gate-logic changes — the
`onboarding_active` conditional that already scoped the old string
still scopes the new one.

These tests guard:

  1. The old redundant string does NOT appear anywhere in the empty
     pantry render — that's the exact copy we're retiring. Any future
     refactor that resurrects it (e.g., a well-intentioned "restore
     the value prop" edit) surfaces here.
  2. The new "Locked until your pantry has a few items." string DOES
     appear on the empty pantry — it's the sole subcopy for that
     section now, so its absence would leave the H2 heading bare.
  3. Once the pantry crosses the onboarding threshold, the subcopy
     swaps to the un-locked branch ("Tell the AI what you want to
     make…") and the locked string is gone. Same conditional the
     rest of the empty-state UI keys on; this test locks the
     branching in place.
  4. The dot-progress panel's own "Add N more items to unlock the AI
     planner." string is preserved on the empty pantry. Two adjacent
     redundant strings was the bug; zero strings would be a new bug.

Tier-1 dev loop:

    pytest tests/test_phase_6f.py -q
"""
from __future__ import annotations

from tests.conftest import Client, sign_up

from app import PANTRY_ONBOARDING_THRESHOLD


# ---------------------------------------------------------------------------
# Helpers — pattern-matched to test_phase_5a.py for grep-consistency.
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


OLD_REDUNDANT_SUBCOPY = "Add a few items first"
NEW_LOCKED_SUBCOPY = "Locked until your pantry has a few items."
DOT_PANEL_INSTRUCTION_PREFIX = "more items to unlock the AI planner"
UNLOCKED_SUBCOPY_PREFIX = "Tell the AI what you want to make"


# ---------------------------------------------------------------------------
# 1. Empty pantry — new copy, old copy gone
# ---------------------------------------------------------------------------

class TestEmptyPantrySubcopy:
    def test_new_locked_subcopy_present_on_empty_pantry(self, client):
        """The `Plan a meal` H2 needs a subcopy — 6F replaces the
        redundant "Add a few items first…" with a state descriptor.
        If this string disappears entirely, the section renders as a
        bare heading with no context for why the planner input is
        missing."""
        sign_up(client, "fresh@example.com", "Fresh")
        html = _pantry_body(client)
        assert NEW_LOCKED_SUBCOPY in html, (
            f"Empty pantry must show the new locked-state subcopy "
            f"'{NEW_LOCKED_SUBCOPY}' under the 'Plan a meal' heading. "
            f"Missing subcopy leaves the section a bare H2 with a "
            f"progress panel below and no framing for why."
        )

    def test_old_redundant_subcopy_retired(self, client):
        """The bug we're fixing. Two adjacent instructions telling
        the user the same thing. If a future edit reintroduces
        'Add a few items first' anywhere on the empty pantry, we're
        back where we started."""
        sign_up(client, "fresh@example.com", "Fresh")
        html = _pantry_body(client)
        assert OLD_REDUNDANT_SUBCOPY not in html, (
            f"Empty pantry must not carry the pre-6F redundant string "
            f"'{OLD_REDUNDANT_SUBCOPY}' — it duplicated the dot-panel "
            f"instruction directly below it. See PLANS/"
            f"ux-improvements-plan.md §1.1."
        )

    def test_dot_panel_instruction_preserved(self, client):
        """The whole point of the 6F swap is that the dot panel
        already carries the action verb ("Add N more items to unlock
        the AI planner."). If the panel copy disappears too, we'd
        have made the empty state LESS informative, not more. Two
        strings was redundant; zero would be a regression."""
        sign_up(client, "fresh@example.com", "Fresh")
        html = _pantry_body(client)
        assert DOT_PANEL_INSTRUCTION_PREFIX in html, (
            f"Dot-progress panel must still tell the user what to do "
            f"('… {DOT_PANEL_INSTRUCTION_PREFIX} …'). 6F removes the "
            f"redundant H2 subcopy; the panel is the sole action "
            f"instruction now, so it can't also go missing."
        )


# ---------------------------------------------------------------------------
# 2. Un-locked pantry — subcopy swaps to the AI-prompt framing
# ---------------------------------------------------------------------------

class TestUnlockedPantrySubcopy:
    def test_new_locked_subcopy_absent_once_unlocked(self, client):
        """Once `pantry_item_count >= onboarding_threshold`, the
        planner form takes over the section and the locked-state
        subcopy is out of place. The template's `onboarding_active`
        gate already handles the branch — this test locks it in."""
        sign_up(client, "fresh@example.com", "Fresh")
        _seed(client, PANTRY_ONBOARDING_THRESHOLD)
        html = _pantry_body(client)
        assert NEW_LOCKED_SUBCOPY not in html, (
            f"Un-locked pantry (>= {PANTRY_ONBOARDING_THRESHOLD} items) "
            f"must not show the locked-state subcopy — the planner "
            f"form is live at that point."
        )

    def test_unlocked_subcopy_present(self, client):
        """The un-locked branch's copy is untouched by 6F — this
        assertion mirrors test_phase_5a.test_planner_subcopy_swaps_
        to_full_prompt and guards against a future edit that
        accidentally deletes the un-locked branch alongside the
        old redundant one."""
        sign_up(client, "fresh@example.com", "Fresh")
        _seed(client, PANTRY_ONBOARDING_THRESHOLD)
        html = _pantry_body(client)
        assert UNLOCKED_SUBCOPY_PREFIX in html


# ---------------------------------------------------------------------------
# 3. Threshold boundary — swap happens exactly at the gate
# ---------------------------------------------------------------------------

class TestSubcopyAtThresholdBoundary:
    def test_locked_at_one_below_threshold(self, client):
        """One item shy of the threshold — still gated, so still
        the locked-state subcopy. Guards the off-by-one that
        typically bites this kind of gate."""
        sign_up(client, "fresh@example.com", "Fresh")
        _seed(client, PANTRY_ONBOARDING_THRESHOLD - 1)
        html = _pantry_body(client)
        assert NEW_LOCKED_SUBCOPY in html, (
            f"At {PANTRY_ONBOARDING_THRESHOLD - 1} items (one below "
            f"threshold {PANTRY_ONBOARDING_THRESHOLD}), the planner "
            f"is still gated — locked-state subcopy must show."
        )
        assert UNLOCKED_SUBCOPY_PREFIX not in html

    def test_unlocked_exactly_at_threshold(self, client):
        """At the threshold — subcopy flips. This is the transition
        the whole 5A gate is engineered around; 6F just re-uses the
        same `onboarding_active` conditional, so if this test starts
        failing something bigger than 6F has moved."""
        sign_up(client, "fresh@example.com", "Fresh")
        _seed(client, PANTRY_ONBOARDING_THRESHOLD)
        html = _pantry_body(client)
        assert UNLOCKED_SUBCOPY_PREFIX in html
        assert NEW_LOCKED_SUBCOPY not in html
