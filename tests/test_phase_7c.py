"""
Phase 7C regression suite — Ask AI in-flight disable.

The meal-plan POST can take a few seconds. While htmx is waiting, both
planner submit buttons should disable themselves so a double tap doesn't
fire a second OpenAI request or spend another daily quota slot.

Tier-1 dev loop:

    pytest tests/test_phase_7c.py -q
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


def _planner_region(html: str, region_id: str) -> str:
    start = html.find(f'id="{region_id}"')
    assert start != -1, f"{region_id} not found"
    end = html.find('id="meal-plan-spinner"', start)
    assert end != -1, "spinner marker after planner region not found"
    return html[start:end]


def _submit_button(region: str, visible_label: str) -> str:
    match = re.search(
        rf'<button type="submit"[^>]*>\s*{re.escape(visible_label)}\s*</button>',
        region,
        re.DOTALL,
    )
    assert match, f"{visible_label} submit button not found"
    return match.group(0)


def _assert_button_disables_in_flight(button: str) -> None:
    assert 'hx-disabled-elt="this"' in button
    assert "disabled:cursor-progress" in button
    assert "disabled:animate-pulse" in button
    assert "disabled:opacity-70" in button


def test_first_run_ask_ai_button_disables_during_request(
        client: Client, app):
    email = "ask-ai-disable-full@example.com"
    sign_up(client, email, "Ask Disable Full")
    _seed_pantry_direct(app, email, PANTRY_ONBOARDING_THRESHOLD)

    region = _planner_region(_body(client.get("/pantry")), "meal-plan-prompt-card")
    button = _submit_button(region, "Ask AI")

    _assert_button_disables_in_flight(button)


def test_compact_ask_button_disables_during_request(client: Client, app):
    email = "ask-ai-disable-compact@example.com"
    sign_up(client, email, "Ask Disable Compact")
    _seed_pantry_direct(app, email, PANTRY_ONBOARDING_THRESHOLD)
    _insert_meal_plan(app, email)

    region = _planner_region(_body(client.get("/pantry")), "meal-plan-compact-card")
    button = _submit_button(region, "Ask")

    assert 'aria-label="Ask AI for another meal"' in button
    _assert_button_disables_in_flight(button)
