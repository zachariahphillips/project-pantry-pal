"""
Phase 3A regression suite — AI meal planning.

We test the routes + DB write path + UI rendering, but we DO NOT call
the real OpenAI API. Instead each test monkeypatches `app._ask_openai_for_meal`
to return a canned dict. This means:

- Tests run offline (CI doesn't need an API key)
- Tests are deterministic (no flakes from model variation)
- The OpenAI SDK shape (which changes across versions) isn't part of
  the test surface — only our contract with it is

The OpenAI plumbing inside `_ask_openai_for_meal` is exercised by a
separate manual smoke test (`scripts/prod_smoke.py` does NOT call it
either, since it'd cost real money and require a key).
"""
from __future__ import annotations

import html
import json

import pytest

from tests.conftest import sign_up


# A canned meal plan that looks like what GPT-4o-mini would return for
# "pasta carbonara" against a pantry of [Pasta, Olive oil, Eggs].
CANNED_PLAN = {
    "meal_name": "Spaghetti carbonara",
    "have": ["Pasta", "Eggs", "Olive oil"],
    "need": ["Pancetta", "Parmesan cheese", "Black pepper"],
    "steps": [
        "Boil a large pot of salted water for the pasta.",
        "Crisp the pancetta in a pan with a little olive oil.",
        "Beat eggs and grated parmesan in a bowl.",
        "Cook the pasta, drain (reserving some water), and toss with pancetta.",
        "Off the heat, stir in the egg mixture and a splash of pasta water.",
        "Top with extra parmesan and lots of black pepper.",
    ],
}


def _body(resp) -> str:
    """Return response body with HTML entities decoded (Jinja autoescape
    turns `'` into `&#39;` etc — we want to assert against the visible
    text, not the encoded form). Mirrors the helper in test_phase_2b."""
    return html.unescape(resp.get_data(as_text=True))


def _seed_pantry(client, items: list[tuple[str, float | None, str | None]]):
    """Add a few pantry items so the meal-plan call has something to
    work with. Returns the response so callers can chain."""
    for name, qty, unit in items:
        data = {"name": name}
        if qty is not None:
            data["quantity"] = str(qty)
        if unit:
            data["unit"] = unit
        client.post("/pantry", data=data, htmx=True)


def _stub_openai(monkeypatch, return_value):
    """Patch `app._ask_openai_for_meal` to return `return_value`.

    Phase 3C: the helper now returns a `(plan_dict | None, error_kind | None)`
    tuple. To keep existing 3A/3B tests untouched, this wrapper auto-
    converts shorthand inputs to the new shape:

    - A dict          → `(dict, None)`   (success)
    - None            → `(None, "unknown")`  (generic failure)
    - A 2-tuple       → passed through unchanged (new 3C tests use this
                        to simulate specific failure kinds)
    - A callable      → wrapped: its return value is run through the
                        same shorthand-conversion logic above

    This lets a 3C test do `_stub_openai(m, (None, "rate_limit"))` to
    simulate a 429, while every dict-returning 3A/3B test keeps working.
    """
    def _wrap(value):
        if isinstance(value, tuple):
            return value
        if value is None:
            return (None, "unknown")
        return (value, None)

    if callable(return_value):
        def wrapped(prompt, pantry):
            return _wrap(return_value(prompt, pantry))
        monkeypatch.setattr("app._ask_openai_for_meal", wrapped)
    else:
        wrapped_value = _wrap(return_value)
        monkeypatch.setattr(
            "app._ask_openai_for_meal",
            lambda prompt, pantry: wrapped_value,
        )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

