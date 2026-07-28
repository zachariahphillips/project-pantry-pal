"""
Phase 6K regression suite — shopping empty-state hero.

Small UX chunk from `PLANS/ux-improvements-plan.md` §1.3. Phase 5B
already gave the true-empty shopping list a basket card and ghost-row
preview. 6K locks that card in as a proper hero state: stable wrapper id,
labelled heading, and copy that names both ways into the shopping list
(the add bar above and + Shop from pantry rows).

Tier-1 dev loop:

    pytest tests/test_phase_6k.py -q
"""
from __future__ import annotations

import re

from tests.conftest import Client, sign_up


def _shopping_body(c: Client, path: str = "/shopping", *, htmx: bool = False) -> str:
    return c.get(path, htmx=htmx).get_data(as_text=True)


def _add_shopping(c: Client, name: str = "Tortillas"):
    return c.post("/shopping", htmx=True, data={
        "name": name, "quantity": "", "unit": "", "notes": "",
        "submit": "Add",
    })


def test_true_empty_shopping_state_has_labelled_hero(client: Client):
    """The no-query empty state is now a stable, labelled hero card."""
    sign_up(client, "emptyhero@example.com", "Empty Hero")

    html = _shopping_body(client)

    assert 'id="shopping-empty-hero"' in html
    assert 'aria-labelledby="shopping-empty-heading"' in html
    assert re.search(
        r'<h2 id="shopping-empty-heading"[^>]*>'
        r'Nothing on your shopping list yet</h2>',
        html,
    )


def test_true_empty_shopping_hero_names_both_entry_points(client: Client):
    """Copy points users to direct add and the pantry row +Shop path."""
    sign_up(client, "emptycopy@example.com", "Empty Copy")

    html = _shopping_body(client)

    assert "Use the add bar above" in html
    assert re.search(
        r'<span class="font-medium text-stone-700">\+ Shop</span>',
        html,
    )
    assert "on any pantry item" in html


def test_true_empty_shopping_hero_renders_in_htmx_partial(client: Client):
    """The hero lives inside the partial, so htmx refreshes keep it."""
    sign_up(client, "emptyhtmx@example.com", "Empty Htmx")

    html = _shopping_body(client, "/shopping?q=", htmx=True)

    assert html.lstrip().startswith('<div id="shopping-list"')
    assert 'id="shopping-empty-hero"' in html
    assert 'id="shopping-empty-heading"' in html


def test_search_empty_state_stays_lean_not_hero(client: Client):
    """A no-match search should stay a concise result message."""
    sign_up(client, "searchlean@example.com", "Search Lean")
    _add_shopping(client, "Tortillas")

    html = _shopping_body(client, "/shopping?q=zzzz")

    assert 'No matches for "zzzz".' in html
    assert 'id="shopping-empty-hero"' not in html
    assert 'id="shopping-empty-heading"' not in html
    assert "Use the add bar above" not in html
