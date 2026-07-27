"""
Phase 6I regression suite — primary button press feedback.

Small interaction chunk from `PLANS/ux-improvements-plan.md` §3.1.
Before 6I, filled green primary buttons had hover/focus states but no
mobile tap feedback. On phones there is no hover, so a tap could feel
dead until the htmx response arrived.

6I adds the same small press affordance to filled green action controls:
`transition active:scale-[0.98] active:bg-green-800`. These tests render
representative pages/partials and assert the active-state classes appear
on primary controls without broadening the assertion to decorative green
elements like the header logo or pantry progress dots.

Tier-1 dev loop:

    pytest tests/test_phase_6i.py -q
"""
from __future__ import annotations

import json

from tests.conftest import Client, sign_up


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _body(resp) -> str:
    return resp.get_data(as_text=True)


def _opening_tag_before(html: str, marker: str) -> str:
    """Return the nearest button/link opening tag before visible text.

    Most target controls are easiest to identify by their visible label
    ("Ask AI", "Save", "+ Shop all"). We only assert on the opening tag
    so unrelated child markup can't produce false positives.
    """
    marker_idx = html.index(marker)
    candidates = [
        html.rfind("<button", 0, marker_idx),
        html.rfind("<a ", 0, marker_idx),
    ]
    start = max(candidates)
    assert start != -1, f"no button/link before marker {marker!r}"
    end = html.index(">", start) + 1
    return html[start:end]


def _opening_tag_containing(html: str, marker: str) -> str:
    """Return the opening button/link tag containing a stable attribute."""
    marker_idx = html.index(marker)
    candidates = [
        html.rfind("<button", 0, marker_idx),
        html.rfind("<a ", 0, marker_idx),
    ]
    start = max(candidates)
    assert start != -1, f"no button/link containing marker {marker!r}"
    end = html.index(">", marker_idx) + 1
    return html[start:end]


def _assert_press_feedback(tag: str) -> None:
    assert "bg-green-600" in tag
    assert "transition" in tag
    assert "active:scale-[0.98]" in tag
    assert "active:bg-green-800" in tag


def _add_pantry_item_direct(
        app, email: str, name: str = "Olive oil") -> int:
    with app.app_context():
        from extensions import db
        from models import PantryItem, User

        user = User.query.filter_by(email=email).one()
        item = PantryItem(
            household_id=user.household_id,
            added_by_user_id=user.id,
            name=name,
        )
        db.session.add(item)
        db.session.commit()
        return item.id


def _add_shopping_item_direct(
        app, email: str, name: str = "Milk") -> int:
    with app.app_context():
        from extensions import db
        from models import ShoppingItem, User

        user = User.query.filter_by(email=email).one()
        item = ShoppingItem(
            household_id=user.household_id,
            added_by_user_id=user.id,
            name=name,
        )
        db.session.add(item)
        db.session.commit()
        return item.id


def _insert_meal_plan(app, email: str) -> int:
    with app.app_context():
        from extensions import db
        from models import MealPlan, User

        user = User.query.filter_by(email=email).one()
        plan_json = {
            "meal_name": "Pasta night",
            "have": ["Pasta"],
            "need": ["Parmesan", "Black pepper"],
            "steps": ["Boil pasta"],
        }
        plan = MealPlan(
            household_id=user.household_id,
            created_by_user_id=user.id,
            prompt="pasta",
            meal_name=plan_json["meal_name"],
            response_json=json.dumps(plan_json),
        )
        db.session.add(plan)
        db.session.commit()
        return plan.id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_main_page_primary_buttons_have_press_feedback(client: Client, app):
    """Ask AI, pantry submit, shopping quick-add, and meals CTA all feel tapped."""
    sign_up(client, "main-buttons@example.com", "Main")
    for name in ("Pasta", "Eggs", "Olive oil"):
        _add_pantry_item_direct(app, "main-buttons@example.com", name)

    pantry = _body(client.get("/pantry"))
    _assert_press_feedback(_opening_tag_before(pantry, "Ask AI"))
    _assert_press_feedback(_opening_tag_before(pantry, "Add to pantry"))

    shopping = _body(client.get("/shopping"))
    _assert_press_feedback(
        _opening_tag_containing(shopping, 'aria-label="Add to shopping list"')
    )

    meals = _body(client.get("/meals"))
    _assert_press_feedback(_opening_tag_before(meals, "Plan a meal"))


def test_partial_primary_buttons_have_press_feedback(client: Client, app):
    """Edit Save, +Shop all, and I'm-home primary actions get the same treatment."""
    sign_up(client, "partials@example.com", "Partial")
    pantry_id = _add_pantry_item_direct(app, "partials@example.com", "Rice")
    shopping_id = _add_shopping_item_direct(app, "partials@example.com", "Milk")
    _insert_meal_plan(app, "partials@example.com")

    pantry_edit = _body(client.get(f"/pantry/{pantry_id}/edit", htmx=True))
    _assert_press_feedback(_opening_tag_before(pantry_edit, "Save"))

    shopping_edit = _body(client.get(f"/shopping/{shopping_id}/edit", htmx=True))
    _assert_press_feedback(_opening_tag_before(shopping_edit, "Save"))

    meals = _body(client.get("/meals"))
    _assert_press_feedback(_opening_tag_before(meals, "+ Shop all"))

    client.post(f"/shopping/{shopping_id}/toggle", htmx=True)
    shopping = _body(client.get("/shopping"))
    _assert_press_feedback(_opening_tag_containing(
        shopping, "aria-label=\"I'm home"
    ))


def test_confirmation_and_household_primary_buttons_have_press_feedback(
        client: Client, app):
    """Green merge/invite actions are primary too; neutral options stay out of scope."""
    sign_up(client, "confirm@example.com", "Confirm")
    _add_pantry_item_direct(app, "confirm@example.com", "Rice")
    _add_shopping_item_direct(app, "confirm@example.com", "Milk")

    pantry_dupe = _body(client.post("/pantry", htmx=True, data={
        "name": "Rice", "quantity": "", "unit": "", "notes": "",
        "submit": "Add",
    }))
    _assert_press_feedback(
        _opening_tag_containing(pantry_dupe, 'data-testid="dupe-confirm-merge"')
    )

    shopping_dupe = _body(client.post("/shopping", htmx=True, data={
        "name": "Milk", "quantity": "", "unit": "", "notes": "",
        "submit": "Add",
    }))
    _assert_press_feedback(_opening_tag_containing(
        shopping_dupe, 'data-testid="shopping-dupe-confirm-merge"'
    ))

    pantry = _body(client.get("/pantry"))
    _assert_press_feedback(_opening_tag_before(pantry, "+ Invite"))


def test_auth_join_primary_buttons_have_press_feedback(client: Client, app):
    """Account and join flows also use the filled green primary style."""
    signup = _body(client.get("/signup"))
    _assert_press_feedback(_opening_tag_containing(signup, 'type="submit"'))

    login = _body(client.get("/login"))
    _assert_press_feedback(_opening_tag_containing(login, 'type="submit"'))

    sign_up(client, "joiner@example.com", "Joiner")
    _add_pantry_item_direct(app, "joiner@example.com", "Beans")
    resp = client.post("/household/invite", htmx=True)
    invite_html = _body(resp)
    token_marker = "/join/"
    assert token_marker in invite_html
    token = invite_html.split(token_marker, 1)[1].split('"', 1)[0]

    already_member = _body(client.get(f"/join/{token}"))
    _assert_press_feedback(_opening_tag_before(already_member, "Open pantry"))
