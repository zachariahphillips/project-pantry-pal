"""
Phase 3B regression suite — meal plan history view + bulk shop-all.

What's covered:
  - GET /meals empty state (fresh household)
  - GET /meals lists every plan, newest first
  - GET /meals respects household isolation
  - GET /meals renders cards collapsed (context="list")
  - GET /pantry renders the inline card expanded (context="inline")
  - "Plan another" footer only on the inline card
  - POST /meal-plan/<id>/need-all-to-shopping bulk-adds with provenance
  - POST /meal-plan/<id>/need-all-to-shopping returns shopping:added-bulk
    HX-Trigger JSON with the count
  - POST /meal-plan/<id>/need-all-to-shopping empty need list → 200, 0 rows
  - POST /meal-plan/<id>/need-all-to-shopping cross-household → 404
  - POST /meal-plan/<id>/need-all-to-shopping anonymous → login redirect
  - Bottom tab bar exposes the new Meals link on every authed page

OpenAI is monkeypatched (no network calls).
"""
from __future__ import annotations

import html
import json
import time

import pytest

from tests.conftest import sign_up


CANNED_PLAN_A = {
    "meal_name": "Spaghetti carbonara",
    "have": ["Pasta", "Eggs"],
    "need": ["Pancetta", "Parmesan", "Black pepper"],
    "steps": ["Boil pasta.", "Crisp pancetta.", "Mix everything."],
}
CANNED_PLAN_B = {
    "meal_name": "Tofu stir fry",
    "have": ["Tofu", "Soy sauce", "Rice"],
    "need": ["Garlic", "Ginger"],
    "steps": ["Press tofu.", "Stir-fry.", "Serve over rice."],
}
CANNED_PLAN_NO_NEED = {
    "meal_name": "Cereal night",
    "have": ["Cereal", "Milk"],
    "need": [],
    "steps": ["Pour cereal.", "Add milk."],
}


def _body(resp) -> str:
    return html.unescape(resp.get_data(as_text=True))


def _stub_openai(monkeypatch, return_value):
    """Patch `app._ask_openai_for_meal`. Phase 3C: helper now returns
    a `(dict | None, error_kind | None)` tuple — this wrapper accepts
    dict / None / tuple / callable and converts to the right shape.
    See test_phase_3a.py for the long-form docstring."""
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


def _make_plan(client, prompt: str = "anything"):
    """POST /meal-plan with the stubbed OpenAI; returns the response."""
    return client.post("/meal-plan", data={"prompt": prompt}, htmx=True)


# ---------------------------------------------------------------------------
# /meals page — list view
# ---------------------------------------------------------------------------