class TestMealPlanCreate:
    def test_post_meal_plan_stores_row_and_renders_card(
            self, client, app, monkeypatch):
        sign_up(client, "alice@example.com", "Alice")
        _seed_pantry(client, [("Pasta", 1, "lb"), ("Eggs", 6, "ea")])
        _stub_openai(monkeypatch, CANNED_PLAN)

        resp = client.post(
            "/meal-plan",
            data={"prompt": "pasta carbonara"},
            htmx=True,
        )
        assert resp.status_code == 200
        body = _body(resp)

        # Card renders meal_name + each section
        assert "Spaghetti carbonara" in body
        assert "Pasta" in body  # in 'have'
        assert "Pancetta" in body  # in 'need'
        assert "Boil a large pot" in body  # first step

        # DB row landed in the right household with the right provenance
        with app.app_context():
            from models import MealPlan, User
            user = User.query.filter_by(email="alice@example.com").one()
            plan = MealPlan.query.filter_by(
                household_id=user.household_id).one()
            assert plan.meal_name == "Spaghetti carbonara"
            assert plan.created_by_user_id == user.id
            assert plan.prompt == "pasta carbonara"
            # Round-trip the stored JSON
            assert json.loads(plan.response_json) == CANNED_PLAN
            # Property accessors
            assert plan.have == CANNED_PLAN["have"]
            assert plan.need == CANNED_PLAN["need"]
            assert len(plan.steps) == 6

    def test_pantry_snapshot_passed_to_helper(
            self, client, app, monkeypatch):
        """The helper receives the household's pantry items list (so it
        can build the system prompt with real pantry context)."""
        captured = {}

        def fake(prompt, pantry):
            captured["prompt"] = prompt
            captured["pantry_names"] = [p.name for p in pantry]
            return CANNED_PLAN

        sign_up(client, "bob@example.com", "Bob")
        _seed_pantry(client, [
            ("Rice", 2, "cup"),
            ("Soy sauce", None, None),
            ("Tofu", 1, "block"),
        ])
        _stub_openai(monkeypatch, fake)

        client.post("/meal-plan", data={"prompt": "stir fry"}, htmx=True)
        assert captured["prompt"] == "stir fry"
        assert set(captured["pantry_names"]) == {"Rice", "Soy sauce", "Tofu"}

    def test_latest_meal_plan_renders_on_pantry_get(
            self, client, app, monkeypatch):
        sign_up(client, "carla@example.com", "Carla")
        _seed_pantry(client, [("Pasta", 1, "lb")])
        _stub_openai(monkeypatch, CANNED_PLAN)
        client.post("/meal-plan", data={"prompt": "pasta night"}, htmx=True)

        # Fresh GET should show the plan inline (not just after htmx swap)
        resp = client.get("/pantry")
        body = _body(resp)
        assert "Spaghetti carbonara" in body, (
            "GET /pantry should re-render the latest meal plan inline so "
            "users coming back to the page see their last suggestion."
        )


# ---------------------------------------------------------------------------
# Validation + error states
# ---------------------------------------------------------------------------

class TestMealPlanErrors:
    def test_empty_prompt_returns_422(self, client, app, monkeypatch):
        sign_up(client, "d@example.com", "D")
        _stub_openai(monkeypatch, CANNED_PLAN)
        resp = client.post("/meal-plan", data={"prompt": ""}, htmx=True)
        assert resp.status_code == 422
        assert "Tell me what you want to make" in _body(resp)

    def test_whitespace_only_prompt_returns_422(
            self, client, app, monkeypatch):
        sign_up(client, "e@example.com", "E")
        _stub_openai(monkeypatch, CANNED_PLAN)
        resp = client.post("/meal-plan", data={"prompt": "   "}, htmx=True)
        assert resp.status_code == 422

    def test_overlong_prompt_returns_422(self, client, app, monkeypatch):
        sign_up(client, "f@example.com", "F")
        _stub_openai(monkeypatch, CANNED_PLAN)
        resp = client.post(
            "/meal-plan",
            data={"prompt": "x" * 241},  # 240 is the cap
            htmx=True,
        )
        assert resp.status_code == 422

    def test_openai_failure_returns_502_with_friendly_message(
            self, client, app, monkeypatch):
        """Helper returning None (key missing, network error, etc.)
        surfaces a friendly 502 to the user, NOT a stack trace."""
        sign_up(client, "g@example.com", "G")
        _stub_openai(monkeypatch, None)  # helper says "I couldn't"

        resp = client.post(
            "/meal-plan", data={"prompt": "anything"}, htmx=True,
        )
        assert resp.status_code == 502
        body = _body(resp)
        assert "AI is taking a nap" in body
        # And critically: NO MealPlan row should be stored on failure
        with app.app_context():
            from models import MealPlan
            assert MealPlan.query.count() == 0

    def test_anonymous_post_to_meal_plan_redirects_to_login(self, client):
        resp = client.post("/meal-plan", data={"prompt": "anything"})
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]


