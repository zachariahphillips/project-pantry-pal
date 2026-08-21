"""
Phase 7D regression suite — quota-zero Ask AI disable.

When `/cost` reports zero daily AI calls remaining, the pantry page should
proactively disable the rendered Ask AI control and explain the reset
instead of letting the user wait for a server-side 429.

Tier-1 dev loop:

    pytest tests/test_phase_7d.py -q
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


def _assert_quota_disable_script(html: str) -> None:
    assert "function setPlannerQuotaState(remaining)" in html
    assert "document.querySelectorAll('[data-meal-plan-submit]')" in html
    assert "document.querySelectorAll('[data-meal-plan-prompt]')" in html
    assert "btn.disabled = limitHit" in html
    assert "btn.setAttribute('aria-disabled'" in html
    assert "input.setAttribute('placeholder', 'Daily AI limit reached')" in html
    assert "quotaHint.classList.toggle('hidden', !limitHit)" in html
    assert "setPlannerQuotaState(remaining)" in html


def _assert_planner_quota_hooks(region: str, visible_label: str) -> None:
    assert "data-meal-plan-prompt" in region
    button = _submit_button(region, visible_label)
    assert "data-meal-plan-submit" in button
    assert 'hx-disabled-elt="this"' in button


def test_first_run_planner_has_quota_zero_disable_hooks(
        client: Client, app):
    email = "quota-zero-full@example.com"
    sign_up(client, email, "Quota Zero Full")
    _seed_pantry_direct(app, email, PANTRY_ONBOARDING_THRESHOLD)

    html = _body(client.get("/pantry"))
    region = _planner_region(html, "meal-plan-prompt-card")

    assert 'id="meal-plan-quota-empty-hint"' in html
    assert "Daily AI limit reached. Try again after midnight UTC." in html
    _assert_planner_quota_hooks(region, "Ask AI")
    _assert_quota_disable_script(html)


def test_compact_planner_has_quota_zero_disable_hooks(client: Client, app):
    email = "quota-zero-compact@example.com"
    sign_up(client, email, "Quota Zero Compact")
    _seed_pantry_direct(app, email, PANTRY_ONBOARDING_THRESHOLD)
    _insert_meal_plan(app, email)

    html = _body(client.get("/pantry"))
    region = _planner_region(html, "meal-plan-compact-card")

    assert 'id="meal-plan-quota-empty-hint"' in html
    _assert_planner_quota_hooks(region, "Ask")
    _assert_quota_disable_script(html)
