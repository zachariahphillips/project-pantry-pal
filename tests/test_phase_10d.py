"""
Phase 10D regression suite — empty-state illustrations.

Decorative inline SVGs add warmth to true empty Pantry and Shopping states.
They must remain absent from search-empty and populated states, where the
illustrations would be misleading or visually noisy.

Tier-1 dev loop:

    pytest tests/test_phase_10d.py -q
"""
from __future__ import annotations

from tests.conftest import Client, sign_up


def _add_pantry(client: Client, name: str) -> None:
    response = client.post("/pantry", htmx=True, data={
        "name": name, "quantity": "", "unit": "", "notes": "",
    })
    assert response.status_code in (200, 204)


def _add_shopping(client: Client, name: str) -> None:
    response = client.post("/shopping", htmx=True, data={
        "name": name, "quantity": "", "unit": "", "notes": "",
    })
    assert response.status_code == 200


class TestPantryEmptyIllustration:
    def test_true_empty_pantry_shows_decorative_illustration(self, client):
        sign_up(client, "alice@example.com", "Alice")
        html = client.get("/pantry").get_data(as_text=True)

        assert 'data-empty-state-illustration="pantry"' in html
        assert 'aria-hidden="true"' in html
        assert 'id="pantry-add-hero"' in html

    def test_pantry_illustration_retires_after_first_item(self, client):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Olive oil")

        html = client.get("/pantry").get_data(as_text=True)
        assert 'data-empty-state-illustration="pantry"' not in html


class TestShoppingEmptyIllustration:
    def test_true_empty_shopping_list_shows_decorative_illustration(self, client):
        sign_up(client, "alice@example.com", "Alice")
        html = client.get("/shopping").get_data(as_text=True)

        assert 'data-empty-state-illustration="shopping"' in html
        assert 'aria-hidden="true"' in html
        assert 'id="shopping-empty-hero"' in html

    def test_shopping_illustration_is_absent_when_searching_or_populated(self, client):
        sign_up(client, "alice@example.com", "Alice")
        search_html = client.get("/shopping?q=milk").get_data(as_text=True)
        assert 'data-empty-state-illustration="shopping"' not in search_html

        _add_shopping(client, "Milk")
        populated_html = client.get("/shopping").get_data(as_text=True)
        assert 'data-empty-state-illustration="shopping"' not in populated_html