class TestMealsListPage:
    def test_meals_empty_state(self, client, app):
        sign_up(client, "alice@example.com", "Alice")
        resp = client.get("/meals")
        assert resp.status_code == 200
        body = _body(resp)
        assert "No meal plans yet" in body
        # Should link back to /pantry to get to the prompt
        assert 'href="/pantry"' in body

    def test_meals_lists_plans_newest_first(
            self, client, app, monkeypatch):
        sign_up(client, "alice@example.com", "Alice")

        _stub_openai(monkeypatch, CANNED_PLAN_A)
        _make_plan(client, prompt="pasta carbonara")
        # Tiny delay so created_at differs at the microsecond level
        # (avoids order-undefined when two rows land in the same tick).
        time.sleep(0.01)
        _stub_openai(monkeypatch, CANNED_PLAN_B)
        _make_plan(client, prompt="stir fry")

        resp = client.get("/meals")
        body = _body(resp)

        # Both meal names are visible
        assert "Spaghetti carbonara" in body
        assert "Tofu stir fry" in body
        # Newest first: 'Tofu stir fry' appears before 'Spaghetti carbonara'
        assert body.index("Tofu stir fry") < body.index("Spaghetti carbonara"), (
            "GET /meals should list newest plans first."
        )

    def test_meals_household_isolation(
            self, two_clients, app, monkeypatch):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")

        _stub_openai(monkeypatch, CANNED_PLAN_A)
        _make_plan(alice, prompt="alice's idea")

        resp = bob.get("/meals")
        body = _body(resp)
        assert "Spaghetti carbonara" not in body, (
            "Bob's /meals must NOT show Alice's meal plans."
        )
        # Empty state visible for bob
        assert "No meal plans yet" in body

    def test_meals_anonymous_redirects_to_login(self, client):
        resp = client.get("/meals")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_meals_cards_collapsed_by_default(
            self, client, app, monkeypatch):
        """Multiple plans = lots of content. On /meals each card's
        sections start CLOSED so the page stays scrollable."""
        sign_up(client, "alice@example.com", "Alice")
        _stub_openai(monkeypatch, CANNED_PLAN_A)
        _make_plan(client)

        resp = client.get("/meals")
        body = _body(resp)
        # The card uses <details> for have/need/steps. Without `open`,
        # they collapse. We can't reliably grep for "<details>" without
        # matching `<details open>` — so look for both patterns:
        assert "<details " in body or "<details>" in body, (
            "card uses <details> for collapsible sections"
        )
        # And critically, on /meals NO <details open> in the rendered cards
        # (the empty-state branch doesn't have details either, so 0 is
        # the right number here).
        assert body.count("<details open") == 0, (
            "/meals cards should be collapsed; found expanded <details open>"
        )

    def test_meals_no_plan_another_footer(
            self, client, app, monkeypatch):
        """The 'Plan another meal' CTA is only on the inline /pantry
        card (where there's a form to scroll back to)."""
        sign_up(client, "alice@example.com", "Alice")
        _stub_openai(monkeypatch, CANNED_PLAN_A)
        _make_plan(client)

        resp = client.get("/meals")
        assert "Plan another meal" not in _body(resp), (
            "Plan another CTA shouldn't appear on the /meals list."
        )


# ---------------------------------------------------------------------------
# /pantry inline card behavior in 3B (expanded + 'Plan another' footer)
# ---------------------------------------------------------------------------

class TestPantryInlineCard:
    def test_inline_card_starts_expanded(
            self, client, app, monkeypatch):
        sign_up(client, "alice@example.com", "Alice")
        _stub_openai(monkeypatch, CANNED_PLAN_A)
        _make_plan(client)

        resp = client.get("/pantry")
        body = _body(resp)
        # At least one <details open> (have/need/steps all open)
        assert "<details open" in body, (
            "/pantry latest plan should render with sections expanded."
        )

    def test_inline_card_has_plan_another_cta(
            self, client, app, monkeypatch):
        sign_up(client, "alice@example.com", "Alice")
        _stub_openai(monkeypatch, CANNED_PLAN_A)
        resp = _make_plan(client)
        body = _body(resp)
        assert "Plan another meal" in body, (
            "POST /meal-plan response should include the Plan another CTA."
        )


# ---------------------------------------------------------------------------
# Bottom tab bar — 3rd "Meals" tab
# ---------------------------------------------------------------------------

class TestBottomTabBar:
    def test_meals_tab_present_on_pantry(self, client):
        sign_up(client, "alice@example.com", "Alice")
        resp = client.get("/pantry")
        body = _body(resp)
        assert 'href="/meals"' in body, "Meals tab missing on /pantry"

    def test_meals_tab_active_state(self, client):
        sign_up(client, "alice@example.com", "Alice")
        resp = client.get("/meals")
        body = _body(resp)
        # Active tab is marked with aria-current="page"
        # Find the meals anchor and verify it has aria-current="page".
        # Cheap parse: look for the substring sequence that means "Meals
        # link is the current page".
        meals_idx = body.find('href="/meals"')
        assert meals_idx != -1
        # Grab a window around the meals link for inspection
        window = body[max(0, meals_idx - 200):meals_idx + 200]
        assert 'aria-current="page"' in window, (
            "Meals tab should be marked aria-current=page on /meals"
        )

    def test_meals_tab_inactive_on_pantry(self, client):
        sign_up(client, "alice@example.com", "Alice")
        resp = client.get("/pantry")
        body = _body(resp)
        meals_idx = body.find('href="/meals"')
        window = body[max(0, meals_idx - 200):meals_idx + 200]
        assert 'aria-current="false"' in window, (
            "Meals tab should be marked aria-current=false on /pantry"
        )


# ---------------------------------------------------------------------------
# +Shop All Missing bulk action
# ---------------------------------------------------------------------------

