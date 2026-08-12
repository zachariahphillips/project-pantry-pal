"""
Phase 6V regression suite — Meals page heading copy.

Small copy-polish chunk from `PLANS/ux-improvements-plan.md` §4.3.
`Meal history` framed the page as an archive; `Your meals` better matches
the value of revisiting ideas the household can cook again.

Tier-1 dev loop:

    pytest tests/test_phase_6v.py -q
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


def test_meals_page_uses_warmer_heading(client: Client):
    sign_up(client, "meals-heading@example.com", "Meals Heading")

    body = _body(client.get("/meals"))

    assert re.search(r"<h1[^>]*>\s*Your meals\s*</h1>", body)
    assert "Meal history" not in body


def test_locked_empty_meals_cta_is_unchanged(client: Client):
    sign_up(client, "meals-locked-heading@example.com", "Meals Locked")

    body = _body(client.get("/meals"))

    assert "No meal plans yet" in body
    assert "Stock your pantry first →" in body
    assert not re.search(
        r'<a href="/pantry"[^>]*>\s*Plan a meal\s*</a>',
        body,
        re.DOTALL,
    )


def test_unlocked_empty_meals_cta_is_unchanged(client: Client, app):
    email = "meals-unlocked-heading@example.com"
    sign_up(client, email, "Meals Unlocked")
    _seed_pantry_direct(app, email, PANTRY_ONBOARDING_THRESHOLD)

    body = _body(client.get("/meals"))

    assert "No meal plans yet" in body
    assert re.search(
        r'<a href="/pantry"[^>]*>\s*Plan a meal\s*</a>',
        body,
        re.DOTALL,
    )
    assert "Stock your pantry first →" not in body
