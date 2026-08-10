"""
Phase 6T regression suite — shopping dupe delta unit copy.

Small copy-polish chunk from `PLANS/ux-improvements-plan.md` §4.1.
The shopping duplicate confirm button used to render labels like
`Update existing (+2 head)`, which reads awkwardly for grocery/container
units. 6T keeps clear measurement units in the visible delta and hides
ambiguous units there; the hidden pending payload still carries the raw
unit for merge/add behavior.

Tier-1 dev loop:

    pytest tests/test_phase_6t.py -q
"""
from __future__ import annotations

import re

import pytest

from tests.conftest import Client, sign_up


def _body(resp) -> str:
    return resp.get_data(as_text=True)


def _add_shopping(c: Client, name: str, qty: str = "", unit: str = ""):
    return c.post("/shopping", htmx=True, data={
        "name": name,
        "quantity": qty,
        "unit": unit,
        "notes": "",
        "submit": "Add",
    })


def _merge_button(html: str) -> str:
    match = re.search(
        r'(<button[^>]*data-testid="shopping-dupe-confirm-merge"[\s\S]*?</button>)',
        html,
    )
    assert match, "shopping duplicate merge button not found"
    return match.group(1)


@pytest.mark.parametrize("unit", ["head", "bag", "jar"])
def test_ambiguous_grocery_units_are_hidden_from_merge_delta(
        client: Client, unit: str):
    sign_up(client, f"dupe-{unit}@example.com", f"Dupe {unit}")
    _add_shopping(client, "Cabbage")

    body = _body(_add_shopping(client, "Cabbage", qty="2", unit=unit))
    button = _merge_button(body)

    assert "Update existing" in button
    assert "(+2)" in button
    assert f"(+2 {unit})" not in button


def test_clear_measurement_unit_stays_in_merge_delta(client: Client):
    sign_up(client, "dupe-gal@example.com", "Dupe Gal")
    _add_shopping(client, "Milk")

    body = _body(_add_shopping(client, "Milk", qty="2", unit="gal"))
    button = _merge_button(body)

    assert "(+2 gal)" in button


def test_hidden_pending_payload_keeps_ambiguous_unit(client: Client):
    sign_up(client, "dupe-hidden@example.com", "Dupe Hidden")
    _add_shopping(client, "Cabbage")

    body = _body(_add_shopping(client, "Cabbage", qty="2", unit="head"))

    assert 'name="unit" value="head"' in body
