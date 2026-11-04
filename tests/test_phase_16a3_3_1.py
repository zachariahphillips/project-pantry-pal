"""
Phase 16A.3.3.1 regression suite — structured quantities for missing needs.

New AI plans may preserve a quantity/unit detail for a missing ingredient,
but legacy name-only plans and malformed AI fields remain safe. No current
Shopping or meal-card behavior consumes these details yet.

Tier-1 dev loop:

    pytest tests/test_phase_3a.py tests/test_phase_3c.py \
        tests/test_phase_16a3_3_1.py -q
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from extensions import db
from models import MealPlan, User
from tests.conftest import sign_up


DETAILED_PLAN = {
    "meal_name": "Tomato pasta",
    "have": ["Pasta"],
    "need": ["Tomatoes", "Milk"],
    "need_details": [
        {"name": "Tomatoes", "quantity": 2, "unit": "cans"},
        {"name": "Milk", "quantity": 0.5, "unit": "cup"},
    ],
    "steps": ["Cook it."],
}


def _create_plan(app, response: dict) -> int:
    with app.app_context():
        user = User.query.filter_by(email="alice@example.com").one()
        plan = MealPlan(
            household_id=user.household_id,
            created_by_user_id=user.id,
            prompt="Dinner",
            response_json=json.dumps(response),
            meal_name="Test dinner",
        )
        db.session.add(plan)
        db.session.commit()
        return plan.id


class _CapturingOpenAIClient:
    last_kwargs: dict | None = None

    def __init__(self, *_args, **_kwargs):
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        type(self).last_kwargs = kwargs
        return SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(
                content=json.dumps(DETAILED_PLAN),
            )),
        ])


class TestStructuredNeedDetails:
    def test_new_plan_stores_safe_quantity_details_without_changing_need(
        self, client, app, monkeypatch,
    ):
        monkeypatch.setattr(
            "app._ask_openai_for_meal",
            lambda prompt, pantry: (DETAILED_PLAN, None),
        )
        sign_up(client, "alice@example.com", "Alice")

        response = client.post(
            "/meal-plan", data={"prompt": "pasta"}, htmx=True,
        )

        assert response.status_code == 200
        with app.app_context():
            plan = MealPlan.query.one()
            assert plan.need == ["Tomatoes", "Milk"]
            assert plan.need_details == [
                {"name": "Tomatoes", "quantity": 2.0, "unit": "cans"},
                {"name": "Milk", "quantity": 0.5, "unit": "cup"},
            ]
            assert json.loads(plan.response_json)["need_details"] == (
                DETAILED_PLAN["need_details"]
            )

    def test_legacy_and_invalid_details_are_ignored_safely(
        self, client, app,
    ):
        sign_up(client, "alice@example.com", "Alice")
        legacy_id = _create_plan(app, {
            "meal_name": "Legacy",
            "have": [],
            "need": ["Milk"],
            "steps": ["Cook it."],
        })
        invalid_id = _create_plan(app, {
            "meal_name": "Mixed details",
            "have": [],
            "need": ["Milk", "Tomatoes", "Eggs"],
            "need_details": [
                {"name": " milk ", "quantity": 1, "unit": "CUP"},
                {"name": "Tomatoes", "quantity": 2, "unit": "cans"},
                {"name": "Tomatoes", "quantity": 3, "unit": "cans"},
                {"name": "Eggs", "quantity": 0, "unit": "ea"},
                {"name": "Eggs", "quantity": 10001, "unit": "ea"},
                {"name": "Eggs", "quantity": 10 ** 100, "unit": "ea"},
                {"name": "Unknown", "quantity": 1, "unit": "ea"},
                {"name": "Milk", "quantity": True, "unit": "cup"},
            ],
            "steps": ["Cook it."],
        })

        with app.app_context():
            legacy = db.session.get(MealPlan, legacy_id)
            invalid = db.session.get(MealPlan, invalid_id)
            assert legacy.need_details == []
            assert invalid.need_details == [
                {"name": "Milk", "quantity": 1.0, "unit": "cup"},
                {"name": "Tomatoes", "quantity": 2.0, "unit": "cans"},
            ]

    def test_openai_contract_requests_matching_standardized_details(
        self, app, monkeypatch,
    ):
        _CapturingOpenAIClient.last_kwargs = None
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setattr("openai.OpenAI", _CapturingOpenAIClient)
        from app import _ask_openai_for_meal

        with app.app_context():
            result, error_kind = _ask_openai_for_meal("pasta", [])

        assert result == DETAILED_PLAN
        assert error_kind is None
        system = _CapturingOpenAIClient.last_kwargs["messages"][0]["content"]
        assert '"need_details"' in system
        assert "`name` must exactly match" in system
        assert "`quantity` must be a positive JSON number" in system
        assert "ea, g, kg, oz, lb" in system
