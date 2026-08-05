"""
Phase 6R regression suite — clearer pantry density toggle label.

Small visual-polish chunk from `PLANS/ux-improvements-plan.md` §2.5.
The compact-mode control previously read as `View` + `Compact`, which
made the feature hard to parse. 6R keeps the existing single toggle
behavior but labels the control as `Density`.

Tier-1 dev loop:

    pytest tests/test_phase_6r.py -q
"""
from __future__ import annotations

import re

from tests.conftest import Client, sign_up


def _body(resp) -> str:
    return resp.get_data(as_text=True)


def _add_pantry(c: Client, name: str):
    return c.post("/pantry", htmx=True, data={
        "name": name,
        "quantity": "1",
        "unit": "ct",
        "notes": "",
        "submit": "Add",
    })


def _density_block(html: str) -> str:
    match = re.search(
        r'(<div [^>]*aria-label="Pantry density"[\s\S]*?</div>)',
        html,
    )
    assert match, "density control region not found"
    return match.group(1)


def _compact_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s)


def test_density_control_uses_clear_label(client: Client):
    sign_up(client, "density-label@example.com", "Density Label")
    _add_pantry(client, "Milk")

    block = _compact_whitespace(_density_block(_body(client.get("/pantry"))))

    assert "> Density <" in block
    assert "> View <" not in block


def test_density_control_keeps_existing_compact_toggle_wiring(client: Client):
    sign_up(client, "density-wiring@example.com", "Density Wiring")
    _add_pantry(client, "Milk")

    block = _density_block(_body(client.get("/pantry")))

    assert 'hx-post="/pantry/density"' in block
    assert 'hx-vals=\'{"density": "compact"}\'' in block
    assert re.search(
        r'<button[^>]*aria-pressed="false"[^>]*>\s*Compact\s*</button>',
        block,
        re.DOTALL,
    )


def test_compact_state_still_flips_toggle_target_to_roomy(client: Client):
    sign_up(client, "density-compact@example.com", "Density Compact")
    _add_pantry(client, "Milk")

    resp = client.post(
        "/pantry/density",
        htmx=True,
        data={"density": "compact"},
    )
    block = _density_block(_body(resp))

    assert 'hx-vals=\'{"density": "roomy"}\'' in block
    assert re.search(
        r'<button[^>]*aria-pressed="true"[^>]*>\s*Compact\s*</button>',
        block,
        re.DOTALL,
    )
