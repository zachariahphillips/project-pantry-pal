"""
Phase 8D regression suite — real-device tap-target polish.

The phone audit after the no-cost deploy runbook pass found signed-in utility
actions that rendered below the 44px thumb target already used by the main tabs
and add buttons. 8D raises those small controls without changing the flows.

Tier-1 dev loop:

    pytest tests/test_phase_8d.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

from tests.conftest import Client, id_for, sign_up


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
PLAN = ROOT / "PLAN.md"


def _class_for_button(html: str, label: str) -> str:
    match = re.search(
        rf'<button[^>]*class="([^"]+)"[^>]*>\s*{re.escape(label)}\s*</button>',
        html,
        re.DOTALL,
    )
    assert match, f"{label!r} button not found"
    return match.group(1)


def test_signed_in_header_sign_out_is_a_thumb_sized_target(client: Client):
    body = sign_up(client, "thumb-header@example.com", "Thumb Header")

    classes = _class_for_button(body, "Sign out")

    assert "inline-flex" in classes
    assert "h-11" in classes
    assert "rounded-xl" in classes
    assert "focus:ring-2" in classes


def test_shopping_checked_actions_are_thumb_sized_targets(client: Client):
    sign_up(client, "thumb-shopping@example.com", "Thumb Shopping")
    body = client.post(
        "/shopping",
        data={"name": "Avocados", "quantity": "4", "unit": "ea", "notes": ""},
        htmx=True,
    ).get_data(as_text=True)
    item_id = id_for(body, "Avocados", "shopping-item")
    assert item_id is not None

    body = client.post(f"/shopping/{item_id}/toggle", htmx=True).get_data(as_text=True)

    clear_classes = _class_for_button(body, "Clear checked")
    home_classes = _class_for_button(body, "I'm home →")
    assert "h-11" in clear_classes
    assert "h-11" in home_classes
    assert "rounded-xl" in clear_classes
    assert "rounded-xl" in home_classes


def test_phase_8d_is_documented_as_completed_mobile_polish():
    readme = README.read_text()
    plan = PLAN.read_text()

    assert "real-device tap-target polish" in readme
    assert "real-device tap-target polish" in plan


def test_phase_history_marks_8d_done():
    readme = README.read_text()

    assert "- **Phase 8C:** No-cost deploy runbook closeout — done" in readme
    assert "- **Phase 8D:** Real-device tap-target polish — done" in readme