class TestShopAllMissing:
    def _setup(self, client, app, monkeypatch, plan=CANNED_PLAN_A):
        sign_up(client, "alice@example.com", "Alice")
        _stub_openai(monkeypatch, plan)
        _make_plan(client)
        with app.app_context():
            from models import MealPlan
            return MealPlan.query.one().id

    def test_bulk_add_creates_one_row_per_need_item(
            self, client, app, monkeypatch):
        plan_id = self._setup(client, app, monkeypatch)

        resp = client.post(
            f"/meal-plan/{plan_id}/need-all-to-shopping", htmx=True,
        )
        assert resp.status_code == 200

        with app.app_context():
            from models import ShoppingItem
            rows = ShoppingItem.query.all()
            # CANNED_PLAN_A has 3 need items
            assert len(rows) == 3
            names = sorted(r.name for r in rows)
            assert names == sorted(CANNED_PLAN_A["need"])
            # Each row carries the AI-source provenance note
            for r in rows:
                assert "Suggested by AI for: Spaghetti carbonara" in r.notes

    def test_bulk_add_returns_hx_trigger_with_count(
            self, client, app, monkeypatch):
        plan_id = self._setup(client, app, monkeypatch)
        resp = client.post(
            f"/meal-plan/{plan_id}/need-all-to-shopping", htmx=True,
        )
        trigger = resp.headers.get("HX-Trigger")
        assert trigger, "HX-Trigger header missing"
        parsed = json.loads(trigger)
        assert "shopping:added-bulk" in parsed
        assert parsed["shopping:added-bulk"]["count"] == 3, (
            "HX-Trigger should report the number of items added so the "
            "toast can show 'Added N items to shopping'."
        )

    def test_bulk_add_with_no_need_items_still_returns_200(
            self, client, app, monkeypatch):
        """Empty need list → 200, 0 rows created, still emits the
        trigger so the client doesn't display an error."""
        plan_id = self._setup(client, app, monkeypatch, plan=CANNED_PLAN_NO_NEED)

        resp = client.post(
            f"/meal-plan/{plan_id}/need-all-to-shopping", htmx=True,
        )
        assert resp.status_code == 200
        with app.app_context():
            from models import ShoppingItem
            assert ShoppingItem.query.count() == 0

    def test_bulk_add_is_not_idempotent(self, client, app, monkeypatch):
        """Matches the existing single-item +Shop behavior: two taps =
        two sets of rows. Predictability over silent dedupe."""
        plan_id = self._setup(client, app, monkeypatch)

        client.post(f"/meal-plan/{plan_id}/need-all-to-shopping", htmx=True)
        client.post(f"/meal-plan/{plan_id}/need-all-to-shopping", htmx=True)

        with app.app_context():
            from models import ShoppingItem
            assert ShoppingItem.query.count() == 6, (
                "two taps of +Shop All on a plan with 3 need items "
                "should produce 6 shopping rows (no dedupe)"
            )

    def test_bulk_add_cross_household_returns_404(
            self, two_clients, app, monkeypatch):
        alice, bob = two_clients
        sign_up(alice, "alice@example.com", "Alice")
        sign_up(bob, "bob@example.com", "Bob")
        _stub_openai(monkeypatch, CANNED_PLAN_A)
        _make_plan(alice)
        with app.app_context():
            from models import MealPlan
            alices_plan_id = MealPlan.query.one().id

        resp = bob.post(
            f"/meal-plan/{alices_plan_id}/need-all-to-shopping", htmx=True,
        )
        # 404 not 403 — don't leak the existence of cross-household plans
        assert resp.status_code == 404
        with app.app_context():
            from models import ShoppingItem
            assert ShoppingItem.query.count() == 0

    def test_bulk_add_anonymous_redirects_to_login(self, client):
        resp = client.post("/meal-plan/1/need-all-to-shopping")
        assert resp.status_code == 302
        assert "/login" in resp.headers["Location"]

    def test_bulk_add_unknown_plan_returns_404(
            self, client, app, monkeypatch):
        sign_up(client, "alice@example.com", "Alice")
        resp = client.post(
            "/meal-plan/99999/need-all-to-shopping", htmx=True,
        )
        assert resp.status_code == 404
