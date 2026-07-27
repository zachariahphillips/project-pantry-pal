"""
Phase 6H regression suite — longer Undo toast grace window.

Small interaction chunk from `PLANS/ux-improvements-plan.md` §3.3.
Before 6H, action-bearing toasts (the ones with an Undo CTA) stayed
visible for 5 seconds. On mobile that is short enough to miss after an
accidental delete or "I'm home" move, so 6H stretches only those toasts
to 7 seconds.

These tests intentionally read the template source instead of trying to
drive browser timers in pytest. The behavior is a small literal in
`showToast()`: action toasts use the long duration, text-only toasts
keep the short 1.8s duration.

Tier-1 dev loop:

    pytest tests/test_phase_6h.py -q
"""
from __future__ import annotations

from pathlib import Path


BASE_TEMPLATE = (
    Path(__file__).resolve().parents[1] / "templates" / "base.html"
)


def _base_template_source() -> str:
    return BASE_TEMPLATE.read_text()


def test_action_toasts_stay_visible_for_seven_seconds():
    """Undo toasts need the broader mobile grace window from UX §3.3."""
    src = _base_template_source()

    assert "with action: 7s" in src
    assert "Action-bearing toasts hang around for 7s" in src
    assert "const duration = (action && action.url) ? 7000 : 1800;" in src


def test_text_only_toasts_keep_short_duration():
    """Merge/add confirmations should still disappear quickly."""
    src = _base_template_source()

    assert "text-only: 1.8s" in src
    assert "pure\n      // info toasts stay at 1.8s" in src
    assert "const duration = (action && action.url) ? 7000 : 1800;" in src


def test_old_five_second_action_window_is_retired():
    """Guards the exact 6H regression: drifting back to a 5s Undo window."""
    src = _base_template_source()

    assert "with action: 5s" not in src
    assert "? 5000 : 1800" not in src
