"""
Phase 6X-A regression suite — compact return-visit planner state.

First micro-phase of `PLANS/ux-improvements-plan.md` §5.1. Once a
household has meal-plan history, the live planner should stop taking the
same visual space as the first-run planner. 6X-A introduces a compact
return-visit card while preserving the full first-run prompt card.

Tier-1 dev loop:

    pytest tests/test_phase_6xa.py -q
"""
from __future__ import annotations

import json

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
                name=f"Pantry item {i}",
            ))
        db.session.commit()


def _insert_meal_plan(app, email: str) -> None:
    with app.app_context():
        from extensions import db
        from models import MealPlan, User

        user = User.query.filter_by(email=email).one()
        db.session.add(MealPlan(
            household_id=user.household_id,
            created_by_user_id=user.id,
            prompt="quick dinner",
            meal_name="Lemon pasta",
            response_json=json.dumps({
                "meal_name": "Lemon pasta",
                "have": ["pasta"],
                "need": ["lemons"],
                "steps": ["Boil pasta.", "Add lemon."],
            }),
        ))
        db.session.commit()


def _compact_card_region(html: str) -> str:
    start = html.find('id="meal-plan-compact-card"')
    assert start != -1, "compact meal-plan card not found"
    end = html.find('id="meal-plan-spinner"', start)
    assert end != -1, "spinner marker after compact card not found"
    return html[start:end]


def test_locked_household_renders_no_live_planner_card(client: Client):
    sign_up(client, "compact-locked@example.com", "Compact Locked")

    body = _body(client.get("/pantry"))

    assert 'id="meal-plan-onboarding-gate"' in body
    assert 'id="meal-plan-prompt-card"' not in body
    assert 'id="meal-plan-compact-card"' not in body


def test_just_unlocked_without_plans_keeps_full_prompt_card(client: Client, app):
    email = "compact-first-run@example.com"
    sign_up(client, email, "Compact First")
    _seed_pantry_direct(app, email, PANTRY_ONBOARDING_THRESHOLD)

    body = _body(client.get("/pantry"))

    assert 'id="meal-plan-prompt-card"' in body
    assert 'id="nudge-planner"' in body
    assert 'id="meal-plan-compact-card"' not in body


def test_returning_household_uses_compact_planner_card(client: Client, app):
    email = "compact-returning@example.com"
    sign_up(client, email, "Compact Returning")
    _seed_pantry_direct(app, email, PANTRY_ONBOARDING_THRESHOLD)
    _insert_meal_plan(app, email)

    body = _body(client.get("/pantry"))

    assert 'id="meal-plan-compact-card"' in body
    assert 'id="meal-plan-prompt-card"' not in body
    assert 'id="nudge-planner"' not in body
    assert "Last meal" in body
    assert "Lemon pasta" in body


def test_compact_planner_preserves_form_and_chip_wiring(client: Client, app):
    email = "compact-wiring@example.com"
    sign_up(client, email, "Compact Wiring")
    _seed_pantry_direct(app, email, PANTRY_ONBOARDING_THRESHOLD)
    _insert_meal_plan(app, email)

    card = _compact_card_region(_body(client.get("/pantry")))

    assert "Plan another meal" in card
    assert 'hx-post="/meal-plan"' in card
    assert 'hx-target="#meal-plan-result"' in card
    assert 'hx-indicator="#meal-plan-spinner"' in card
    assert 'id="meal-plan-prompt"' in card
    assert "Ask AI" in card
    assert "Prompt ideas" in card
    assert "<details" in card
    assert "<details open" not in card
    assert card.count('data-prompt-chip="') == 5
