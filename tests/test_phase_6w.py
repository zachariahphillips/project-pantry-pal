"""
Phase 6W regression suite — grouped pantry meal-prompt controls.

Small density/hierarchy chunk from `PLANS/ux-improvements-plan.md` §5.2.
The planner prompt chips used to float above the Ask AI form. 6W groups
chips, first-run planner nudge, and the prompt form into one subtle card
so the suggestions read as part of the same composed control.

Tier-1 dev loop:

    pytest tests/test_phase_6w.py -q
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
                name=f"Pantry item {i}",
            ))
        db.session.commit()


def _prompt_card_region(html: str) -> str:
    start = html.find('id="meal-plan-prompt-card"')
    assert start != -1, "meal-plan prompt card not found"
    end = html.find('id="meal-plan-spinner"', start)
    assert end != -1, "spinner marker after prompt card not found"
    return html[start:end]


def test_unlocked_planner_groups_chips_and_form_in_card(client: Client, app):
    email = "prompt-card@example.com"
    sign_up(client, email, "Prompt Card")
    _seed_pantry_direct(app, email, PANTRY_ONBOARDING_THRESHOLD)

    card = _prompt_card_region(_body(client.get("/pantry")))

    for cls in (
        "rounded-2xl",
        "border",
        "border-stone-200",
        "bg-white",
        "p-3",
        "shadow-sm",
    ):
        assert cls in card


def test_prompt_card_preserves_chip_and_form_wiring(client: Client, app):
    email = "prompt-card-wiring@example.com"
    sign_up(client, email, "Prompt Card Wiring")
    _seed_pantry_direct(app, email, PANTRY_ONBOARDING_THRESHOLD)

    card = _prompt_card_region(_body(client.get("/pantry")))

    assert card.count('data-prompt-chip="') == 5
    assert 'aria-label="Quick prompts"' in card
    assert 'id="meal-plan-prompt"' in card
    assert 'hx-post="/meal-plan"' in card
    assert 'hx-target="#meal-plan-result"' in card
    assert 'hx-indicator="#meal-plan-spinner"' in card
    assert "Ask AI" in card


def test_first_run_planner_nudge_stays_inside_prompt_card(client: Client, app):
    email = "prompt-card-nudge@example.com"
    sign_up(client, email, "Prompt Card Nudge")
    _seed_pantry_direct(app, email, PANTRY_ONBOARDING_THRESHOLD)

    card = _prompt_card_region(_body(client.get("/pantry")))

    chip_pos = card.find('data-prompt-chip="')
    nudge_pos = card.find('id="nudge-planner"')
    form_pos = card.find('hx-post="/meal-plan"')
    assert chip_pos != -1 and nudge_pos != -1 and form_pos != -1
    assert chip_pos < nudge_pos < form_pos


def test_locked_planner_does_not_render_prompt_card(client: Client):
    sign_up(client, "prompt-card-locked@example.com", "Prompt Card Locked")

    body = _body(client.get("/pantry"))

    assert 'id="meal-plan-onboarding-gate"' in body
    assert 'id="meal-plan-prompt-card"' not in body
    assert 'data-prompt-chip="' not in body
    assert not re.search(r'<form[^>]*hx-post="/meal-plan"', body)