# ---------------------------------------------------------------------------
# Need → shopping cross-link
# ---------------------------------------------------------------------------

class TestNeedToShopping:
    def _make_plan(self, client, app, monkeypatch):
        """Helper: sign up, create a plan, return (plan_id, body_of_create_response)."""
        sign_up(client, "alice@example.com", "Alice")
        _seed_pantry(client, [("Pasta", 1, "lb")])
        _stub_openai(monkeypatch, CANNED_PLAN)
        resp = client.post(
            "/meal-plan", data={"prompt": "pasta carbonara"}, htmx=True,
        )
        with app.app_context():
            from models import MealPlan
            plan = MealPlan.query.one()
            return plan.id, resp

    def test_tap_need_item_adds_to_shopping_with_hx_trigger(
            self, client, app, monkeypatch):
        plan_id, _ = self._make_plan(client, app, monkeypatch)

        resp = client.post(
            f"/meal-plan/{plan_id}/need-to-shopping",
            data={"name": "Pancetta"},
            htmx=True,
        )
        assert resp.status_code == 200
        assert resp.headers.get("HX-Trigger") == "shopping:added", (
            "Existing toast hook in base.html listens for shopping:added; "
            "without this header the user sees no confirmation."
        )

        # Verify DB row landed with provenance + notes
        with app.app_context():
            from models import ShoppingItem
            items = ShoppingItem.query.all()
            assert len(items) == 1
            assert items[0].name == "Pancetta"
            assert "Spaghetti carbonara" in items[0].notes
            assert items[0].notes.startswith("Suggested by AI for:")

    def test_tap_need_item_appears_on_shopping_page(
            self, client, app, monkeypatch):
        plan_id, _ = self._make_plan(client, app, monkeypatch)
        client.post(
            f"/meal-plan/{plan_id}/need-to-shopping",
            data={"name": "Parmesan cheese"},
            htmx=True,
        )
        resp = client.get("/shopping")
        body = _body(resp)
        assert "Parmesan cheese" in body

    def test_unknown_item_name_returns_400(
            self, client, app, monkeypatch):
        """Can't use this endpoint to add arbitrary items to shopping —
        only items that are in the plan's `need` list."""
        plan_id, _ = self._make_plan(client, app, monkeypatch)
        resp = client.post(
            f"/meal-plan/{plan_id}/need-to-shopping",
            data={"name": "Caviar"},  # not in the plan
            htmx=True,
        )
        assert resp.status_code == 400

    def test_empty_name_returns_400(self, client, app, monkeypatch):
        plan_id, _ = self._make_plan(client, app, monkeypatch)
        resp = client.post(
            f"/meal-plan/{plan_id}/need-to-shopping",
            data={"name": ""},
            htmx=True,
        )
        assert resp.status_code == 400

    def test_unknown_plan_id_returns_404(self, client, app, monkeypatch):
        sign_up(client, "h@example.com", "H")
        resp = client.post(
            "/meal-plan/99999/need-to-shopping",
            data={"name": "Anything"},
            htmx=True,
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Household isolation
# ---------------------------------------------------------------------------

class TestHouseholdIsolation:
    def test_bob_cant_see_alices_meal_plan(
            self, two_clients, app, monkeypatch):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")

        _seed_pantry(alice, [("Pasta", 1, "lb")])
        _stub_openai(monkeypatch, CANNED_PLAN)
        alice.post(
            "/meal-plan", data={"prompt": "pasta carbonara"}, htmx=True,
        )

        # Bob hits /pantry — should NOT see alice's plan
        resp = bob.get("/pantry")
        body = _body(resp)
        assert "Spaghetti carbonara" not in body
        # Empty-state slot OK (the section header is visible to bob)
        assert "Plan a meal" in body

    def test_bob_cant_add_alices_need_item_to_shopping(
            self, two_clients, app, monkeypatch):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")

        _seed_pantry(alice, [("Pasta", 1, "lb")])
        _stub_openai(monkeypatch, CANNED_PLAN)
        alice.post(
            "/meal-plan", data={"prompt": "pasta carbonara"}, htmx=True,
        )
        with app.app_context():
            from models import MealPlan
            alices_plan_id = MealPlan.query.one().id

        # Bob tries to add an item from alice's plan to HIS shopping list
        resp = bob.post(
            f"/meal-plan/{alices_plan_id}/need-to-shopping",
            data={"name": "Pancetta"},
            htmx=True,
        )
        # 404 not 403 — don't leak the existence of cross-household plans
        assert resp.status_code == 404

        with app.app_context():
            from models import ShoppingItem
            assert ShoppingItem.query.count() == 0

    def test_shared_household_members_see_same_plan(
            self, app, monkeypatch):
        """Once bob joins alice's household via an invite, he should see
        her meal plan inline on /pantry (and vice versa). This is the
        whole point of household-scoped storage."""
        from tests.conftest import Client
        from models import Household, Invite, User

        # Boot two independent clients on the same app
        alice_c = Client(app.test_client())
        bob_c = Client(app.test_client())
        sign_up(alice_c, "alice@example.com", "Alice")
        sign_up(bob_c, "bob@example.com", "Bob")

        # Alice generates a plan
        _seed_pantry(alice_c, [("Pasta", 1, "lb")])
        _stub_openai(monkeypatch, CANNED_PLAN)
        alice_c.post(
            "/meal-plan", data={"prompt": "pasta carbonara"}, htmx=True,
        )

        # Direct DB stitch: move bob into alice's household (the Phase 2B
        # invite UI exists but the test bypasses it for brevity — Phase
        # 2B tests already cover that flow end-to-end).
        with app.app_context():
            from extensions import db
            alice = User.query.filter_by(email="alice@example.com").one()
            bob = User.query.filter_by(email="bob@example.com").one()
            bob.household_id = alice.household_id
            db.session.commit()

        # Bob now hits /pantry and SHOULD see alice's plan
        resp = bob_c.get("/pantry")
        body = _body(resp)
        assert "Spaghetti carbonara" in body
        # And the provenance stamp should call out alice (since it's
        # not bob's own plan).
        assert "Alice" in body, (
            "When a roommate's plan renders, the 'asked by X' stamp "
            "should attribute it to the original asker."
        )


# ---------------------------------------------------------------------------
# Defensive: MealPlan model parsing
# ---------------------------------------------------------------------------

class TestMealPlanModel:
    def test_malformed_json_falls_back_to_empty(self, app):
        """If the DB ever contains malformed JSON (corrupted, migrated
        wrong, etc.), the model accessors should return [] rather than
        crashing the template render."""
        with app.app_context():
            from extensions import db
            from models import Household, MealPlan, User

            hh = Household(name="Test")
            db.session.add(hh)
            db.session.flush()
            user = User(email="x@example.com", name="X", household_id=hh.id)
            user.set_password("testpass1")
            db.session.add(user)
            db.session.commit()

            mp = MealPlan(
                household_id=hh.id,
                created_by_user_id=user.id,
                prompt="test",
                response_json="not json at all { malformed",
                meal_name="Test",
            )
            assert mp.parsed == {}
            assert mp.have == []
            assert mp.need == []
            assert mp.steps == []

    def test_list_caps_enforce_upper_bound(self, app):
        """A model returning 500 'steps' shouldn't blow up the rendered
        card. The properties cap at MEAL_PLAN_MAX_STEPS."""
        with app.app_context():
            from extensions import db
            from models import (
                Household, MealPlan, User,
                MEAL_PLAN_MAX_STEPS,
            )

            hh = Household(name="Test")
            db.session.add(hh)
            db.session.flush()
            user = User(email="y@example.com", name="Y", household_id=hh.id)
            user.set_password("testpass1")
            db.session.add(user)
            db.session.commit()

            huge = {"meal_name": "X", "steps": [f"step {i}" for i in range(500)]}
            mp = MealPlan(
                household_id=hh.id,
                created_by_user_id=user.id,
                prompt="test",
                response_json=json.dumps(huge),
                meal_name="X",
            )
            assert len(mp.steps) == MEAL_PLAN_MAX_STEPS
