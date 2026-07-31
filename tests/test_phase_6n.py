"""
Phase 6N regression suite — locked empty-meals CTA.

Small UX correctness chunk from `PLANS/ux-improvements-plan.md` §1.4.
Before 6N, a fresh household with no meal plans saw a `Plan a meal` CTA
on /meals even though /pantry would still show the meal-planner onboarding
gate. The link was technically correct, but the label promised an action
the next page could not yet complete.

6N fixes only the locked branch: below the pantry onboarding threshold,
the empty Meals CTA says `Stock your pantry first →`. Phase 6O pins the
unlocked branch separately.

Tier-1 dev loop:

    pytest tests/test_phase_6n.py -q
"""
from __future__ import annotations

import re

from tests.conftest import Client, sign_up


def _body(resp) -> str:
    return resp.get_data(as_text=True)


def test_empty_meals_locked_state_points_to_stocking_pantry(client: Client):
    """Fresh households need pantry items before they can plan meals."""
    sign_up(client, "lockedmeals@example.com", "Locked Meals")

    body = _body(client.get("/meals"))

    assert "No meal plans yet" in body
    assert "Stock your pantry first →" in body
    assert re.search(
        r'<a href="/pantry"[^>]*>\s*Stock your pantry first →\s*</a>',
        body,
        re.DOTALL,
    )


def test_empty_meals_locked_state_does_not_show_plan_meal_cta(
        client: Client):
    """The misleading locked-state CTA label is retired."""
    sign_up(client, "lockedcopy@example.com", "Locked Copy")

    body = _body(client.get("/meals"))

    assert not re.search(
        r'<a href="/pantry"[^>]*>\s*Plan a meal\s*</a>',
        body,
        re.DOTALL,
    )
