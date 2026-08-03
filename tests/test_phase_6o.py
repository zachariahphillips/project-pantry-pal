"""
Phase 6O regression suite — unlocked empty-meals CTA.

Companion to Phase 6N from `PLANS/ux-improvements-plan.md` §1.4. 6N
fixed the locked/fresh-household branch so /meals says `Stock your pantry
first →` when /pantry would still show the planner gate. 6O pins the
other side of that conditional: once the pantry has enough items to unlock
the planner, the empty Meals CTA should still say `Plan a meal`.

Tier-1 dev loop:

    pytest tests/test_phase_6o.py -q
"""
from __future__ import annotations

import re

from app import PANTRY_ONBOARDING_THRESHOLD
from tests.conftest import Client, sign_up


def _body(resp) -> str:
    return resp.get_data(as_text=True)


def _seed_pantry_direct(app, email: str, count: int) -> None:
    with app.app_context():
        from extensions import db
        from models import PantryItem, User

        user = User.query.filter_by(email=email).one()
        for i in range(count):
            db.session.add(PantryItem(
                household_id=user.household_id,
                added_by_user_id=user.id,
                name=f"Item {i}",
            ))
        db.session.commit()


def _assert_plan_meal_cta(body: str) -> None:
    assert "No meal plans yet" in body
    assert "Plan a meal" in body
    assert re.search(
        r'<a href="/pantry"[^>]*>\s*Plan a meal\s*</a>',
        body,
        re.DOTALL,
    )
    assert "Stock your pantry first →" not in body


def test_empty_meals_at_threshold_keeps_plan_meal_cta(client: Client, app):
    """Exactly at threshold, /pantry shows the planner, so /meals may promise it."""
    email = "thresholdmeals@example.com"
    sign_up(client, email, "Threshold Meals")
    _seed_pantry_direct(app, email, PANTRY_ONBOARDING_THRESHOLD)

    body = _body(client.get("/meals"))

    _assert_plan_meal_cta(body)


def test_empty_meals_above_threshold_keeps_plan_meal_cta(client: Client, app):
    """Above threshold is the common stocked-pantry empty-meals state."""
    email = "stockedmeals@example.com"
    sign_up(client, email, "Stocked Meals")
    _seed_pantry_direct(app, email, PANTRY_ONBOARDING_THRESHOLD + 1)

    body = _body(client.get("/meals"))

    _assert_plan_meal_cta(body)
