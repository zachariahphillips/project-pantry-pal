"""
Phase 6J regression suite — shopping quick-add in-flight state.

Adjacent interaction chunk from `PLANS/ux-improvements-plan.md` §3.2.
The round "+" button in the shopping quick-add bar used to stay visually
unchanged while htmx was posting. A fast tap could feel ignored and invite
a second tap. 6J lets htmx disable that exact button during the request and
adds a subtle disabled/pulse treatment.

Tier-1 dev loop:

    pytest tests/test_phase_6j.py -q
"""
from __future__ import annotations

from tests.conftest import Client, sign_up


def _body(resp) -> str:
    return resp.get_data(as_text=True)


def _quick_add_button(html: str) -> str:
    marker = 'aria-label="Add to shopping list"'
    marker_idx = html.index(marker)
    start = html.rfind("<button", 0, marker_idx)
    assert start != -1, "shopping quick-add button not found"
    end = html.index(">", marker_idx) + 1
    return html[start:end]


def test_shopping_quick_add_button_disables_itself_in_flight(client: Client):
    """htmx disables only the tapped plus button while POST /shopping runs."""
    sign_up(client, "quickadd@example.com", "Quick")

    body = _body(client.get("/shopping"))
    button = _quick_add_button(body)

    assert 'hx-disabled-elt="this"' in button


def test_shopping_quick_add_button_has_disabled_visual_feedback(
        client: Client):
    """The disabled state is visible enough to discourage double taps."""
    sign_up(client, "quickadd-state@example.com", "Quick State")

    body = _body(client.get("/shopping"))
    button = _quick_add_button(body)

    assert "disabled:cursor-progress" in button
    assert "disabled:animate-pulse" in button
    assert "disabled:opacity-70" in button


def test_press_feedback_survives_quick_add_in_flight_state(client: Client):
    """6J layers onto 6I; the normal tap affordance remains in place."""
    sign_up(client, "quickadd-press@example.com", "Quick Press")

    body = _body(client.get("/shopping"))
    button = _quick_add_button(body)

    assert "active:scale-[0.98]" in button
    assert "active:bg-green-800" in button
