"""
Phase 6X-B regression suite — tighter compact planner bar copy.

Second micro-phase of `PLANS/ux-improvements-plan.md` §5.1. 6X-A added
the compact return-visit planner. 6X-B makes that compact card read more
like a true mobile bar: the input placeholder carries "Plan another meal"
and the visible submit label shrinks to "Ask" while preserving an
explicit screen-reader label.

Tier-1 dev loop:

    pytest tests/test_phase_6xb.py -q
"""
from __future__ import annotations

import json
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


def _full_prompt_card_region(html: str) -> str:
    start = html.find('id="meal-plan-prompt-card"')
    assert start != -1, "full meal-plan prompt card not found"
    end = html.find('id="meal-plan-spinner"', start)
    assert end != -1, "spinner marker after prompt card not found"
    return html[start:end]


def test_compact_planner_uses_short_visible_submit_label(client: Client, app):
    email = "compact-short-label@example.com"
    sign_up(client, email, "Compact Short")
    _seed_pantry_direct(app, email, PANTRY_ONBOARDING_THRESHOLD)
    _insert_meal_plan(app, email)

    card = _compact_card_region(_body(client.get("/pantry")))

    assert 'placeholder="Plan another meal"' in card
    assert 'aria-label="Ask AI for another meal"' in card
    assert re.search(
        r'<button type="submit"[^>]*>\s*Ask\s*</button>',
        card,
        re.DOTALL,
    )
    assert not re.search(
        r'<button type="submit"[^>]*>\s*Ask AI\s*</button>',
        card,
        re.DOTALL,
    )


def test_full_first_run_planner_keeps_original_ask_ai_copy(client: Client, app):
    email = "full-ask-ai-copy@example.com"
    sign_up(client, email, "Full Ask")
    _seed_pantry_direct(app, email, PANTRY_ONBOARDING_THRESHOLD)

    card = _full_prompt_card_region(_body(client.get("/pantry")))

    assert 'placeholder=\'e.g. "pasta carbonara"\'' in card
    assert re.search(
        r'<button type="submit"[^>]*>\s*Ask AI\s*</button>',
        card,
        re.DOTALL,
    )
    assert 'aria-label="Ask AI for another meal"' not in card
