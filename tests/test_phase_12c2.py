"""
Phase 12C.2 regression suite — request-scoped dietary preferences.

Vegetarian and Gluten-free chips are canonical, validated values. They are
sent to the AI separately from the saved free-text request.

Tier-1 dev loop:

    pytest tests/test_phase_12c2.py -q
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from extensions import db
from models import MealPlan
from tests.conftest import sign_up


PLAN = {
    "meal_name": "Test dinner",
    "have": [],
    "need": [],
    "steps": ["Cook it."],
}


def _add_pantry(client, name: str) -> None:
    response = client.post("/pantry", htmx=True, data={
        "name": name,
        "quantity": "",
        "unit": "",
        "notes": "",
        "expiry_date": "",
    })
    assert response.status_code in (200, 204)


class _CapturingOpenAIClient:
    last_kwargs: dict | None = None

    def __init__(self, *_args, **_kwargs):
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        type(self).last_kwargs = kwargs
        return SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content=json.dumps(PLAN))),
        ])


class TestMealPlanDietaryPreferences:
    def test_unlocked_planner_renders_dietary_request_chips(self, client):
        sign_up(client, "alice@example.com", "Alice")
        for name in ("Pasta", "Eggs", "Olive oil"):
            _add_pantry(client, name)

        html = client.get("/pantry").get_data(as_text=True)

        assert "data-meal-plan-dietary-preferences" in html
        assert 'name="dietary_preferences"' in html
        assert 'value="vegetarian"' in html
        assert 'value="gluten_free"' in html
        assert "Gluten-free" in html
        assert 'data-prompt-chip="A vegetarian meal"' not in html

    def test_selected_diets_reach_ai_without_rewriting_saved_prompt(
        self, client, app, monkeypatch,
    ):
        captured = {}

        def fake_openai(prompt, pantry, servings=2, dietary_preferences=()):
            captured["prompt"] = prompt
            captured["servings"] = servings
            captured["diets"] = dietary_preferences
            return PLAN, None

        monkeypatch.setattr("app._ask_openai_for_meal", fake_openai)
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Pasta")

        response = client.post(
            "/meal-plan",
            data={
                "prompt": "pasta night",
                "servings": "4",
                "dietary_preferences": ["vegetarian", "gluten_free"],
            },
            htmx=True,
        )

        assert response.status_code == 200
        assert captured == {
            "prompt": "pasta night",
            "servings": 4,
            "diets": ("vegetarian", "gluten_free"),
        }
        with app.app_context():
            assert MealPlan.query.one().prompt == "pasta night"

    @pytest.mark.parametrize(
        "diets",
        [["vegan"], ["vegetarian", "vegetarian"], ["gluten free"]],
    )
    def test_invalid_dietary_values_are_rejected_before_ai_call(
        self, client, app, monkeypatch, diets,
    ):
        monkeypatch.setattr(
            "app._ask_openai_for_meal",
            lambda *_args: pytest.fail("AI must not run for invalid diets"),
        )
        sign_up(client, "alice@example.com", "Alice")

        response = client.post(
            "/meal-plan",
            data={"prompt": "dinner", "dietary_preferences": diets},
            htmx=True,
        )

        assert response.status_code == 422
        assert "Choose valid dietary preferences." in response.get_data(
            as_text=True,
        )
        with app.app_context():
            assert MealPlan.query.count() == 0

    def test_dietary_values_are_explicit_system_instructions(
        self, app, monkeypatch,
    ):
        _CapturingOpenAIClient.last_kwargs = None
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setattr("openai.OpenAI", _CapturingOpenAIClient)
        from app import _ask_openai_for_meal

        with app.app_context():
            result, error_kind = _ask_openai_for_meal(
                "dinner",
                [],
                dietary_preferences=("vegetarian", "gluten_free"),
            )

        assert result == PLAN
        assert error_kind is None
        system = _CapturingOpenAIClient.last_kwargs["messages"][0]["content"]
        assert "Vegetarian, Gluten-free" in system
        assert "Vegetarian excludes meat and seafood." in system
        assert "Gluten-free excludes gluten-containing ingredients" in system
