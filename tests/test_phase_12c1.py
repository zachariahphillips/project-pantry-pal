"""
Phase 12C.1 regression suite — request-scoped portions.

The portions stepper sends a bounded serving count with the meal request.
The server validates it and supplies it as a separate system instruction,
without rewriting the user's stored meal prompt.

Tier-1 dev loop:

    pytest tests/test_phase_12c1.py -q
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


class TestMealPlanPortions:
    def test_unlocked_planner_renders_the_two_serving_stepper(
        self, client,
    ):
        sign_up(client, "alice@example.com", "Alice")
        for name in ("Pasta", "Eggs", "Olive oil"):
            _add_pantry(client, name)

        html = client.get("/pantry").get_data(as_text=True)

        assert "data-meal-plan-servings" in html
        assert 'name="servings"' in html
        assert 'value="2"' in html
        assert "Decrease servings" in html
        assert "Increase servings" in html

    def test_custom_servings_reaches_the_meal_planner_without_rewriting_prompt(
        self, client, app, monkeypatch,
    ):
        captured = {}

        def fake_openai(prompt, pantry, servings=2):
            captured["prompt"] = prompt
            captured["servings"] = servings
            captured["pantry"] = [item.name for item in pantry]
            return PLAN, None

        monkeypatch.setattr("app._ask_openai_for_meal", fake_openai)
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Pasta")

        response = client.post(
            "/meal-plan",
            data={"prompt": "pasta night", "servings": "4"},
            htmx=True,
        )

        assert response.status_code == 200
        assert captured == {
            "prompt": "pasta night",
            "servings": 4,
            "pantry": ["Pasta"],
        }
        with app.app_context():
            plan = MealPlan.query.one()
            assert plan.prompt == "pasta night"

    @pytest.mark.parametrize("servings", ["0", "13", "-1", "1.5", "four"])
    def test_invalid_servings_are_rejected_before_ai_call(
        self, client, app, monkeypatch, servings,
    ):
        monkeypatch.setattr(
            "app._ask_openai_for_meal",
            lambda *_args: pytest.fail("AI must not run for invalid servings"),
        )
        sign_up(client, f"{servings}@example.com", "Alice")

        response = client.post(
            "/meal-plan",
            data={"prompt": "dinner", "servings": servings},
            htmx=True,
        )

        assert response.status_code == 422
        assert "Choose between 1 and 12 servings." in response.get_data(
            as_text=True,
        )
        with app.app_context():
            assert MealPlan.query.count() == 0

    def test_serving_count_is_a_system_instruction(
        self, app, monkeypatch,
    ):
        _CapturingOpenAIClient.last_kwargs = None
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setattr("openai.OpenAI", _CapturingOpenAIClient)
        from app import _ask_openai_for_meal

        with app.app_context():
            result, error_kind = _ask_openai_for_meal(
                "dinner", [], servings=4,
            )

        assert result == PLAN
        assert error_kind is None
        system = _CapturingOpenAIClient.last_kwargs["messages"][0]["content"]
        assert "This meal must make 4 servings." in system
        assert "exactly 4 servings" in system
