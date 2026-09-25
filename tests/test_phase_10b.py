"""
Phase 10B regression suite — smooth shopping-list view transitions.

Each shopping mutation uses htmx's `transition:true` swap modifier. When the
browser supports the View Transitions API, rows retain their own transition
name so checking an item off animates its move into the checked section.
Browsers without the API safely fall back to a normal htmx swap.

Tier-1 dev loop:

    pytest tests/test_phase_10b.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.conftest import Client, sign_up


ROOT = Path(__file__).resolve().parent.parent


def _add_shopping(client: Client, name: str) -> str:
    response = client.post("/shopping", data={"name": name}, htmx=True)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def _opening_tag_containing(html: str, marker: str) -> str:
    marker_index = html.index(marker)
    start = html.rfind("<input", 0, marker_index)
    if start == -1:
        start = html.rfind("<button", 0, marker_index)
    assert start != -1, f"No control found before {marker!r}"
    return html[start:html.index(">", marker_index) + 1]


class TestShoppingListViewTransitions:
    def test_persisted_row_has_a_stable_transition_name(self, client):
        sign_up(client, "alice@example.com", "Alice")
        html = _add_shopping(client, "Milk")
        item_id = re.search(r'id="shopping-item-(\d+)"', html).group(1)

        assert (
            f'data-shopping-transition-row="{item_id}"' in html
        ), "Persisted rows need stable names so reordering can animate."
        page = client.get("/shopping").get_data(as_text=True)
        assert "nameShoppingTransitionRows" in page
        assert "row.style.viewTransitionName" in page

    def test_checkbox_toggle_opts_into_view_transition(self, client):
        sign_up(client, "alice@example.com", "Alice")
        html = _add_shopping(client, "Milk")

        checkbox = _opening_tag_containing(html, 'type="checkbox"')
        assert 'hx-target="#shopping-list"' in checkbox
        assert 'hx-swap="outerHTML transition:true"' in checkbox

    def test_shopping_add_and_actions_opt_into_view_transitions(self, client):
        sign_up(client, "alice@example.com", "Alice")
        _add_shopping(client, "Milk")
        client.post("/shopping/1/toggle", htmx=True)
        html = client.get("/shopping").get_data(as_text=True)

        # Add, delete, clear checked, and move-home controls all rerender the
        # same shopping-list partial, so each needs the same swap modifier.
        assert html.count('hx-swap="outerHTML transition:true"') >= 5
        assert "swap: 'outerHTML transition:true'" in html
        assert "target === '#shopping-list'" in html


class TestViewTransitionStyles:
    def test_transition_css_respects_reduced_motion(self):
        css = (ROOT / "assets/css/app.css").read_text()
        assert "@supports (view-transition-name: none)" in css
        assert "prefers-reduced-motion: no-preference" in css
        assert "::view-transition-group(*)" in css
